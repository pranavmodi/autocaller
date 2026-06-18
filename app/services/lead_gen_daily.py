"""Deterministic daily lead-selection and draft scheduling pipeline."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import desc, func, select

from app.db import AsyncSessionLocal
from app.db.models import (
    AgentActionRow,
    EmailSequenceRow,
    FrontFirmActivityRow,
    FirmContactRow,
    FirmReviewRow,
    LeadGenBatchItemRow,
    LeadGenBatchRow,
    LeadGenDailyRunRow,
    LeadGenObservationRow,
    LeadGenPolicyVersionRow,
    SystemSettingsRow,
)
from app.providers.settings_provider import get_settings_provider
from app.services.action_execution import (
    SEND_EMAIL,
    _record_action_event,
    create_send_email_action,
    find_live_scheduled_action_for_item,
)
from app.services.firm_research import orchestrate_warm_research
from app.services.front_sync import front_status, normalize_domain, refresh_warm_scores, resolve_firms
from app.services.lead_gen_cybernetic import TARGET_METRIC, ensure_default_policy, get_batch
from app.services.lead_gen_email_agent import _compose_batch_items
from app.services.persona_mapper import map_personas
from app.services.sequence_recommendations import recommend_sequence_contacts
from app.services.sequences.registry import DEFAULT_TEMPLATE_KEY
from app.services.sequence_scheduler import sequences_enabled
from app.services.firm_contacts_service import resolve_firm_name
from app.services.review_extraction import firms_with_usable_evidence, split_raw_reviews
from app.services.scheduled_time import format_pt, format_utc


logger = logging.getLogger(__name__)

PT = ZoneInfo("America/Los_Angeles")
# The pipeline RUN trigger (loop window, run-date, weekday gate) is on the
# operator's timezone (IST by default) so "runs at 8 AM IST on weekdays" is
# expressed natively. The SEND window (when emails actually go to US firms)
# stays on PT — see _send_window / DEFAULT_SEND_WINDOW.
RUN_TZ = ZoneInfo(os.getenv("DAILY_RUN_TZ", "Asia/Kolkata"))
RUN_WINDOW_START = time(8, 0)
RUN_WINDOW_END = time(8, 30)
DAILY_RUN_CONFIG_KEY = "daily_run_enabled"
DAILY_RUN_STAGES = (
    "gates",
    "signals",
    "research",
    "personas",
    "select",
    "batch",
    "compose",
    "schedule",
    "notify",
)
DEFAULT_PERSONA_QUOTA = {
    "founder_owner": 5,
    "managing_partner": 4,
    "coo_ops": 3,
    "intake": 3,
    "records": 2,
    "case_manager": 1,
    "lien_settlement": 1,
    "attorney": 1,
}
DEFAULT_SEND_WINDOW = {
    "start": "09:00",
    "end": "11:30",
    "timezone": "America/Los_Angeles",
}
HARD_EXCLUDED_DOMAINS = {"precisemri.com"}


def auto_approve_send_enabled() -> bool:
    return os.getenv("LEAD_GEN_AUTO_APPROVE_SEND", "false").strip().lower() in {"1", "true", "yes", "on"}


def _pt_day_bounds(target: date) -> tuple[datetime, datetime]:
    start = datetime.combine(target, time.min, tzinfo=PT)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, default=str)
        return value
    except TypeError:
        return json.loads(json.dumps(value, default=str))


def _date_for_run(now: datetime | None = None) -> date:
    # Run-date idempotency key is the operator-timezone (IST) calendar day,
    # matching the 8 AM IST trigger, so one run per IST weekday.
    return (now or _utcnow()).astimezone(RUN_TZ).date()


def _run_to_dict(row: LeadGenDailyRunRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_date": row.run_date.isoformat() if row.run_date else None,
        "status": row.status,
        "stage": row.stage,
        "stages": row.stages_json or {},
        "batch_id": row.batch_id,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _stage_done(stages: dict[str, Any], stage: str) -> bool:
    return (stages.get(stage) or {}).get("status") in {"completed", "skipped"}


async def _checkpoint(
    run_id: str,
    *,
    stage: str,
    status: str,
    counts: dict[str, Any] | None = None,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
    run_status: str | None = None,
    batch_id: str | None = None,
) -> LeadGenDailyRunRow:
    now = _utcnow()
    async with AsyncSessionLocal() as session:
        row = await session.get(LeadGenDailyRunRow, run_id)
        if not row:
            raise ValueError("daily_run_not_found")
        stages = dict(row.stages_json or {})
        entry = dict(stages.get(stage) or {})
        entry.setdefault("started_at", now.isoformat())
        if status in {"completed", "skipped", "failed", "partial"}:
            entry["finished_at"] = now.isoformat()
        entry["status"] = status
        if counts is not None:
            entry["counts"] = _json_safe(counts)
        if error:
            entry["error"] = error
        if extra:
            entry.update(_json_safe(extra))
        stages[stage] = entry
        row.stages_json = stages
        row.stage = stage
        if run_status:
            row.status = run_status
        if batch_id:
            row.batch_id = batch_id
        row.updated_at = now
        await session.commit()
        await session.refresh(row)
        return row


async def _create_or_get_run(
    *,
    run_date: date,
    created_by: str,
    force: bool,
) -> tuple[LeadGenDailyRunRow, bool]:
    async with AsyncSessionLocal() as session:
        existing = (await session.execute(
            select(LeadGenDailyRunRow).where(LeadGenDailyRunRow.run_date == run_date)
        )).scalar_one_or_none()
        if existing and not force:
            return existing, False
        if existing and force:
            existing.status = "running"
            existing.stage = "pending"
            existing.stages_json = {}
            existing.batch_id = None
            existing.created_by = created_by
            existing.updated_at = _utcnow()
            await session.commit()
            await session.refresh(existing)
            return existing, True
        row = LeadGenDailyRunRow(
            id=_new_id(),
            run_date=run_date,
            status="running",
            stage="pending",
            stages_json={},
            created_by=created_by,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row, True


async def _active_policy() -> LeadGenPolicyVersionRow | None:
    async with AsyncSessionLocal() as session:
        return (await session.execute(
            select(LeadGenPolicyVersionRow)
            .where(LeadGenPolicyVersionRow.active.is_(True))
            .order_by(desc(LeadGenPolicyVersionRow.created_at))
            .limit(1)
        )).scalar_one_or_none()


def _policy_weights(policy: LeadGenPolicyVersionRow | None) -> dict[str, Any]:
    return dict(getattr(policy, "weights_json", None) or {})


def _int_policy(weights: dict[str, Any], key: str, default: int, *, minimum: int = 0, maximum: int = 500) -> int:
    try:
        value = int(weights.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _float_policy(weights: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(weights.get(key, default))
    except (TypeError, ValueError):
        return default


def _persona_quota(weights: dict[str, Any]) -> dict[str, int]:
    raw = weights.get("daily_persona_quota")
    if not isinstance(raw, dict):
        return dict(DEFAULT_PERSONA_QUOTA)
    quota: dict[str, int] = {}
    for key, default in DEFAULT_PERSONA_QUOTA.items():
        try:
            quota[key] = max(0, int(raw.get(key, default)))
        except (TypeError, ValueError):
            quota[key] = default
    for key, value in raw.items():
        if key in quota:
            continue
        try:
            quota[str(key)] = max(0, int(value))
        except (TypeError, ValueError):
            continue
    return quota


def _send_window(weights: dict[str, Any]) -> dict[str, str]:
    raw = weights.get("daily_send_window")
    if not isinstance(raw, dict):
        return dict(DEFAULT_SEND_WINDOW)
    return {
        "start": str(raw.get("start") or DEFAULT_SEND_WINDOW["start"]),
        "end": str(raw.get("end") or DEFAULT_SEND_WINDOW["end"]),
        "timezone": str(raw.get("timezone") or DEFAULT_SEND_WINDOW["timezone"]),
    }


def _weekdays(weights: dict[str, Any]) -> set[int]:
    raw = weights.get("daily_run_weekdays", [0, 1, 2, 3, 4])
    if not isinstance(raw, list):
        return {0, 1, 2, 3, 4}
    out = set()
    for value in raw:
        try:
            out.add(int(value))
        except (TypeError, ValueError):
            continue
    return out or {0, 1, 2, 3, 4}


async def _deliverability_circuit(weights: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    threshold = _float_policy(weights, "deliverability_circuit_breaker_threshold", 0.25)
    min_sends = _int_policy(weights, "deliverability_circuit_breaker_min_sends", 4, minimum=1, maximum=1000)
    cutoff = (now or _utcnow()) - timedelta(hours=48)
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(LeadGenObservationRow.event_type, LeadGenObservationRow.classified_outcome)
            .where(LeadGenObservationRow.created_at >= cutoff)
        )).all()
    sends = sum(1 for event_type, _outcome in rows if event_type == "email_sent")
    # Deliverability == recipient-side bounces, which is what risks sender
    # reputation and is the thing this breaker exists to protect. Operational
    # `email_send_failed` events (the classifier marks these neutral — e.g. a
    # pre-transport policy refusal, or a transient SSL/transport timeout) never
    # reached a recipient mailbox and carry no reputation signal, so they must
    # NOT trip this breaker. Count only true bounces.
    failures = sum(1 for _event_type, outcome in rows if outcome == "bounce")
    ratio = (failures / sends) if sends else 0.0
    tripped = sends >= min_sends and ratio > threshold
    return {
        "tripped": tripped,
        "sends": sends,
        "failures": failures,
        "ratio": round(ratio, 4),
        "threshold": threshold,
        "min_sends": min_sends,
    }


async def _run_gates(
    weights: dict[str, Any], *, now: datetime | None = None, force: bool = False
) -> dict[str, Any]:
    # Hard gates always apply, even under force: the system kill-switch and a
    # zero budget are not "discipline" the operator can wave through.
    settings = await get_settings_provider().get_settings()
    if not settings.system_enabled:
        return {"passed": False, "reason": "system_disabled", "system_enabled": False}
    daily_send_budget = _int_policy(weights, "daily_send_budget", 50, minimum=0, maximum=200)
    if daily_send_budget <= 0:
        return {"passed": False, "reason": "daily_send_budget_zero", "daily_send_budget": daily_send_budget}
    # Weekday gate uses the run timezone (IST) so "except weekends" means IST
    # weekends, consistent with the 8 AM IST trigger. (8 AM IST Monday is
    # Sunday evening in PT — a PT weekday check would wrongly skip it.)
    local_now = (now or _utcnow()).astimezone(RUN_TZ)
    weekdays = _weekdays(weights)
    bypassed: list[str] = []
    # Discipline gates: a forced run (operator-confirmed) bypasses these. The
    # pipeline only produces approval-waiting drafts, so nothing sends anyway.
    if local_now.weekday() not in weekdays:
        if not force:
            return {
                "passed": False,
                "reason": "weekday_disabled",
                "weekday": local_now.weekday(),
                "allowed_weekdays": sorted(weekdays),
            }
        bypassed.append("weekday_disabled")
    circuit = await _deliverability_circuit(weights, now=now)
    if circuit["tripped"]:
        if not force:
            return {"passed": False, "reason": "deliverability_circuit_breaker", "deliverability": circuit}
        bypassed.append("deliverability_circuit_breaker")
    return {
        "passed": True,
        "forced": bool(force),
        "force_bypassed": bypassed,
        "system_enabled": True,
        "daily_send_budget": daily_send_budget,
        "weekday": local_now.weekday(),
        "deliverability": circuit,
    }


def _select_by_persona_quota(
    recommendations: Iterable[dict[str, Any]],
    *,
    quota: dict[str, int],
    batch_size: int,
    evidence_pifs: set[str] | None = None,
    no_evidence_reserve: int = 0,
) -> list[dict[str, Any]]:
    """Pick up to batch_size, persona-quota first then relaxed, ranked by score.

    Evidence-aware mode (evidence_pifs given): prefer firms that already have
    usable review evidence so the daily slots fill with composable (not held)
    firms, while reserving up to `no_evidence_reserve` slots for the
    highest-scoring no-evidence firms — that keeps surfacing firms to paste
    reviews for (the discovery loop) instead of starving it."""
    ordered = sorted(
        list(recommendations),
        key=lambda row: (-int(row.get("score") or 0), str(row.get("firm_name") or "").lower()),
    )
    selected: list[dict[str, Any]] = []
    used_firms: set[str] = set()
    counts: Counter[str] = Counter()

    def _take(pool: list[dict[str, Any]], limit: int, respect_quota: bool) -> None:
        for rec in pool:
            if len(selected) >= limit:
                break
            pif_id = str(rec.get("pif_id") or "")
            persona = str(rec.get("persona") or "")
            if pif_id in used_firms:
                continue
            if respect_quota and counts[persona] >= quota.get(persona, 0):
                continue
            selected.append(rec)
            used_firms.add(pif_id)
            counts[persona] += 1

    if not evidence_pifs:
        _take(ordered, batch_size, True)
        _take(ordered, batch_size, False)
        return selected

    ev = [r for r in ordered if str(r.get("pif_id") or "") in evidence_pifs]
    non_ev = [r for r in ordered if str(r.get("pif_id") or "") not in evidence_pifs]
    reserve = min(max(0, no_evidence_reserve), len(non_ev))
    ev_target = max(0, batch_size - reserve)
    # 1) evidence firms up to the evidence budget (quota first, then relaxed)
    _take(ev, ev_target, True)
    _take(ev, ev_target, False)
    # 2) reserve discovery slots for top no-evidence firms (fills to batch_size)
    _take(non_ev, batch_size, True)
    _take(non_ev, batch_size, False)
    # 3) any slots still open (no-evidence exhausted) -> remaining evidence firms
    _take(ev, batch_size, True)
    _take(ev, batch_size, False)
    return selected


async def _suppressed_pifs_and_behavior(pif_ids: set[str]) -> tuple[set[str], dict[str, dict[str, Any]]]:
    if not pif_ids:
        return set(), {}
    suppressed: set[str] = set()
    behavior: dict[str, dict[str, Any]] = {}
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(FrontFirmActivityRow).where(FrontFirmActivityRow.pif_id.in_(pif_ids))
        )).scalars().all()
    for row in rows:
        terms = json.dumps({
            "inbox_breakdown": row.inbox_breakdown or {},
            "tech_signals": row.tech_signals or {},
        }, sort_keys=True, default=str).lower()
        if any(marker in terms for marker in ("collection", "collections", "non-payment", "nonpayment", "non payment")):
            suppressed.add(str(row.pif_id))
        if row.behavioral_json:
            behavior[str(row.pif_id)] = {
                "after_hours_ratio": (row.behavioral_json or {}).get("after_hours_ratio"),
                "primary_pain_point": (row.behavioral_json or {}).get("primary_pain_point"),
            }
    return suppressed, behavior


async def _select_contacts(
    *,
    weights: dict[str, Any],
    batch_size: int,
    template_key: str,
) -> dict[str, Any]:
    # Widen the candidate pool so evidence-bearing firms (which may rank below
    # the top-20 by base score) are in scope for the evidence-aware preference.
    rec_limit = max(batch_size * 10, 200)
    rec_data = await recommend_sequence_contacts(template_key=template_key, limit=rec_limit)
    recs = list(rec_data.get("recommended") or [])
    pif_ids = {str(r.get("pif_id") or "") for r in recs if r.get("pif_id")}
    suppressed_pifs, behavior_by_pif = await _suppressed_pifs_and_behavior(pif_ids)
    filtered: list[dict[str, Any]] = []
    excluded = Counter()
    for rec in recs:
        pif_id = str(rec.get("pif_id") or "")
        domain = normalize_domain(str(rec.get("contact_email") or ""))
        if domain in HARD_EXCLUDED_DOMAINS:
            excluded["hard_domain"] += 1
            continue
        if pif_id in suppressed_pifs:
            excluded["suppress_flag"] += 1
            continue
        filtered.append(rec)
    quota = _persona_quota(weights)
    # Evidence-aware selection: prefer firms with usable review evidence so the
    # daily slots fill with composable firms, but reserve a few slots for top
    # no-evidence firms to keep the "paste reviews" discovery loop fed.
    evidence_pifs: set[str] | None = None
    reserve = 0
    if os.getenv("LEAD_GEN_EVIDENCE_AWARE_SELECTION", "true").strip().lower() in {"1", "true", "yes", "on"}:
        try:
            from app.services.review_extraction import firms_with_usable_evidence
            evidence_pifs = await firms_with_usable_evidence(
                {str(r.get("pif_id") or "") for r in filtered}
            )
            reserve = int(os.getenv("LEAD_GEN_NO_EVIDENCE_RESERVE", "3"))
        except Exception:
            logger.exception("evidence-aware selection lookup failed; falling back to score-only")
            evidence_pifs = None
    selected = _select_by_persona_quota(
        filtered, quota=quota, batch_size=batch_size,
        evidence_pifs=evidence_pifs, no_evidence_reserve=reserve,
    )
    persona_mix = Counter(str(row.get("persona") or "unknown") for row in selected)
    return {
        "selected": selected,
        "recommendation_counts": rec_data.get("counts") or {},
        "quota": quota,
        "batch_size": batch_size,
        "persona_mix": dict(persona_mix),
        "excluded": dict(excluded),
        "behavior_by_pif": behavior_by_pif,
        "evidence_selected": sum(1 for r in selected if evidence_pifs and str(r.get("pif_id") or "") in evidence_pifs) if evidence_pifs else None,
    }


async def _select_due_followups(
    *,
    batch_size: int,
    template_key: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    due_at = now or _utcnow()
    selected: list[dict[str, Any]] = []
    async with AsyncSessionLocal() as session:
        due_total = (await session.execute(
            select(func.count(EmailSequenceRow.id)).where(
                EmailSequenceRow.status == "active",
                EmailSequenceRow.template_key == template_key,
                EmailSequenceRow.next_step_due_at != None,  # noqa: E711
                EmailSequenceRow.next_step_due_at <= due_at,
            )
        )).scalar_one()
        rows = (await session.execute(
            select(EmailSequenceRow, FirmContactRow)
            .join(FirmContactRow, FirmContactRow.id == EmailSequenceRow.contact_id)
            .where(
                EmailSequenceRow.status == "active",
                EmailSequenceRow.template_key == template_key,
                EmailSequenceRow.next_step_due_at != None,  # noqa: E711
                EmailSequenceRow.next_step_due_at <= due_at,
                EmailSequenceRow.current_step < EmailSequenceRow.steps_total,
                FirmContactRow.email != None,  # noqa: E711
            )
            .order_by(EmailSequenceRow.next_step_due_at.asc())
            .limit(batch_size)
        )).all()

    for seq, contact in rows:
        email = (contact.email or "").strip().lower()
        if not email:
            continue
        step_num = int(seq.current_step or 0) + 1
        selected.append({
            "contact_id": contact.id,
            "pif_id": contact.pif_id,
            "firm_name": await resolve_firm_name(contact.pif_id),
            "contact_name": contact.full_name or "",
            "contact_email": email,
            "contact_title": contact.title or "",
            "persona": contact.persona or "",
            "score": 1000 - len(selected),
            "reason": (
                f"Due sequence follow-up step {step_num} "
                f"(due {seq.next_step_due_at.isoformat() if seq.next_step_due_at else 'now'})."
            ),
            "action_type": "follow_up",
            "priority_bucket": "due_follow_up",
            "source_type": "email_sequence",
            "source_id": seq.id,
            "sequence_id": seq.id,
            "step_num": step_num,
            "steps_total": seq.steps_total,
            "current_step": seq.current_step,
            "next_step_due_at": seq.next_step_due_at.isoformat() if seq.next_step_due_at else None,
            "selection_signals": ["sequence_due"],
            "suppressions": [],
        })
    return {
        "selected": selected[:batch_size],
        "followups_due_total": int(due_total or 0),
    }


async def _select_daily_contacts(
    *,
    weights: dict[str, Any],
    batch_size: int,
    template_key: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not sequences_enabled():
        return await _select_contacts(
            weights=weights,
            batch_size=batch_size,
            template_key=template_key,
        )

    followups = await _select_due_followups(
        batch_size=batch_size,
        template_key=template_key,
        now=now,
    )
    followup_selected = list(followups.get("selected") or [])[:batch_size]
    fresh_limit = max(0, batch_size - len(followup_selected))
    if fresh_limit:
        fresh_result = await _select_contacts(
            weights=weights,
            batch_size=fresh_limit,
            template_key=template_key,
        )
    else:
        fresh_result = {
            "selected": [],
            "recommendation_counts": {},
            "quota": _persona_quota(weights),
            "batch_size": 0,
            "persona_mix": {},
            "excluded": {},
            "behavior_by_pif": {},
        }

    selected = followup_selected + list(fresh_result.get("selected") or [])
    persona_mix = Counter(str(row.get("persona") or "unknown") for row in selected)
    return {
        **fresh_result,
        "selected": selected,
        "batch_size": batch_size,
        "persona_mix": dict(persona_mix),
        "followups_selected": len(followup_selected),
        "fresh_selected": len(fresh_result.get("selected") or []),
        "followups_due_total": int(followups.get("followups_due_total") or 0),
    }


async def _create_daily_batch(
    *,
    run_id: str,
    run_date: date,
    selected: list[dict[str, Any]],
    select_result: dict[str, Any],
    policy: LeadGenPolicyVersionRow | None,
    created_by: str,
    template_key: str,
) -> str:
    active_policy = policy or await ensure_default_policy()
    batch_id = _new_id()
    behavior_by_pif = select_result.get("behavior_by_pif") or {}
    async with AsyncSessionLocal() as session:
        batch = LeadGenBatchRow(
            id=batch_id,
            name=f"Daily run {run_date.isoformat()}",
            target_metric=TARGET_METRIC,
            template_key=template_key,
            policy_version=active_policy.version,
            status="recommended",
            counts_json={
                **(select_result.get("recommendation_counts") or {}),
                "basis": "daily-run",
                "daily_run_id": run_id,
                "requested": select_result.get("batch_size"),
                "returned": len(selected),
                "persona_mix": select_result.get("persona_mix") or {},
                "persona_quota": select_result.get("quota") or {},
                "excluded": select_result.get("excluded") or {},
                **(
                    {
                        "followups_selected": select_result.get("followups_selected", 0),
                        "fresh_selected": select_result.get("fresh_selected", len(selected)),
                        "followups_due_total": select_result.get("followups_due_total", 0),
                    }
                    if sequences_enabled()
                    else {}
                ),
            },
            created_by=created_by,
        )
        session.add(batch)
        await session.flush()
        for rec in selected:
            behavior = behavior_by_pif.get(str(rec.get("pif_id") or ""), {})
            action_type = str(rec.get("action_type") or "first_touch")
            reason_json = {
                "basis": "daily-run",
                "reason": rec.get("reason") or "",
                "contact_source": rec.get("contact_source") or "",
                "policy_version": active_policy.version,
                "daily_run_id": run_id,
                "action_type": action_type,
                "priority_bucket": rec.get("priority_bucket") or "new_conversation",
                "source_type": rec.get("source_type") or "lead_gen_daily_run",
                "source_id": rec.get("source_id") or rec.get("contact_id"),
                "signals": rec.get("selection_signals") or rec.get("signals") or [],
                "next_operator_action": "review_edit_approve_send",
                "selection_policy_version": rec.get("policy_version") or active_policy.version,
                "score_breakdown": rec.get("score_breakdown") or {},
                "selection_features": rec.get("selection_features") or {},
                "suppressions": rec.get("suppressions") or [],
                "persona_quota": select_result.get("quota") or {},
                "behavioral_json": {
                    "after_hours_ratio": behavior.get("after_hours_ratio"),
                    "primary_pain_point": behavior.get("primary_pain_point"),
                },
            }
            if action_type == "follow_up":
                reason_json.update({
                    "sequence_id": rec.get("sequence_id"),
                    "step_num": rec.get("step_num"),
                    "steps_total": rec.get("steps_total"),
                    "current_step": rec.get("current_step"),
                    "next_step_due_at": rec.get("next_step_due_at"),
                })
            session.add(LeadGenBatchItemRow(
                id=_new_id(),
                batch_id=batch_id,
                contact_id=rec["contact_id"],
                pif_id=rec["pif_id"],
                firm_name=rec["firm_name"],
                contact_name=rec.get("contact_name") or "",
                contact_email=rec["contact_email"],
                contact_title=rec.get("contact_title") or "",
                persona=rec.get("persona") or "",
                template_key=template_key,
                score=int(rec.get("score") or 0),
                reason_json=reason_json,
                approval_status="pending",
            ))
            if action_type == "follow_up" and rec.get("sequence_id"):
                seq = await session.get(EmailSequenceRow, str(rec.get("sequence_id")))
                if (
                    seq
                    and seq.status == "active"
                    and int(seq.current_step or 0) + 1 == int(rec.get("step_num") or 0)
                ):
                    # The autonomous scheduler only selects active+due rows,
                    # so this daily-run claim prevents double-drafting.
                    seq.status = "paused"
                    seq.paused_reason = f"awaiting_operator_send_approval:daily_run:{run_id}"
                    seq.next_step_due_at = None
        await session.commit()
    return batch_id


async def _compose_batch(*, batch_id: str, created_by: str, template_key: str) -> dict[str, Any]:
    all_drafts: list[dict[str, Any]] = []
    action_ids: list[str] = []
    errors: list[str] = []
    for _chunk in range(40):
        before = await get_batch(batch_id, include_observations=False)
        pending = [
            item for item in before.get("items") or []
            if item.get("approval_status") in {"pending", "approved"}
            and not (item.get("reason") or {}).get("agent_draft")
            # Held items never get a draft; exclude them so the loop makes
            # progress to the rest instead of re-grabbing the same held chunk.
            and not (item.get("reason") or {}).get("held_reason")
        ]
        if not pending:
            break
        chunk_limit = min(5, len(pending))
        chunk_ok = False
        for attempt in range(2):
            try:
                result = await _compose_batch_items(
                    batch_id=batch_id,
                    created_by=created_by,
                    composer_variant_key=None,
                    approve_actions=False,
                    policy_check_first_action=False,
                    template_key=template_key,
                    only_undrafted_pending=True,
                    limit=chunk_limit,
                )
                all_drafts.extend(result.get("drafts") or [])
                action_ids.extend(result.get("action_ids") or [])
                chunk_ok = True
                break
            except Exception as exc:
                errors.append(f"attempt {attempt + 1}: {type(exc).__name__}: {str(exc)[:300]}")
                logger.exception("daily-run compose chunk failed for batch %s", batch_id)
        if not chunk_ok:
            break
    final = await get_batch(batch_id, include_observations=False)
    items = final.get("items") or []
    drafted = sum(1 for item in items if (item.get("reason") or {}).get("agent_draft"))
    held = sum(1 for item in items if (item.get("reason") or {}).get("held_reason"))
    # "Complete" = every non-held item is drafted. Held items (no usable review
    # evidence) are an intended terminal state, not unfinished work — they must
    # not keep the run in 'partial' and skip schedule/notify.
    return {
        "drafts": all_drafts,
        "action_ids": action_ids,
        "drafted": drafted,
        "held": held,
        "total": len(items),
        "errors": errors,
        "complete": drafted >= (len(items) - held),
    }


def _parse_hhmm(value: str) -> time:
    parts = str(value or "").split(":", 1)
    if len(parts) != 2:
        raise ValueError("invalid_time")
    return time(hour=max(0, min(23, int(parts[0]))), minute=max(0, min(59, int(parts[1]))))


def _next_weekday(start: date, *, weekdays: set[int]) -> date:
    current = start
    for _ in range(14):
        if current.weekday() in weekdays:
            return current
        current += timedelta(days=1)
    return start


def spread_schedule_times(
    *,
    item_ids: list[str],
    now: datetime | None = None,
    window: dict[str, str] | None = None,
    weekdays: set[int] | None = None,
) -> list[datetime]:
    if not item_ids:
        return []
    window = window or DEFAULT_SEND_WINDOW
    weekdays = weekdays or {0, 1, 2, 3, 4}
    tz = ZoneInfo(window.get("timezone") or "America/Los_Angeles")
    local_now = (now or _utcnow()).astimezone(tz)
    start_t = _parse_hhmm(window.get("start") or "09:00")
    end_t = _parse_hhmm(window.get("end") or "11:30")
    target_date = local_now.date()
    end_today = datetime.combine(target_date, end_t, tzinfo=tz)
    if target_date.weekday() not in weekdays or local_now >= end_today:
        target_date = _next_weekday(target_date + timedelta(days=1), weekdays=weekdays)
    else:
        target_date = _next_weekday(target_date, weekdays=weekdays)
    start_dt = datetime.combine(target_date, start_t, tzinfo=tz)
    end_dt = datetime.combine(target_date, end_t, tzinfo=tz)
    total_seconds = max(0, int((end_dt - start_dt).total_seconds()))
    count = len(item_ids)
    times: list[datetime] = []
    for idx, item_id in enumerate(item_ids):
        base_offset = total_seconds // 2 if count == 1 else int((total_seconds * idx) / (count - 1))
        jitter_window = 240
        jitter = (sum(ord(c) for c in item_id) % (jitter_window + 1)) - (jitter_window // 2)
        offset = max(0, min(total_seconds, base_offset + jitter))
        times.append((start_dt + timedelta(seconds=offset)).astimezone(timezone.utc))
    return times


async def _find_waiting_action_for_item(session, batch_item_id: str) -> AgentActionRow | None:
    rows = (await session.execute(
        select(AgentActionRow)
        .where(AgentActionRow.action_type == SEND_EMAIL)
        .where(AgentActionRow.status == "waiting_for_approval")
        .order_by(desc(AgentActionRow.created_at))
    )).scalars().all()
    for row in rows:
        if (row.input_json or {}).get("batch_item_id") == batch_item_id:
            return row
    return None


async def _schedule_drafted_items(
    *,
    batch_id: str,
    created_by: str,
    weights: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    batch = await get_batch(batch_id, include_observations=False)
    drafted = [
        item for item in batch.get("items") or []
        if (item.get("reason") or {}).get("agent_draft")
    ]
    # Autonomous send (operator-authorized): create scheduled send actions as
    # already-approved so the action scheduler sends them at their window time
    # without a manual approval click. Code default OFF — enabled via env. This
    # only removes the human approval step; every send still passes the policy /
    # PHI egress guard at execution time and is spread across the send window.
    auto_approve = auto_approve_send_enabled()
    approver = "auto-approve" if auto_approve else None
    scheduled_times = spread_schedule_times(
        item_ids=[item["id"] for item in drafted],
        now=now,
        window=_send_window(weights),
        weekdays=_weekdays(weights),
    )
    created = updated = skipped = 0
    action_ids: list[str] = []
    subjects: list[str] = []
    scheduled: list[dict[str, Any]] = []
    for item, scheduled_for in zip(drafted, scheduled_times):
        async with AsyncSessionLocal() as session:
            live = await find_live_scheduled_action_for_item(session, item["id"])
            if live:
                skipped += 1
                scheduled.append({"item_id": item["id"], "skipped": "already_approved_scheduled", **live})
                continue
            row = await _find_waiting_action_for_item(session, item["id"])
            reason = dict(item.get("reason") or {})
            draft = dict(reason.get("agent_draft") or {})
            if row:
                row.scheduled_for = scheduled_for
                row.updated_at = _utcnow()
                if approver and row.status == "waiting_for_approval":
                    row.status = "approved"
                    row.approved_by = approver
                    row.approved_at = _utcnow()
                await _record_action_event(
                    session,
                    action_id=row.id,
                    event_type="action_scheduled",
                    actor=created_by,
                    message=(
                        "Daily run scheduled draft (auto-approved for send)."
                        if approver else "Daily run scheduled draft awaiting approval."
                    ),
                    input_json={"scheduled_for": scheduled_for.isoformat(), "batch_item_id": item["id"]},
                )
                item_row = await session.get(LeadGenBatchItemRow, item["id"])
                if item_row:
                    item_reason = dict(item_row.reason_json or {})
                    item_draft = dict(item_reason.get("agent_draft") or {})
                    item_draft.update({
                        "action_id": row.id,
                        "action_status": row.status,
                        "scheduled_for_pt": format_pt(scheduled_for),
                        "scheduled_for_utc": format_utc(scheduled_for),
                    })
                    item_reason["agent_draft"] = item_draft
                    item_reason["send_email_action_id"] = row.id
                    item_reason["next_operator_action"] = (
                        "auto_send_scheduled" if approver else "review_approve_scheduled_send"
                    )
                    item_row.reason_json = item_reason
                await session.commit()
                await session.refresh(row)
                updated += 1
                action = {
                    "id": row.id,
                    "status": row.status,
                    "scheduled_for": row.scheduled_for.isoformat() if row.scheduled_for else None,
                }
            else:
                action = await create_send_email_action(
                    mode="lead_gen",
                    to=item["contact_email"],
                    subject=str(draft.get("subject") or ""),
                    body=str(draft.get("body") or ""),
                    requested_by=created_by,
                    approved_by=approver,
                    contact_id=item["contact_id"],
                    batch_item_id=item["id"],
                    pif_id=item["pif_id"],
                    firm_name=item["firm_name"],
                    composer_experiment_key=draft.get("composer_experiment_key"),
                    composer_variant_key=draft.get("composer_variant_key"),
                    skill_path=draft.get("skill_path"),
                    skill_sha256=draft.get("skill_sha256"),
                    brief_version=draft.get("brief_version"),
                    scheduled_for=scheduled_for,
                )
                created += 1
            action_ids.append(action["id"])
            subjects.append(str(draft.get("subject") or ""))
            scheduled.append({
                "item_id": item["id"],
                "action_id": action["id"],
                "status": action.get("status"),
                "scheduled_for_pt": format_pt(scheduled_for),
                "scheduled_for_utc": format_utc(scheduled_for),
            })
    return {
        "scheduled": len(action_ids),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "action_ids": action_ids,
        "subjects": [s for s in subjects if s][:3],
        "items": scheduled,
    }


def build_notify_message(*, batch_id: str | None, item_count: int, draft_count: int, persona_mix: dict[str, Any], subjects: list[str]) -> str:
    subject_lines = "; ".join(subjects[:3]) if subjects else "No subjects drafted"
    return (
        "[from cc] Daily lead-gen run ready for review. "
        f"batch={batch_id or 'none'} items={item_count} drafts={draft_count} "
        f"persona_mix={json.dumps(persona_mix, sort_keys=True)} "
        f"first_subjects={subject_lines}. review at /lead-gen"
    )


async def _notify_operator(
    *,
    batch_id: str | None,
    item_count: int,
    draft_count: int,
    persona_mix: dict[str, Any],
    subjects: list[str],
) -> dict[str, Any]:
    to = os.getenv("OPERATOR_WHATSAPP", "+918287149638")
    message = build_notify_message(
        batch_id=batch_id,
        item_count=item_count,
        draft_count=draft_count,
        persona_mix=persona_mix,
        subjects=subjects,
    )

    def _send() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["openclaw", "message", "send", "--channel", "whatsapp", "-t", to, "--message", message],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )

    try:
        proc = await asyncio.to_thread(_send)
        return {
            "sent": proc.returncode == 0,
            "returncode": proc.returncode,
            "to": to,
            "message": message,
            "stdout": (proc.stdout or "")[-500:],
            "stderr": (proc.stderr or "")[-500:],
        }
    except subprocess.TimeoutExpired:
        logger.warning("daily-run WhatsApp notify timed out")
        return {"sent": False, "timeout": True, "to": to, "message": message}
    except FileNotFoundError:
        logger.warning("openclaw CLI not found for daily-run WhatsApp notify")
        return {"sent": False, "error": "openclaw_cli_not_found", "to": to, "message": message}


async def _notify_yelp_reviews_needed(select_result: dict[str, Any]) -> dict[str, int]:
    """Prompt the operator (action center) to paste Yelp reviews for each
    selected FIRST-TOUCH firm that has no citable quote yet, and resolve prompts
    for firms that now have one. Deduped per pif_id; top-ranked firms get high
    priority. This is what turns "select the ideal firm" into a "go get its Yelp
    review" ask, so the Yelp-quote email can cite a real complaint."""
    from app.services.firm_contacts_service import fetch_pain_quote_for_firm
    from app.services.operator_notifications import create_operator_notification, resolve_notifications

    selected = select_result.get("selected") or []
    followups_n = int(select_result.get("followups_selected") or 0)
    fresh = selected[followups_n:]  # first-touch items only (followups are first)

    created = resolved = 0
    seen: set[str] = set()
    for rank, item in enumerate(fresh):
        pif_id = str(item.get("pif_id") or "").strip()
        if not pif_id or pif_id in seen:
            continue
        seen.add(pif_id)
        firm_name = str(item.get("firm_name") or "").strip() or "this firm"
        try:
            quote = await fetch_pain_quote_for_firm(pif_id)
        except Exception:
            quote = {}
        if quote.get("pain_quote"):
            resolved += await resolve_notifications(notification_type="yelp_review_needed", source_id=pif_id)
            continue
        try:
            async with AsyncSessionLocal() as session:
                await create_operator_notification(
                    session,
                    notification_type="yelp_review_needed",
                    title=f"Yelp reviews needed: {firm_name}",
                    body=(f"{firm_name} is queued for outbound but has no citable Yelp quote. "
                          f"Paste its Yelp reviews so the first email can cite a real client complaint."),
                    source_type="firm",
                    source_id=pif_id,
                    priority="high" if rank < 3 else "normal",
                    context={"pif_id": pif_id, "firm_name": firm_name, "rank": rank, "persona": item.get("persona")},
                    suggested_action={"kind": "paste_yelp_reviews", "label": "Paste Yelp reviews", "url": f"/firms/{pif_id}"},
                )
                await session.commit()
            created += 1
        except Exception:
            logger.exception("failed to create yelp_review_needed notification for %s", pif_id)
    logger.info("yelp_review_needed prompts: created=%d resolved=%d", created, resolved)
    return {"created": created, "resolved": resolved}


async def run_daily_pipeline(
    *,
    dry_run: bool = False,
    force: bool = False,
    created_by: str = "daily-run",
    run_date: date | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run or resume today's deterministic daily lead-gen pipeline.

    Dry runs intentionally avoid writes and external side effects so operators
    can validate live selection without creating actions or consuming research
    API budget.
    """
    now = now or _utcnow()
    target_date = run_date or _date_for_run(now)
    policy = await _active_policy()
    weights = _policy_weights(policy)
    template_key = str(weights.get("daily_template_key") or DEFAULT_TEMPLATE_KEY)
    batch_size = _int_policy(weights, "daily_batch_size", 20, minimum=1, maximum=200)

    if dry_run:
        stages: dict[str, Any] = {}
        gates = await _run_gates(weights, now=now, force=force)
        stages["gates"] = {"status": "completed" if gates["passed"] else "skipped", "counts": gates}
        if gates["passed"]:
            status_data = await front_status()
            age = (status_data.get("sync_health") or {}).get("last_run_age_hours")
            stages["signals"] = {"status": "completed", "counts": {"front_last_run_age_hours": age, "would_refresh": age is None or age > 30}}
            stages["research"] = {"status": "skipped", "reason": "dry_run"}
            stages["personas"] = {"status": "skipped", "reason": "dry_run"}
            selected = await _select_daily_contacts(
                weights=weights,
                batch_size=batch_size,
                template_key=template_key,
                now=now,
            )
            select_counts = {
                "selected": len(selected["selected"]),
                "persona_mix": selected["persona_mix"],
                "excluded": selected["excluded"],
            }
            if sequences_enabled():
                select_counts.update({
                    "followups_selected": selected.get("followups_selected", 0),
                    "fresh_selected": selected.get("fresh_selected", len(selected["selected"])),
                    "followups_due_total": selected.get("followups_due_total", 0),
                })
            stages["select"] = {
                "status": "completed",
                "counts": select_counts,
            }
            stages["batch"] = {"status": "skipped", "reason": "dry_run"}
            stages["compose"] = {"status": "skipped", "reason": "dry_run"}
            stages["schedule"] = {"status": "skipped", "reason": "dry_run"}
            stages["notify"] = {"status": "skipped", "reason": "dry_run"}
        return {
            "id": f"dry-run-{target_date.isoformat()}",
            "run_date": target_date.isoformat(),
            "status": "skipped" if not gates["passed"] else "completed",
            "stage": "dry_run",
            "stages": stages,
            "batch_id": None,
            "dry_run": True,
        }

    row, should_run = await _create_or_get_run(run_date=target_date, created_by=created_by, force=force)
    if not should_run and row.status != "partial":
        return _run_to_dict(row)

    stages = dict(row.stages_json or {})
    select_result: dict[str, Any] | None = None
    schedule_result: dict[str, Any] = {}

    try:
        if not _stage_done(stages, "gates"):
            await _checkpoint(row.id, stage="gates", status="running", run_status="running")
            gates = await _run_gates(weights, now=now, force=force)
            if not gates["passed"]:
                row = await _checkpoint(
                    row.id,
                    stage="gates",
                    status="skipped",
                    counts=gates,
                    run_status="skipped",
                    extra={"reason": gates.get("reason")},
                )
                return _run_to_dict(row)
            row = await _checkpoint(row.id, stage="gates", status="completed", counts=gates, run_status="running")

        if not _stage_done(row.stages_json or {}, "signals"):
            await _checkpoint(row.id, stage="signals", status="running")
            status_data = await front_status()
            age = (status_data.get("sync_health") or {}).get("last_run_age_hours")
            refreshed: dict[str, Any] = {}
            if age is None or float(age) > 30:
                refreshed["resolve"] = await resolve_firms()
                refreshed["scores"] = await refresh_warm_scores()
            row = await _checkpoint(
                row.id,
                stage="signals",
                status="completed",
                counts={"front_last_run_age_hours": age, "refreshed": bool(refreshed)},
                extra=refreshed,
            )

        if not _stage_done(row.stages_json or {}, "research"):
            await _checkpoint(row.id, stage="research", status="running")
            try:
                research_budget = _int_policy(weights, "daily_research_budget", 10, minimum=0, maximum=100)
                if research_budget > 0:
                    research = await orchestrate_warm_research(
                        top_n=research_budget,
                        kinds=["research", "analyze_behavior"],
                        timeout_seconds=600,
                        poll_interval_seconds=15,
                    )
                else:
                    research = {"skipped": "daily_research_budget_zero"}
                row = await _checkpoint(row.id, stage="research", status="completed", counts=research)
            except Exception as exc:
                row = await _checkpoint(
                    row.id,
                    stage="research",
                    status="partial",
                    error=f"{type(exc).__name__}: {str(exc)[:500]}",
                    run_status="running",
                )

        if not _stage_done(row.stages_json or {}, "personas"):
            await _checkpoint(row.id, stage="personas", status="running")
            personas = await map_personas()
            row = await _checkpoint(row.id, stage="personas", status="completed", counts=personas)

        if not _stage_done(row.stages_json or {}, "select"):
            await _checkpoint(row.id, stage="select", status="running")
            select_result = await _select_daily_contacts(
                weights=weights,
                batch_size=batch_size,
                template_key=template_key,
                now=now,
            )
            select_counts = {
                "selected": len(select_result["selected"]),
                "batch_size": batch_size,
                "persona_mix": select_result["persona_mix"],
                "excluded": select_result["excluded"],
                "recommendation_counts": select_result["recommendation_counts"],
            }
            if sequences_enabled():
                select_counts.update({
                    "followups_selected": select_result.get("followups_selected", 0),
                    "fresh_selected": select_result.get("fresh_selected", len(select_result["selected"])),
                    "followups_due_total": select_result.get("followups_due_total", 0),
                })
            row = await _checkpoint(
                row.id,
                stage="select",
                status="completed",
                counts=select_counts,
                extra={"selected_contact_ids": [r["contact_id"] for r in select_result["selected"]]},
            )

        if not _stage_done(row.stages_json or {}, "batch"):
            await _checkpoint(row.id, stage="batch", status="running")
            if select_result is None:
                select_result = await _select_daily_contacts(
                    weights=weights,
                    batch_size=batch_size,
                    template_key=template_key,
                    now=now,
                )
            batch_id = await _create_daily_batch(
                run_id=row.id,
                run_date=target_date,
                selected=select_result["selected"],
                select_result=select_result,
                policy=policy,
                created_by=created_by,
                template_key=template_key,
            )
            row = await _checkpoint(
                row.id,
                stage="batch",
                status="completed",
                counts={"items": len(select_result["selected"])},
                batch_id=batch_id,
            )
            # Ask the operator (action center) to paste Yelp reviews for selected
            # first-touch firms missing a citable quote; resolve ones now covered.
            try:
                await _notify_yelp_reviews_needed(select_result)
            except Exception:
                logger.exception("yelp_review_needed notification pass failed")

        if not _stage_done(row.stages_json or {}, "compose"):
            await _checkpoint(row.id, stage="compose", status="running")
            if not row.batch_id:
                raise ValueError("batch_id_missing_for_compose")
            compose = await _compose_batch(batch_id=row.batch_id, created_by=created_by, template_key=template_key)
            row = await _checkpoint(
                row.id,
                stage="compose",
                status="completed" if compose["complete"] else "partial",
                counts=compose,
                run_status="running" if compose["complete"] else "partial",
                error="; ".join(compose["errors"][-2:]) if compose["errors"] and not compose["complete"] else None,
            )
            if not compose["complete"]:
                return _run_to_dict(row)

        if not _stage_done(row.stages_json or {}, "schedule"):
            await _checkpoint(row.id, stage="schedule", status="running")
            if not row.batch_id:
                raise ValueError("batch_id_missing_for_schedule")
            schedule_result = await _schedule_drafted_items(
                batch_id=row.batch_id,
                created_by=created_by,
                weights=weights,
                now=now,
            )
            row = await _checkpoint(row.id, stage="schedule", status="completed", counts=schedule_result)

        if not _stage_done(row.stages_json or {}, "notify"):
            await _checkpoint(row.id, stage="notify", status="running")
            batch = await get_batch(row.batch_id, include_observations=False) if row.batch_id else {"items": []}
            items = batch.get("items") or []
            persona_mix = dict(Counter(str(item.get("persona") or "unknown") for item in items))
            draft_count = sum(1 for item in items if (item.get("reason") or {}).get("agent_draft"))
            subjects = schedule_result.get("subjects") or [
                ((item.get("reason") or {}).get("agent_draft") or {}).get("subject")
                for item in items
                if ((item.get("reason") or {}).get("agent_draft") or {}).get("subject")
            ][:3]
            notify = await _notify_operator(
                batch_id=row.batch_id,
                item_count=len(items),
                draft_count=draft_count,
                persona_mix=persona_mix,
                subjects=subjects,
            )
            row = await _checkpoint(row.id, stage="notify", status="completed", counts=notify)

        row = await _checkpoint(row.id, stage="done", status="completed", run_status="completed")
        return _run_to_dict(row)
    except Exception as exc:
        logger.exception("daily lead-gen pipeline failed")
        current_stage = row.stage if row else "unknown"
        row = await _checkpoint(
            row.id,
            stage=current_stage,
            status="failed",
            error=f"{type(exc).__name__}: {str(exc)[:500]}",
            run_status="partial" if row and row.batch_id else "failed",
        )
        return _run_to_dict(row)


async def list_daily_runs(*, limit: int = 20) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(LeadGenDailyRunRow)
            .order_by(desc(LeadGenDailyRunRow.run_date), desc(LeadGenDailyRunRow.created_at))
            .limit(max(1, min(int(limit), 100)))
        )).scalars().all()
    return [_run_to_dict(row) for row in rows]


async def get_daily_run(*, run_date: date | None = None) -> dict[str, Any] | None:
    target = run_date or _date_for_run()
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(LeadGenDailyRunRow).where(LeadGenDailyRunRow.run_date == target)
        )).scalar_one_or_none()
    return _run_to_dict(row) if row else None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _item_warm_score(reason: dict[str, Any]) -> int | None:
    features = reason.get("selection_features")
    if isinstance(features, dict):
        score = _int_or_none(features.get("front_warm_score"))
        if score is not None:
            return score
    for key in ("front_warm_score", "warm_score"):
        score = _int_or_none(reason.get(key))
        if score is not None:
            return score
    return None


async def _sent_lead_gen_count(start_utc: datetime, end_utc: datetime) -> int:
    async with AsyncSessionLocal() as session:
        return int((await session.execute(
            select(func.count(AgentActionRow.id))
            .where(AgentActionRow.action_type == SEND_EMAIL)
            .where(AgentActionRow.entity_type == "lead_gen_email")
            .where(AgentActionRow.status == "succeeded")
            .where(AgentActionRow.completed_at >= start_utc)
            .where(AgentActionRow.completed_at < end_utc)
        )).scalar_one() or 0)


async def get_daily_run_throughput(*, run_date: date | None = None) -> dict[str, Any]:
    """Read-only daily throughput view for the operator control panel."""
    target_date = run_date or _date_for_run()
    today_start_utc, today_end_utc = _pt_day_bounds(target_date)
    yesterday_start_utc, _ = _pt_day_bounds(target_date - timedelta(days=1))
    seven_day_start_utc, _ = _pt_day_bounds(target_date - timedelta(days=6))
    policy = await _active_policy()
    target = _int_policy(_policy_weights(policy), "daily_send_budget", 50, minimum=1, maximum=200)
    history = {
        "yesterday_sent": await _sent_lead_gen_count(yesterday_start_utc, today_start_utc),
        "seven_day_sent": await _sent_lead_gen_count(seven_day_start_utc, today_end_utc),
    }

    async with AsyncSessionLocal() as session:
        run = (await session.execute(
            select(LeadGenDailyRunRow).where(LeadGenDailyRunRow.run_date == target_date)
        )).scalar_one_or_none()

    base = {
        "run_date": target_date.isoformat(),
        "run_status": "none",
        "batch_id": None,
        "target": target,
        "auto_send_on": auto_approve_send_enabled(),
        "history": history,
        "funnel": {
            "selected": 0,
            "with_evidence": 0,
            "composed": 0,
            "sending_today": 0,
            "sent_today": 0,
            "held": 0,
        },
        "verdict": {"will_hit_target": False, "shortfall": target, "blocker": "below_target"},
        "held_firms": [],
    }
    if not run or not run.batch_id:
        return base

    try:
        batch = await get_batch(run.batch_id, include_observations=False)
    except ValueError:
        base["run_status"] = run.status
        base["batch_id"] = run.batch_id
        return base

    items = list(batch.get("items") or [])
    item_ids = [str(item.get("id")) for item in items if item.get("id")]
    pif_ids = {str(item.get("pif_id")) for item in items if item.get("pif_id")}
    evidence_pifs = await firms_with_usable_evidence(pif_ids)
    composed = sum(1 for item in items if (item.get("reason") or {}).get("agent_draft"))
    held_items = [item for item in items if (item.get("reason") or {}).get("held_reason")]

    sending_today = 0
    sent_today = 0
    raw_review_pifs: set[str] = set()
    if item_ids or pif_ids:
        async with AsyncSessionLocal() as session:
            if item_ids:
                actions = (await session.execute(
                    select(AgentActionRow)
                    .where(AgentActionRow.action_type == SEND_EMAIL)
                    .where(AgentActionRow.entity_type == "lead_gen_email")
                    .where(AgentActionRow.entity_id.in_(item_ids))
                    .where(AgentActionRow.status.in_(["approved", "queued", "running", "succeeded"]))
                )).scalars().all()
                for action in actions:
                    if (
                        action.status in {"approved", "queued", "running"}
                        and action.scheduled_for
                        and today_start_utc <= action.scheduled_for < today_end_utc
                    ):
                        sending_today += 1
                    elif (
                        action.status == "succeeded"
                        and action.completed_at
                        and today_start_utc <= action.completed_at < today_end_utc
                    ):
                        sending_today += 1
                        sent_today += 1
            if pif_ids:
                review_rows = (await session.execute(
                    select(FirmReviewRow).where(FirmReviewRow.pif_id.in_(pif_ids))
                )).scalars().all()
                raw_review_pifs = {
                    row.pif_id
                    for row in review_rows
                    if split_raw_reviews(row.yelp_content).strip()
                }

    held_firms = []
    for rank, item in enumerate(sorted(held_items, key=lambda i: int(i.get("score") or 0), reverse=True), 1):
        reason = dict(item.get("reason") or {})
        pif_id = str(item.get("pif_id") or "")
        held_firms.append({
            "pif_id": pif_id,
            "firm_name": item.get("firm_name") or "",
            "rank": rank,
            "warm_score": _item_warm_score(reason),
            "persona": item.get("persona") or "",
            "contact_name": item.get("contact_name") or "",
            "contact_email": item.get("contact_email") or "",
            "has_raw_reviews": pif_id in raw_review_pifs,
            "has_usable_evidence": pif_id in evidence_pifs,
            "held_reason": reason.get("held_reason") or "",
        })

    blocker = "none"
    if sending_today < target:
        blocker = "no_review_evidence" if items and len(evidence_pifs) == 0 else "below_target"
    funnel = {
        "selected": len(items),
        "with_evidence": len(evidence_pifs),
        "composed": composed,
        "sending_today": sending_today,
        "sent_today": sent_today,
        "held": len(held_items),
    }
    return {
        **base,
        "run_status": run.status,
        "batch_id": run.batch_id,
        "funnel": funnel,
        "verdict": {
            "will_hit_target": sending_today >= target,
            "shortfall": max(0, target - sending_today),
            "blocker": blocker,
        },
        "held_firms": held_firms,
    }


async def get_daily_run_enabled() -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        row = (await session.execute(select(SystemSettingsRow).where(SystemSettingsRow.id == 1))).scalar_one_or_none()
        config = dict(getattr(row, "agent_config", None) or {}) if row else {}
    return {"enabled": bool(config.get(DAILY_RUN_CONFIG_KEY, False)), "key": DAILY_RUN_CONFIG_KEY}


async def set_daily_run_enabled(enabled: bool) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        row = (await session.execute(select(SystemSettingsRow).where(SystemSettingsRow.id == 1))).scalar_one_or_none()
        if row is None:
            row = SystemSettingsRow(id=1, business_hours={}, queue_thresholds={}, agent_config={})
            session.add(row)
        config = dict(row.agent_config or {})
        config[DAILY_RUN_CONFIG_KEY] = bool(enabled)
        config["daily_run_enabled_updated_at"] = _utcnow().isoformat()
        row.agent_config = config
        await session.commit()
    return {"enabled": bool(enabled), "key": DAILY_RUN_CONFIG_KEY}


def _in_daily_loop_window(now: datetime | None = None) -> bool:
    local = (now or _utcnow()).astimezone(RUN_TZ)
    return local.weekday() < 5 and RUN_WINDOW_START <= local.time() < RUN_WINDOW_END


async def daily_run_loop(interval_seconds: int = 600) -> None:
    """Background loop. Wired on startup, but default-off and no-op disabled."""
    logger.info("lead_gen_daily_run_loop starting (interval=%ss, default disabled)", interval_seconds)
    while True:
        try:
            enabled = await get_daily_run_enabled()
            if enabled["enabled"] and _in_daily_loop_window():
                today = _date_for_run()
                current = await get_daily_run(run_date=today)
                if not current or current.get("status") not in {"completed", "running"}:
                    await run_daily_pipeline(created_by="daily-run-loop", run_date=today)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("lead_gen_daily_run_loop tick failed")
        await asyncio.sleep(interval_seconds)
