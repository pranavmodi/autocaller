import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.lead_gen import router as lead_gen_router
from app.services import lead_gen_daily


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _Session:
    def __init__(self, rows):
        self.rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, _stmt):
        return _Result(self.rows)


def _settings_provider(enabled=True):
    async def get_settings():
        return SimpleNamespace(system_enabled=enabled)

    return SimpleNamespace(get_settings=get_settings)


class _QueuedSession:
    def __init__(self, result_sets):
        self.result_sets = list(result_sets)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, _stmt):
        return _Result(self.result_sets.pop(0))


@pytest.mark.asyncio
async def test_gates_skip_when_system_disabled(monkeypatch):
    monkeypatch.setattr(lead_gen_daily, "get_settings_provider", lambda: _settings_provider(False))

    result = await lead_gen_daily._run_gates(
        {"daily_send_budget": 20},
        now=datetime(2026, 6, 12, 14, 0, tzinfo=timezone.utc),
    )

    assert result["passed"] is False
    assert result["reason"] == "system_disabled"


def test_daily_channel_plan_assigns_provider_caps_by_scheduled_order(monkeypatch):
    run_date = datetime(2026, 6, 24, tzinfo=timezone.utc).date()
    scheduled_start = datetime(2026, 6, 24, 16, 0, tzinfo=timezone.utc)
    actions = [
        SimpleNamespace(
            id=f"action_{idx:02d}",
            input_json={"mode": "lead_gen", "batch_item_id": f"item_{idx:02d}"},
            entity_id=f"item_{idx:02d}",
            scheduled_for=scheduled_start + timedelta(minutes=idx),
            execution_result_json={},
            completed_at=None,
            status="approved",
            started_at=None,
        )
        for idx in range(40)
    ]

    async def fake_active_policy():
        return SimpleNamespace(weights_json={
            "daily_send_budget": 40,
            "provider_daily_caps": {"zoho_api": 20, "resend": 20},
        })

    async def fake_sent_counts_by_transport_for_day(*, run_date=None):
        return {"zoho_api": 0, "resend": 0}

    monkeypatch.setattr(lead_gen_daily, "_active_policy", fake_active_policy)
    monkeypatch.setattr(
        lead_gen_daily,
        "sent_counts_by_transport_for_day",
        fake_sent_counts_by_transport_for_day,
    )
    monkeypatch.setattr(
        lead_gen_daily,
        "AsyncSessionLocal",
        lambda: _QueuedSession([actions, []]),
    )

    plan = asyncio.run(lead_gen_daily.daily_channel_plan(run_date=run_date))

    assert [plan[f"item_{idx:02d}"]["channel"] for idx in range(20)] == ["zoho_api"] * 20
    assert [plan[f"item_{idx:02d}"]["channel"] for idx in range(20, 40)] == ["resend"] * 20
    assert plan["item_00"]["scheduled_for"] == scheduled_start.isoformat()


@pytest.mark.asyncio
async def test_gates_skip_when_budget_zero(monkeypatch):
    monkeypatch.setattr(lead_gen_daily, "get_settings_provider", lambda: _settings_provider(True))

    result = await lead_gen_daily._run_gates(
        {"daily_send_budget": 0},
        now=datetime(2026, 6, 12, 14, 0, tzinfo=timezone.utc),
    )

    assert result["passed"] is False
    assert result["reason"] == "daily_send_budget_zero"


@pytest.mark.asyncio
async def test_gates_skip_weekend(monkeypatch):
    monkeypatch.setattr(lead_gen_daily, "get_settings_provider", lambda: _settings_provider(True))

    result = await lead_gen_daily._run_gates(
        {"daily_send_budget": 20},
        now=datetime(2026, 6, 13, 14, 0, tzinfo=timezone.utc),
    )

    assert result["passed"] is False
    assert result["reason"] == "weekday_disabled"


@pytest.mark.asyncio
async def test_force_bypasses_weekend_gate(monkeypatch):
    monkeypatch.setattr(lead_gen_daily, "get_settings_provider", lambda: _settings_provider(True))

    async def _no_circuit(*_args, **_kwargs):
        return {"tripped": False}

    monkeypatch.setattr(lead_gen_daily, "_deliverability_circuit", _no_circuit)

    result = await lead_gen_daily._run_gates(
        {"daily_send_budget": 20},
        now=datetime(2026, 6, 13, 14, 0, tzinfo=timezone.utc),
        force=True,
    )

    assert result["passed"] is True
    assert result["forced"] is True
    assert "weekday_disabled" in result["force_bypassed"]


@pytest.mark.asyncio
async def test_force_does_not_bypass_hard_gates(monkeypatch):
    # System kill-switch and zero budget are not waivable by force.
    monkeypatch.setattr(lead_gen_daily, "get_settings_provider", lambda: _settings_provider(False))
    disabled = await lead_gen_daily._run_gates({"daily_send_budget": 20}, force=True)
    assert disabled["passed"] is False
    assert disabled["reason"] == "system_disabled"

    monkeypatch.setattr(lead_gen_daily, "get_settings_provider", lambda: _settings_provider(True))
    no_budget = await lead_gen_daily._run_gates({"daily_send_budget": 0}, force=True)
    assert no_budget["passed"] is False
    assert no_budget["reason"] == "daily_send_budget_zero"


@pytest.mark.asyncio
async def test_deliverability_circuit_breaker_math(monkeypatch):
    now = datetime(2026, 6, 12, 14, 0, tzinfo=timezone.utc)
    rows = [
        ("email_sent", "neutral"),
        ("email_sent", "neutral"),
        ("email_sent", "neutral"),
        ("email_sent", "neutral"),
        ("email_send_failed", "bounce"),
        ("manual", "bounce"),
    ]
    monkeypatch.setattr(lead_gen_daily, "AsyncSessionLocal", lambda: _Session(rows))

    result = await lead_gen_daily._deliverability_circuit(
        {"deliverability_circuit_breaker_threshold": 0.25, "deliverability_circuit_breaker_min_sends": 4},
        now=now,
    )

    assert result["sends"] == 4
    assert result["failures"] == 2
    assert result["tripped"] is True


@pytest.mark.asyncio
async def test_deliverability_circuit_ignores_operational_send_failures(monkeypatch):
    # Regression for the false skip on 2026-06-16: operational `email_send_failed`
    # events the classifier marks neutral (policy refusals, transport timeouts)
    # never reach a recipient mailbox and must NOT trip the bounce breaker.
    now = datetime(2026, 6, 16, 2, 33, tzinfo=timezone.utc)
    rows = [("email_sent", "neutral")] * 19 + [("email_send_failed", "neutral")] * 5
    monkeypatch.setattr(lead_gen_daily, "AsyncSessionLocal", lambda: _Session(rows))

    result = await lead_gen_daily._deliverability_circuit(
        {"deliverability_circuit_breaker_threshold": 0.25, "deliverability_circuit_breaker_min_sends": 4},
        now=now,
    )

    assert result["sends"] == 19
    assert result["failures"] == 0
    assert result["tripped"] is False


def test_persona_quota_shortfall_fill_and_one_per_firm():
    recs = [
        {"contact_id": "a1", "pif_id": "p1", "firm_name": "A", "persona": "founder_owner", "score": 100},
        {"contact_id": "a2", "pif_id": "p1", "firm_name": "A", "persona": "coo_ops", "score": 99},
        {"contact_id": "b1", "pif_id": "p2", "firm_name": "B", "persona": "coo_ops", "score": 90},
        {"contact_id": "c1", "pif_id": "p3", "firm_name": "C", "persona": "intake", "score": 80},
    ]

    selected = lead_gen_daily._select_by_persona_quota(
        recs,
        quota={"founder_owner": 1},
        batch_size=3,
    )

    assert [row["contact_id"] for row in selected] == ["a1", "b1", "c1"]
    assert len({row["pif_id"] for row in selected}) == 3


@pytest.mark.asyncio
async def test_select_contacts_excludes_already_batched_contacts(monkeypatch):
    async def fake_recommend(**_kwargs):
        return {
            "recommended": [
                {
                    "contact_id": "already",
                    "pif_id": "p1",
                    "firm_name": "Already LLP",
                    "contact_email": "a@example.com",
                    "persona": "founder_owner",
                    "score": 100,
                },
                {
                    "contact_id": "fresh",
                    "pif_id": "p2",
                    "firm_name": "Fresh LLP",
                    "contact_email": "f@example.com",
                    "persona": "founder_owner",
                    "score": 90,
                },
            ],
            "counts": {"eligible": 2},
        }

    async def fake_suppressed(_pif_ids):
        return set(), {}

    monkeypatch.setattr(lead_gen_daily, "recommend_sequence_contacts", fake_recommend)
    monkeypatch.setattr(lead_gen_daily, "_suppressed_pifs_and_behavior", fake_suppressed)
    monkeypatch.setenv("LEAD_GEN_EVIDENCE_AWARE_SELECTION", "0")

    result = await lead_gen_daily._select_contacts(
        weights={},
        batch_size=1,
        template_key="possible_minds_dynamic",
        exclude_contact_ids={"already"},
    )

    assert [row["contact_id"] for row in result["selected"]] == ["fresh"]
    assert result["excluded"]["already_batched_today"] == 1


@pytest.mark.asyncio
async def test_daily_selection_prioritizes_due_followups_then_fresh(monkeypatch):
    followups = [
        {"contact_id": "fu-1", "pif_id": "p1", "firm_name": "A", "persona": "owner"},
        {"contact_id": "fu-2", "pif_id": "p2", "firm_name": "B", "persona": "ops"},
    ]
    fresh = [
        {"contact_id": "fresh-1", "pif_id": "p3", "firm_name": "C", "persona": "intake"},
    ]

    async def fake_followups(**kwargs):
        assert kwargs["batch_size"] == 3
        return {"selected": followups, "followups_due_total": 5}

    async def fake_fresh(**kwargs):
        assert kwargs["batch_size"] == 1
        return {
            "selected": fresh,
            "recommendation_counts": {"eligible": 10},
            "quota": {"owner": 3},
            "batch_size": 1,
            "persona_mix": {"intake": 1},
            "excluded": {},
            "behavior_by_pif": {},
        }

    monkeypatch.setattr(lead_gen_daily, "sequences_enabled", lambda: True)
    monkeypatch.setattr(lead_gen_daily, "_select_due_followups", fake_followups)
    monkeypatch.setattr(lead_gen_daily, "_select_contacts", fake_fresh)

    result = await lead_gen_daily._select_daily_contacts(
        weights={},
        batch_size=3,
        template_key="possible_minds_dynamic",
    )

    assert [row["contact_id"] for row in result["selected"]] == ["fu-1", "fu-2", "fresh-1"]
    assert result["followups_selected"] == 2
    assert result["fresh_selected"] == 1
    assert result["followups_due_total"] == 5


@pytest.mark.asyncio
async def test_daily_selection_uses_zero_fresh_when_followups_fill_quota(monkeypatch):
    followups = [
        {"contact_id": "fu-1", "pif_id": "p1", "firm_name": "A", "persona": "owner"},
        {"contact_id": "fu-2", "pif_id": "p2", "firm_name": "B", "persona": "ops"},
    ]

    async def fake_followups(**_kwargs):
        return {"selected": followups, "followups_due_total": 4}

    async def fail_fresh(**_kwargs):
        raise AssertionError("fresh selector should not run when follow-ups fill quota")

    monkeypatch.setattr(lead_gen_daily, "sequences_enabled", lambda: True)
    monkeypatch.setattr(lead_gen_daily, "_select_due_followups", fake_followups)
    monkeypatch.setattr(lead_gen_daily, "_select_contacts", fail_fresh)

    result = await lead_gen_daily._select_daily_contacts(
        weights={},
        batch_size=2,
        template_key="possible_minds_dynamic",
    )

    assert [row["contact_id"] for row in result["selected"]] == ["fu-1", "fu-2"]
    assert result["followups_selected"] == 2
    assert result["fresh_selected"] == 0


@pytest.mark.asyncio
async def test_daily_selection_flag_off_uses_original_fresh_selector(monkeypatch):
    fresh_result = {
        "selected": [{"contact_id": "fresh-1"}],
        "recommendation_counts": {},
        "quota": {},
        "batch_size": 3,
        "persona_mix": {},
        "excluded": {},
        "behavior_by_pif": {},
    }

    async def fail_followups(**_kwargs):
        raise AssertionError("follow-up selector should not run when sequences are disabled")

    async def fake_fresh(**kwargs):
        assert kwargs["batch_size"] == 3
        return fresh_result

    monkeypatch.setattr(lead_gen_daily, "sequences_enabled", lambda: False)
    monkeypatch.setattr(lead_gen_daily, "_select_due_followups", fail_followups)
    monkeypatch.setattr(lead_gen_daily, "_select_contacts", fake_fresh)

    result = await lead_gen_daily._select_daily_contacts(
        weights={},
        batch_size=3,
        template_key="possible_minds_dynamic",
    )

    assert result == fresh_result


def test_schedule_spread_same_day_and_next_weekday():
    same_day = lead_gen_daily.spread_schedule_times(
        item_ids=["a", "b", "c"],
        now=datetime(2026, 6, 12, 14, 0, tzinfo=timezone.utc),
    )

    assert len(same_day) == 3
    assert all(t.tzinfo == timezone.utc for t in same_day)
    assert [t.astimezone(lead_gen_daily.PT).date().isoformat() for t in same_day] == [
        "2026-06-12",
        "2026-06-12",
        "2026-06-12",
    ]
    assert all(9 <= t.astimezone(lead_gen_daily.PT).hour <= 11 for t in same_day)

    next_day = lead_gen_daily.spread_schedule_times(
        item_ids=["a"],
        now=datetime(2026, 6, 12, 20, 0, tzinfo=timezone.utc),
    )[0]

    assert next_day.astimezone(lead_gen_daily.PT).date().isoformat() == "2026-06-15"


def test_notify_payload_shape():
    message = lead_gen_daily.build_notify_message(
        batch_id="batch-1",
        item_count=20,
        draft_count=18,
        persona_mix={"founder_owner": 5},
        subjects=["One", "Two", "Three", "Four"],
    )

    assert message.startswith("[from cc]")
    assert "batch=batch-1" in message
    assert "items=20 drafts=18" in message
    assert "review at /lead-gen" in message
    assert "Four" not in message


@pytest.mark.asyncio
async def test_compose_partial_on_repeated_chunk_failure(monkeypatch):
    batch = {
        "items": [
            {"id": "item-1", "approval_status": "pending", "reason": {}},
            {"id": "item-2", "approval_status": "pending", "reason": {}},
        ]
    }

    async def fake_get_batch(*_args, **_kwargs):
        return batch

    async def fail_compose(**_kwargs):
        raise RuntimeError("composer_down")

    monkeypatch.setattr(lead_gen_daily, "get_batch", fake_get_batch)
    monkeypatch.setattr(lead_gen_daily, "_compose_batch_items", fail_compose)

    result = await lead_gen_daily._compose_batch(
        batch_id="batch-1",
        created_by="test",
        template_key="possible_minds_dynamic",
    )

    assert result["complete"] is False
    assert result["drafted"] == 0
    assert len(result["errors"]) == 2


def test_daily_api_smoke(monkeypatch):
    app = FastAPI()
    app.include_router(lead_gen_router)

    async def fake_run(**kwargs):
        return {
            "id": "run-1",
            "run_date": "2026-06-12",
            "status": "completed",
            "stage": "done",
            "stages": {"gates": {"status": "completed", "counts": kwargs}},
            "batch_id": "batch-1",
        }

    async def fake_list(limit=20):
        return [{"id": "run-1", "run_date": "2026-06-12", "status": "completed", "stage": "done", "stages": {}, "batch_id": "batch-1"}]

    async def fake_enabled():
        return {"enabled": False, "key": "daily_run_enabled"}

    async def fake_set(enabled):
        return {"enabled": enabled, "key": "daily_run_enabled"}

    monkeypatch.setattr("app.api.lead_gen.run_daily_pipeline", fake_run)
    monkeypatch.setattr("app.api.lead_gen.list_daily_runs", fake_list)
    monkeypatch.setattr("app.api.lead_gen.get_daily_run_enabled", fake_enabled)
    monkeypatch.setattr("app.api.lead_gen.set_daily_run_enabled", fake_set)

    client = TestClient(app)
    assert client.post("/api/lead-gen/daily-run", json={"dry_run": True}).json()["batch_id"] == "batch-1"
    assert client.get("/api/lead-gen/daily-runs?limit=1").json()["runs"][0]["id"] == "run-1"
    assert client.get("/api/lead-gen/daily-run/enabled").json()["enabled"] is False
    assert client.put("/api/lead-gen/daily-run/enabled", json={"enabled": True}).json()["enabled"] is True


@pytest.mark.asyncio
async def test_top_up_daily_run_returns_counts_and_uses_exclude_set(monkeypatch):
    async def fake_active_policy():
        return SimpleNamespace(version="v1", weights_json={"daily_template_key": "possible_minds_dynamic"})

    async def fake_exclude(run_date):
        assert run_date.isoformat() == "2026-06-24"
        return {"already"}

    async def fake_existing_run(run_date):
        assert run_date.isoformat() == "2026-06-24"
        return "run-1"

    async def fake_select(**kwargs):
        assert kwargs["batch_size"] == 2
        assert kwargs["exclude_contact_ids"] == {"already"}
        return {
            "selected": [
                {
                    "contact_id": "fresh",
                    "pif_id": "p2",
                    "firm_name": "Fresh LLP",
                    "contact_email": "fresh@example.com",
                    "persona": "founder_owner",
                    "score": 90,
                }
            ],
            "recommendation_counts": {"eligible": 10},
            "quota": {},
            "batch_size": 2,
            "persona_mix": {"founder_owner": 1},
            "excluded": {"already_batched_today": 1},
            "behavior_by_pif": {},
        }

    async def fake_daily_run_batch_id(run_date):
        assert run_date.isoformat() == "2026-06-24"
        return "today-batch"

    async def fake_create(**kwargs):
        assert kwargs["run_id"] == "run-1"
        # Top-up now APPENDS to today's daily-run batch (no sidecar).
        assert kwargs["batch_name"] == "Daily run 2026-06-24"
        assert kwargs["basis"] == "daily-run-top-up"
        assert kwargs["append_to_batch_id"] == "today-batch"
        assert kwargs["extra_counts"]["excluded_today_contacts"] == 1
        return "today-batch"

    async def fake_compose(**kwargs):
        assert kwargs["batch_id"] == "today-batch"
        assert kwargs["composer_variant_key"] == "ai-audit"
        return {"drafted": 1, "held": 0, "complete": True}

    async def fake_schedule(**kwargs):
        assert kwargs["batch_id"] == "today-batch"
        return {"scheduled": 1, "auto_approved": 1}

    monkeypatch.setattr(lead_gen_daily, "_active_policy", fake_active_policy)
    monkeypatch.setattr(lead_gen_daily, "_daily_run_batch_contact_ids", fake_exclude)
    monkeypatch.setattr(lead_gen_daily, "_existing_daily_run_id", fake_existing_run)
    monkeypatch.setattr(lead_gen_daily, "_daily_run_batch_id", fake_daily_run_batch_id)
    monkeypatch.setattr(lead_gen_daily, "_select_contacts", fake_select)
    monkeypatch.setattr(lead_gen_daily, "_create_daily_batch", fake_create)
    monkeypatch.setattr(lead_gen_daily, "_compose_batch", fake_compose)
    monkeypatch.setattr(lead_gen_daily, "_schedule_drafted_items", fake_schedule)

    result = await lead_gen_daily.top_up_daily_run(
        n=2,
        composer_variant_key="ai-audit",
        run_date=datetime(2026, 6, 24, tzinfo=timezone.utc).date(),
    )

    assert result == {
        "run_date": "2026-06-24",
        "batch_id": "today-batch",
        "requested": 2,
        "selected": 1,
        "composed": 1,
        "held": 0,
        "scheduled": 1,
        "approved": 1,
        "composer_variant_override": "ai-audit",
        "excluded_today_contacts": 1,
        "compose_complete": True,
    }


def test_top_up_api_smoke(monkeypatch):
    app = FastAPI()
    app.include_router(lead_gen_router)

    async def fake_top_up(**kwargs):
        assert kwargs["n"] == 3
        return {
            "run_date": "2026-06-24",
            "batch_id": "batch-top-up",
            "requested": 3,
            "selected": 3,
            "composed": 3,
            "held": 0,
            "scheduled": 3,
            "approved": 3,
        }

    monkeypatch.setattr("app.api.lead_gen.top_up_daily_run", fake_top_up)

    client = TestClient(app)
    data = client.post("/api/lead-gen/daily-run/top-up", json={"n": 3}).json()
    assert data["batch_id"] == "batch-top-up"
    assert data["scheduled"] == 3


def test_daily_loop_window_fires_at_8am_ist_weekdays_only():
    from datetime import datetime, timezone
    from app.services.lead_gen_daily import _in_daily_loop_window, _date_for_run
    mon_in = datetime(2026, 6, 15, 2, 40, tzinfo=timezone.utc)   # 08:10 IST Mon
    assert _in_daily_loop_window(mon_in) is True
    assert _date_for_run(mon_in).isoformat() == "2026-06-15"
    assert _in_daily_loop_window(datetime(2026, 6, 15, 2, 20, tzinfo=timezone.utc)) is False  # 07:50 IST
    assert _in_daily_loop_window(datetime(2026, 6, 15, 3, 30, tzinfo=timezone.utc)) is False  # 09:00 IST
    assert _in_daily_loop_window(datetime(2026, 6, 13, 2, 40, tzinfo=timezone.utc)) is False  # Sat 08:10 IST
    assert _in_daily_loop_window(datetime(2026, 6, 14, 2, 40, tzinfo=timezone.utc)) is False  # Sun 08:10 IST
