import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from typer.testing import CliRunner

from app.services import nightly_sync as service

NOW = datetime(2026, 9, 11, 9, 20, tzinfo=timezone.utc)
SLOT = datetime(2026, 9, 11, 19, 30, tzinfo=timezone.utc)


@pytest.fixture
def store(monkeypatch):
    state = {"saved": {}, "checkpoints": [], "locked": False, "calls": []}

    @asynccontextmanager
    async def lock():
        if state["locked"]:
            yield False
            return
        state["locked"] = True
        try:
            yield True
        finally:
            state["locked"] = False

    async def load():
        return deepcopy(state["saved"])

    async def save(value):
        state["saved"] = deepcopy(value)
        state["checkpoints"].append(deepcopy(value))

    async def stage(name):
        assert state["saved"]["slot"] == SLOT.isoformat()
        assert state["saved"]["current_stage"] == name
        state["calls"].append(name)
        return {"count": 1}

    monkeypatch.setenv("PIF_DIRECTORY_NATIVE", "true")
    monkeypatch.setenv("PIF_RESEARCH_MAINTENANCE_ENABLED", "true")
    monkeypatch.setenv("FRONT_SYNC_ENABLED", "true")
    monkeypatch.setenv("POSSIBLEOS_NIGHTLY_SYNC_ENABLED", "true")
    monkeypatch.setattr(service, "_run_lock", lock)
    monkeypatch.setattr(service, "_load_state", load)
    monkeypatch.setattr(service, "_save_state", save)
    monkeypatch.setattr(service, "_run_stage", stage)
    monkeypatch.setattr(service, "_front_failed", AsyncMock())
    monkeypatch.setattr(service, "_now", lambda: NOW)
    monkeypatch.setattr(service, "_runtime", {"scheduler_active": False, "next_run_at": None, "last_error": None})
    return state


@pytest.mark.parametrize("now,expected", [
    (NOW, SLOT),
    (SLOT - timedelta(seconds=1), SLOT),
    (SLOT, SLOT + timedelta(days=1)),
    (SLOT + timedelta(hours=1), SLOT + timedelta(days=1)),
    (datetime(2026, 12, 31, 20, tzinfo=timezone.utc), datetime(2027, 1, 1, 19, 30, tzinfo=timezone.utc)),
])
def test_slot_timezone_and_date_rollover(now, expected):
    assert service.next_slot(now) == expected
    assert service.next_slot(now).astimezone(service.ZONE).hour == 1


def test_order_claim_before_work_and_same_slot_even_after_restart(store):
    result = asyncio.run(service.run_slot(SLOT))
    assert result["status"] == "completed"
    assert store["calls"] == list(service.STAGES)
    service._runtime.clear()  # Durable claim does not depend on process memory.
    assert asyncio.run(service.run_slot(SLOT))["status"] == "already_claimed"
    assert len(store["calls"]) == 5


def test_overlap_rejected_without_work(store):
    store["locked"] = True
    assert asyncio.run(service.run_slot(SLOT)) == {"status": "busy"}
    assert store["checkpoints"] == []
    assert store["calls"] == []


def test_front_nested_status_payload_is_success(store, monkeypatch):
    async def stage(name):
        return {"status": {"sync_health": {"last_error": None}}} if name == "front" else {}

    monkeypatch.setattr(service, "_run_stage", stage)
    result = asyncio.run(service.run_slot(SLOT))
    assert result["status"] == "completed"
    assert result["stages"]["front"]["status"] == "completed"


def test_errors_continue_through_front_to_maintenance_and_no_repeat(store, monkeypatch):
    async def run(name):
        store["calls"].append(name)
        if name in {"firm_sync", "front"}:
            raise TimeoutError("test upstream timeout")
        if name == "contact_ingestion":
            return {"errors": 2, "inserted": 3}
        return {}

    monkeypatch.setattr(service, "_run_stage", run)
    result = asyncio.run(service.run_slot(SLOT))
    assert store["calls"] == list(service.STAGES)
    assert result["status"] == "partial"
    assert [error["stage"] for error in result["errors"]] == ["firm_sync", "contact_ingestion", "front"]
    assert result["stages"]["research_maintenance"]["status"] == "completed"
    service._front_failed.assert_awaited_once()
    assert asyncio.run(service.run_slot(SLOT))["status"] == "already_claimed"


def test_timeout_cancels_stage_then_continues(store, monkeypatch):
    original_wait = asyncio.wait_for
    configured_timeouts = []

    async def short_wait(coro, timeout):
        configured_timeouts.append(timeout)
        return await original_wait(coro, timeout=0.01)

    async def stage(name):
        store["calls"].append(name)
        if name == "front":
            await asyncio.Event().wait()
        return {}

    monkeypatch.setattr(service.asyncio, "wait_for", short_wait)
    monkeypatch.setattr(service, "_run_stage", stage)
    monkeypatch.setenv("POSSIBLEOS_NIGHTLY_STAGE_TIMEOUT_SECONDS", "77")
    result = asyncio.run(service.run_slot(SLOT))
    assert configured_timeouts == [77] * 5
    assert result["stages"]["front"]["status"] == "failed"
    assert result["stages"]["research_maintenance"]["status"] == "completed"


def test_flags_skip_only_their_stages(store, monkeypatch):
    monkeypatch.setenv("PIF_DIRECTORY_NATIVE", "false")
    monkeypatch.setenv("FRONT_SYNC_ENABLED", "false")
    result = asyncio.run(service.run_slot(SLOT))
    assert store["calls"] == ["research_maintenance"]
    assert result["stages"]["firm_sync"]["status"] == "disabled"
    monkeypatch.setenv("PIF_RESEARCH_MAINTENANCE_ENABLED", "false")
    assert service.stage_flags() == dict.fromkeys(service.STAGES, False)
    monkeypatch.setenv("POSSIBLEOS_NIGHTLY_SYNC_ENABLED", "false")
    assert asyncio.run(service.run_slot(SLOT + timedelta(days=1)))["status"] == "disabled"


def test_cancelled_slot_is_not_resumed(store, monkeypatch):
    monkeypatch.setattr(service, "_run_stage", AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(service.run_slot(SLOT))
    assert store["saved"]["status"] == "interrupted"
    assert asyncio.run(service.run_slot(SLOT))["status"] == "already_claimed"


@pytest.mark.parametrize("startup", [NOW, SLOT, SLOT + timedelta(minutes=1)])
def test_restart_waits_for_next_slot_without_catchup(store, monkeypatch, startup):
    monkeypatch.setattr(service, "_now", lambda: startup)
    observed = []

    async def sleep(seconds):
        observed.append(service.schedule_status())
        assert seconds > 0
        raise asyncio.CancelledError

    monkeypatch.setattr(service.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(service.nightly_sync_loop())
    assert observed[0]["next_run_at"] == service.next_slot(startup).isoformat()
    assert observed[0]["next_run_at_ist"].endswith("T01:00:00+05:30")
    assert store["calls"] == []
    assert not service.schedule_status()["scheduler_active"]


def test_loop_advances_before_failure_and_never_immediately_retries(store, monkeypatch):
    clock = [SLOT - timedelta(seconds=1)]
    monkeypatch.setattr(service, "_now", lambda: clock[0])
    run = AsyncMock(side_effect=RuntimeError("database offline"))
    monkeypatch.setattr(service, "run_slot", run)

    async def sleep(seconds):
        if clock[0] < SLOT:
            clock[0] = SLOT
        else:
            assert service.schedule_status()["next_run_at"] == (SLOT + timedelta(days=1)).isoformat()
            raise asyncio.CancelledError

    monkeypatch.setattr(service.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(service.nightly_sync_loop())
    run.assert_awaited_once_with(SLOT)
    assert service._runtime["last_error"] == "RuntimeError: database offline"


def test_budget_forwarding_and_no_full_front_sync(monkeypatch):
    from app.services import front_sync, pif_research_maintenance
    front = AsyncMock(return_value={})
    maintenance = AsyncMock(return_value={})
    monkeypatch.setattr(front_sync, "run_front_sync", front)
    monkeypatch.setattr(pif_research_maintenance, "queue_due_firm_maintenance", maintenance)
    monkeypatch.setenv("FRONT_SYNC_MAX_CALLS", "123")
    asyncio.run(service._run_stage("front"))
    asyncio.run(service._run_stage("research_maintenance"))
    front.assert_awaited_once_with(max_calls=123, full=False)
    maintenance.assert_awaited_once_with()  # Existing due windows and daily budget stay authoritative.


def test_front_status_uses_scheduled_slot_not_last_finished_plus_interval(monkeypatch, store):
    from app.services import front_sync
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalar_one.return_value = 0
    result.scalar_one_or_none.return_value = None
    session = AsyncMock()
    session.execute.return_value = result
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    monkeypatch.setattr(front_sync, "AsyncSessionLocal", factory)
    service._runtime.update(scheduler_active=True, next_run_at=SLOT)
    monkeypatch.setenv("FRONT_SYNC_INTERVAL_SECONDS", "5")
    response = asyncio.run(front_sync.front_status())
    assert response["sync_health"]["last_run_at"] is None
    assert response["sync_health"]["next_daily_run_at"] == SLOT.isoformat()
    assert response["sync_health"]["daily_schedule_timezone"] == "Asia/Kolkata"
    monkeypatch.setenv("FRONT_SYNC_ENABLED", "false")
    assert asyncio.run(front_sync.front_status())["sync_health"]["next_daily_run_at"] is None


def test_status_reads_durable_run_and_does_not_take_scheduler_lock(monkeypatch, store):
    store["saved"] = {"status": "running", "slot": SLOT.isoformat(), "errors": []}
    session = AsyncMock()
    session.scalar.return_value = False
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    monkeypatch.setattr(service, "AsyncSessionLocal", factory)
    status = asyncio.run(service.nightly_status())
    assert status["last_run"]["status"] == "interrupted"
    assert not status["running"]
    sql = str(session.scalar.call_args.args[0])
    assert "pg_locks" in sql
    assert "pg_try_advisory_lock" not in sql
    session.scalar.return_value = True
    assert asyncio.run(service.nightly_status())["running"]


def test_settings_update_only_our_namespace(monkeypatch):
    session = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    monkeypatch.setattr(service, "AsyncSessionLocal", factory)
    asyncio.run(service._save_state({"slot": SLOT.isoformat(), "status": "running"}))
    compiled = session.execute.call_args.args[0].compile()
    assert "ON CONFLICT (id) DO UPDATE SET agent_config = (system_settings.agent_config || excluded.agent_config)" in str(compiled)
    assert set(compiled.params["agent_config"]) == {service.STATE_KEY}
    session.commit.assert_awaited_once()


def test_cli_and_api_use_live_server_status(monkeypatch):
    from app import cli
    from app.api.pif import get_nightly_sync_status
    get = MagicMock(return_value={"next_run_at": SLOT.isoformat(), "enabled": True})
    monkeypatch.setattr(cli, "_get", get)
    monkeypatch.setenv("POSSIBLEOS_NIGHTLY_SYNC_ENABLED", "false")
    result = CliRunner().invoke(cli.app, ["pif", "nightly-status"])
    assert result.exit_code == 0
    assert '"enabled": true' in result.stdout
    get.assert_called_once_with("/api/pif/nightly-sync/status")
    live = AsyncMock(return_value={"running": True})
    monkeypatch.setattr(service, "nightly_status", live)
    assert asyncio.run(get_nightly_sync_status()) == {"running": True}
