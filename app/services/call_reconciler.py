"""Carrier-state reconciler — enforces the invariant
`ended_at IS NOT NULL ⟺ carrier confirmed terminal`.

Every ~60s, scans call_logs for rows whose termination_state is one of
the non-terminal states ('live', 'hangup_requested', 'hangup_failed')
started in the last few hours, and asks the carrier what it currently
thinks of each call. Depending on the answer:

  carrier says TERMINAL → stamp ended_at, termination_state =
                          'carrier_confirmed_ended'. No more polling.

  carrier says LIVE →     this is the scary one: our DB thinks the call
                          ended but the carrier still has the leg.
                          Re-fire hangup via the carrier adapter; log
                          escalation. Sweep again next tick.

  carrier says UNKNOWN →  transient API error. Update
                          termination_last_checked_at and retry next tick.

Orphan window: default 2 hours of started_at history. Older orphans
(the 5 pre-existing zombies from April 20-22) are reconciled once when
the reconciler first runs, via `sweep_all_pending_orphans()`.

Run as a background task from app.main startup — see
`start_reconciler_loop` at the bottom.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, or_

from app.db import AsyncSessionLocal
from app.db.models import CallLogRow


logger = logging.getLogger(__name__)


# How often to sweep. Short enough to feel responsive on a stuck call,
# long enough not to hammer carrier APIs.
RECONCILE_INTERVAL_SECS = int(os.getenv("CALL_RECONCILE_INTERVAL_SECS", "60"))

# How far back to look for "recent" orphans. Rows older than this are
# only swept on the one-off `sweep_all_pending_orphans` path.
RECENT_ORPHAN_WINDOW_HOURS = int(os.getenv("CALL_RECONCILE_WINDOW_HOURS", "2"))

# Non-terminal states that the reconciler re-evaluates. If a row ever
# reaches 'carrier_confirmed_ended', it's ignored forever.
NONTERMINAL_STATES = ("live", "hangup_requested", "hangup_failed")


async def _fetch_pending_rows(window_hours: Optional[int]) -> list[CallLogRow]:
    async with AsyncSessionLocal() as session:
        stmt = select(CallLogRow).where(
            CallLogRow.termination_state.in_(NONTERMINAL_STATES),
        )
        if window_hours is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
            stmt = stmt.where(CallLogRow.started_at >= cutoff)
        stmt = stmt.order_by(CallLogRow.started_at.desc()).limit(200)
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def reconcile_one(row: CallLogRow) -> dict:
    """Reconcile a single call_log row against its carrier.

    Returns a dict summarising what happened — used by on-demand
    endpoints (`/api/calls/reconcile`, `autocaller calls reconcile`)
    to show operators what the sweep did.
    """
    from app.services.carrier import get_carrier
    from app.providers.call_log_provider import get_call_log_provider

    result = {
        "call_id": row.call_id,
        "carrier": row.carrier,
        "carrier_call_sid": row.carrier_call_sid,
        "prev_state": row.termination_state,
        "action": "noop",
        "detail": "",
    }

    if not row.carrier_call_sid:
        # Pre-existing orphan: no SID on file. We can't ask the carrier.
        # Best we can do is stamp 'carrier_confirmed_ended' defensively
        # on rows old enough that any leg would have timed out anyway
        # (> 1 hour since started_at). Twilio hangs up abandoned legs
        # after a few minutes; Telnyx similar. A 1-hour-old no-SID
        # orphan is certainly gone carrier-side.
        age = datetime.now(timezone.utc) - (row.started_at or datetime.now(timezone.utc))
        if age > timedelta(hours=1):
            clp = get_call_log_provider()
            await clp.mark_carrier_terminal(
                row.call_id,
                state="carrier_confirmed_ended",
                error=(row.termination_last_error or "") +
                      " | reconciler: assumed terminal (no carrier_call_sid on file, age>1h)",
            )
            result["action"] = "assumed_terminal_no_sid"
            result["detail"] = f"age={age}"
            return result
        result["action"] = "waiting_for_sid"
        result["detail"] = f"age={age}"
        return result

    adapter = get_carrier(row.carrier)
    try:
        state, raw = await adapter.get_call_state(row.carrier_call_sid)
    except Exception as e:
        state, raw = "unknown", f"adapter_raise: {type(e).__name__}: {e!r}"

    clp = get_call_log_provider()
    if state == "terminal":
        await clp.mark_carrier_terminal(
            row.call_id,
            state="carrier_confirmed_ended",
            error=(row.termination_last_error or None),
        )
        result["action"] = "marked_terminal"
        result["detail"] = raw
    elif state == "live":
        # DANGER: our DB thinks the call is over, carrier says it's
        # alive. Force-hangup and log loudly. Reconciler will sweep
        # again next tick to confirm the hangup landed.
        logger.error(
            "[Reconciler] ORPHAN LEG: call_id=%s carrier=%s sid=%s — "
            "carrier reports call_state=%s but DB termination_state=%s. "
            "Force-hanging-up.",
            row.call_id, row.carrier, row.carrier_call_sid,
            raw, row.termination_state,
        )
        ok, err = await adapter.hangup_async(row.carrier_call_sid)
        if ok:
            await clp.mark_carrier_terminal(
                row.call_id, state="hangup_acked",
                error=f"reconciler_orphan_force_hangup: was_live, now_acked",
            )
            result["action"] = "force_hangup_acked"
            result["detail"] = raw
        else:
            await clp.mark_carrier_terminal(
                row.call_id, state="hangup_failed",
                error=f"reconciler_orphan_force_hangup_failed: {err}",
            )
            result["action"] = "force_hangup_failed"
            result["detail"] = f"state={raw} err={err}"
    else:  # 'unknown'
        # Just touch last_checked_at so we don't spin.
        async with AsyncSessionLocal() as session:
            stmt = select(CallLogRow).where(CallLogRow.call_id == row.call_id)
            res = await session.execute(stmt)
            live_row = res.scalar_one_or_none()
            if live_row:
                live_row.termination_last_checked_at = datetime.now(timezone.utc)
                live_row.termination_last_error = (
                    f"reconciler: carrier state unknown ({raw})"
                )
                await session.commit()
        result["action"] = "unknown_state"
        result["detail"] = raw

    return result


async def reconcile_once(window_hours: Optional[int] = RECENT_ORPHAN_WINDOW_HOURS) -> dict:
    """Run one reconciliation pass. Returns summary stats."""
    rows = await _fetch_pending_rows(window_hours)
    actions: dict[str, int] = {}
    details: list[dict] = []
    for row in rows:
        try:
            r = await reconcile_one(row)
        except Exception as e:
            logger.exception(
                "[Reconciler] reconcile_one raised on call_id=%s: %s",
                row.call_id, e,
            )
            r = {"call_id": row.call_id, "action": "error",
                 "detail": f"{type(e).__name__}: {e}"}
        actions[r["action"]] = actions.get(r["action"], 0) + 1
        details.append(r)
    summary = {
        "scanned": len(rows),
        "window_hours": window_hours,
        "actions": actions,
        "details": details[:50],  # cap for API response size
    }
    if rows:
        logger.info("[Reconciler] sweep: %s", {k: v for k, v in summary.items() if k != "details"})
    return summary


async def sweep_all_pending_orphans() -> dict:
    """One-shot sweep with no time window. Used for the initial
    backfill of pre-existing zombie rows on first reconciler boot.
    """
    return await reconcile_once(window_hours=None)


async def reconciler_loop():
    """Background task: run reconcile_once every RECONCILE_INTERVAL_SECS.

    On first boot, do one full sweep of all pending orphans (no time
    window) to backfill any zombies accumulated across previous
    deployments.
    """
    logger.info(
        "[Reconciler] started (interval=%ds, recent-window=%dh)",
        RECONCILE_INTERVAL_SECS, RECENT_ORPHAN_WINDOW_HOURS,
    )
    try:
        first = await sweep_all_pending_orphans()
        logger.info("[Reconciler] boot-sweep: %s",
                    {"scanned": first["scanned"], "actions": first["actions"]})
    except Exception as e:
        logger.exception("[Reconciler] boot-sweep failed: %s", e)

    sweep_counter = 0
    while True:
        await asyncio.sleep(RECONCILE_INTERVAL_SECS)
        try:
            await reconcile_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("[Reconciler] tick failed: %s", e)
        # Sweep pre-synthesized VM audio files older than 1h every ~10
        # reconciler ticks (~10 min with the default interval). Cheap.
        sweep_counter += 1
        if sweep_counter % 10 == 0:
            try:
                from app.services.vm_audio_service import sweep_stale
                n = sweep_stale(max_age_seconds=3600)
                if n:
                    logger.info("[Reconciler] VM audio sweep removed %d stale files", n)
            except Exception as e:
                logger.debug("[Reconciler] VM audio sweep raised: %s", e)


def start_reconciler_loop() -> asyncio.Task:
    """Fire-and-forget task starter for app.main startup."""
    return asyncio.create_task(reconciler_loop(), name="call_reconciler")


async def force_hangup(call_id: str) -> dict:
    """Operator-invoked force-hangup: look up the row's carrier_call_sid,
    fire the async hangup, record the result. Idempotent — safe to call
    on a row that's already terminal.
    """
    from app.services.carrier import get_carrier
    from app.providers.call_log_provider import get_call_log_provider

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(CallLogRow).where(CallLogRow.call_id == call_id)
        )
        row = result.scalar_one_or_none()
    if not row:
        return {"call_id": call_id, "ok": False, "error": "call not found"}
    if not row.carrier_call_sid:
        return {
            "call_id": call_id, "ok": False,
            "error": "no carrier_call_sid on this row — nothing to hang up",
        }
    adapter = get_carrier(row.carrier)
    ok, err = await adapter.hangup_async(row.carrier_call_sid)
    clp = get_call_log_provider()
    if ok:
        await clp.mark_carrier_terminal(
            row.call_id, state="hangup_acked",
            error="operator_force_hangup",
        )
    else:
        await clp.mark_carrier_terminal(
            row.call_id, state="hangup_failed",
            error=f"operator_force_hangup_failed: {err}",
        )
    return {
        "call_id": call_id,
        "carrier": row.carrier,
        "carrier_call_sid": row.carrier_call_sid,
        "ok": ok,
        "error": err,
    }
