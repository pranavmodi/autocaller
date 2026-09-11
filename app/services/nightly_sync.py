"""Fixed-slot daily producers; continuous research workers live separately."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from app.db import AsyncSessionLocal, async_engine
from app.db.models import SystemSettingsRow

logger = logging.getLogger(__name__)
ZONE = ZoneInfo("Asia/Kolkata")
STATE_KEY = "nightly_sync"
LOCK_ID = 73011930
STAGES = ("firm_sync", "autoresponses", "contact_ingestion", "front", "research_maintenance")
_runtime: dict[str, Any] = {"scheduler_active": False, "next_run_at": None, "last_error": None}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _enabled(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _positive_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def next_slot(now: datetime) -> datetime:
    """Strictly future 01:00 IST, including on process startup at the boundary."""
    local = now.astimezone(ZONE)
    slot = datetime.combine(local.date(), time(1), tzinfo=ZONE)
    if slot <= local:
        slot += timedelta(days=1)
    return slot.astimezone(timezone.utc)


def stage_flags() -> dict[str, bool]:
    from .pif_directory import pif_native_enabled
    from .pif_research_maintenance import maintenance_enabled

    native = pif_native_enabled()
    return dict(zip(STAGES, (native, native, native, _enabled("FRONT_SYNC_ENABLED"), maintenance_enabled())))


def schedule_status() -> dict[str, Any]:
    """In-process scheduler truth, also used by Front's next-run indicator."""
    enabled = _enabled("POSSIBLEOS_NIGHTLY_SYNC_ENABLED")
    slot = _runtime.get("next_run_at") if enabled and _runtime["scheduler_active"] else None
    return {
        **_runtime,
        "enabled": enabled,
        "timezone": ZONE.key,
        "local_time": "01:00",
        "next_run_at": slot.isoformat() if slot else None,
        "next_run_at_ist": slot.astimezone(ZONE).isoformat() if slot else None,
        "stages_enabled": stage_flags(),
        "stage_timeout_seconds": _positive_int("POSSIBLEOS_NIGHTLY_STAGE_TIMEOUT_SECONDS", 1800),
        "front_max_calls": _positive_int("FRONT_SYNC_MAX_CALLS", 300),
        "research_daily_limit_per_kind": _positive_int("PIF_RESEARCH_MAINTENANCE_DAILY_LIMIT", 175),
    }


async def _load_state() -> dict:
    async with AsyncSessionLocal() as session:
        config = await session.scalar(select(SystemSettingsRow.agent_config).where(SystemSettingsRow.id == 1))
        return dict((config or {}).get(STATE_KEY) or {})


async def _save_state(state: dict) -> None:
    # Update only our JSON key, not a stale copy of other agents' settings.
    stmt = insert(SystemSettingsRow).values(
        id=1, business_hours={}, queue_thresholds={}, agent_config={STATE_KEY: state},
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[SystemSettingsRow.id],
        set_={"agent_config": SystemSettingsRow.agent_config.op("||")(stmt.excluded.agent_config)},
    )
    async with AsyncSessionLocal() as session:
        await session.execute(stmt)
        await session.commit()


@asynccontextmanager
async def _run_lock():
    async with async_engine.connect() as connection:
        acquired = await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_ID})
        await connection.commit()
        try:
            yield bool(acquired)
        finally:
            if acquired:
                await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_ID})
                await connection.commit()


async def nightly_status() -> dict:
    result = schedule_status()
    state = await _load_state()
    # A stale running checkpoint after a crash is not evidence of live work.
    async with AsyncSessionLocal() as session:
        running = bool(await session.scalar(text(
            "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' "
            "AND classid = 0 AND objid = :key AND objsubid = 1 AND granted "
            "AND database = (SELECT oid FROM pg_database WHERE datname = current_database()))"
        ), {"key": LOCK_ID}))
    if state.get("status") == "running" and not running:
        state = {**state, "status": "interrupted"}
    return {**result, "running": running, "last_run": state}


async def _run_stage(name: str) -> dict:
    if name == "firm_sync":
        from .firm_intel_sync import sync_firm_intel
        return await sync_firm_intel()
    if name == "autoresponses":
        from .pif_autorespond_sync import sync_autorespond_events
        return await sync_autorespond_events()
    if name == "contact_ingestion":
        from .firm_contacts_service import ingest_pif_directory_contacts
        return await ingest_pif_directory_contacts()
    if name == "front":
        from .front_sync import run_front_sync
        return await run_front_sync(max_calls=_positive_int("FRONT_SYNC_MAX_CALLS", 300), full=False)
    if name == "research_maintenance":
        from .pif_research_maintenance import queue_due_firm_maintenance
        return await queue_due_firm_maintenance()
    raise ValueError(f"Unknown nightly stage: {name}")


def _summary(result: dict) -> dict:
    # Counts/status only: keep contact data and large firm lists out of settings.
    return {key: value for key, value in result.items()
            if value is None or isinstance(value, (str, int, float, bool))}


async def _front_failed(started_at: str, error: str) -> None:
    from .front_sync import _save_front_last_run
    await _save_front_last_run({
        "started_at": started_at, "finished_at": _now().isoformat(), "calls_used": None,
        "call_budget": _positive_int("FRONT_SYNC_MAX_CALLS", 300), "full": False, "error": error,
    })


async def run_slot(slot: datetime) -> dict:
    """Internal automatic entrypoint. Claim once before any external side effect."""
    if not _enabled("POSSIBLEOS_NIGHTLY_SYNC_ENABLED"):
        return {"status": "disabled"}
    async with _run_lock() as acquired:
        if not acquired:
            return {"status": "busy"}
        prior = await _load_state()
        if prior.get("slot") and datetime.fromisoformat(prior["slot"]) >= slot:
            return {"status": "already_claimed", "slot": prior["slot"]}
        state = {
            "slot": slot.isoformat(), "slot_ist": slot.astimezone(ZONE).isoformat(),
            "started_at": _now().isoformat(), "finished_at": None, "status": "running",
            "current_stage": None, "stages": {}, "errors": [],
        }
        await _save_state(state)
        flags = stage_flags()
        try:
            for name in STAGES:
                stage = {"status": "running" if flags[name] else "disabled", "started_at": _now().isoformat()}
                state["stages"][name] = stage
                state["current_stage"] = name
                await _save_state(state)
                if not flags[name]:
                    continue
                try:
                    result = await asyncio.wait_for(
                        _run_stage(name), timeout=_positive_int("POSSIBLEOS_NIGHTLY_STAGE_TIMEOUT_SECONDS", 1800),
                    )
                    stage.update(status="completed", result=_summary(result or {}))
                    failures = (result or {}).get("failures") or (result or {}).get("errors")
                    if failures or (result or {}).get("error") or (result or {}).get("status") in ("failed", "error"):
                        stage.update(status="partial", error=str(failures or result.get("error") or result["status"])[:2000])
                except asyncio.CancelledError:
                    stage["status"] = "interrupted"
                    raise
                except Exception as exc:
                    error = f"{type(exc).__name__}: {str(exc)[:1000]}"
                    stage.update(status="failed", error=error)
                    if name == "front":
                        try:
                            await _front_failed(stage["started_at"], error)
                        except Exception:
                            logger.exception("Unable to save Front failure summary")
                stage["finished_at"] = _now().isoformat()
                if stage.get("error"):
                    state["errors"].append({"stage": name, "error": stage["error"]})
                await _save_state(state)
            state["status"] = "partial" if state["errors"] else "completed"
        except asyncio.CancelledError:
            state["status"] = "interrupted"
            raise
        except Exception as exc:
            state["status"] = "failed"
            state["errors"].append({"stage": state["current_stage"], "error": f"{type(exc).__name__}: {str(exc)[:1000]}"})
            raise
        finally:
            state["finished_at"] = _now().isoformat()
            state["current_stage"] = None
            await _save_state(state)
        return state


async def nightly_sync_loop() -> None:
    # Restart never catches up a missed slot, even if the last run failed.
    _runtime.update(scheduler_active=True, started_at=_now().isoformat(), next_run_at=next_slot(_now()), last_error=None)
    try:
        while True:
            slot = _runtime["next_run_at"]
            delay = (slot - _now()).total_seconds()
            if delay > 0:
                await asyncio.sleep(min(delay, 60))
                continue
            # Advance before work, including failures and lock contention. A
            # suspended process also skips slots more than five minutes late.
            _runtime["next_run_at"] = next_slot(max(slot, _now()))
            if (_now() - slot).total_seconds() > 300:
                _runtime["last_error"] = f"Missed nightly slot {slot.isoformat()}; no catch-up"
                continue
            try:
                await run_slot(slot)
                _runtime["last_error"] = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _runtime["last_error"] = f"{type(exc).__name__}: {str(exc)[:1000]}"
                logger.exception("Nightly slot failed; next attempt is tomorrow")
    finally:
        _runtime.update(scheduler_active=False, next_run_at=None)
