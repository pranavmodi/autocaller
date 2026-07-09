"""Experiment lifecycle and honest rollups for lead-gen waves.

The source of truth is a lead_gen_batches row. The experiment card captures the
pre-send contract; raw telemetry stays in existing sensor tables and is rolled
up with explicit evidence quality labels.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, func, or_, select

from app.db import AsyncSessionLocal
from app.db.models import (
    AuditLinkClickRow,
    InboundEmailRow,
    LeadGenBatchItemRow,
    LeadGenBatchRow,
    LeadGenObservationRow,
)


EXPERIMENT_STATUSES = {
    "none",
    "draft",
    "ready",
    "scheduled",
    "measuring",
    "awaiting_verdict",
    "closed",
    "superseded",
}
REQUIRED_CARD_FIELDS = (
    "wave_id",
    "goal",
    "primary_metric",
    "hypothesis",
    "changed_vs_previous",
    "prediction",
    "success_threshold",
    "measurement_window_hours",
    "minimum_n",
    "confidence_note",
    "invalidation_criteria",
    "owner",
)
REQUIRED_CLOSE_FIELDS = (
    "verdict",
    "learning",
    "why",
    "next_hypothesis",
    "next_recommended_wave",
    "confidence_note",
)
TERMINAL_EXPERIMENT_STATUSES = {"closed", "superseded"}
REPLY_OUTCOMES = {
    "positive_reply",
    "reply",
    "referral",
    "forwarded_internally",
    "owner_introduction",
    "booked_qualified_conversation",
    "needs_human_review",
}
SCANNER_UA_PATTERNS = (
    "proofpoint",
    "mimecast",
    "barracuda",
    "safelinks",
    "urlprotect",
    "defender",
    "microsoft office",
    "microsoft preview",
    "googleimageproxy",
    "google web preview",
    "curl/",
    "python-requests",
    "headlesschrome",
)
BROWSER_UA_PATTERNS = ("mozilla/", "chrome/", "safari/", "firefox/", "edg/")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _card_missing_fields(card: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for field in REQUIRED_CARD_FIELDS:
        if field == "measurement_window_hours":
            try:
                if int(card.get(field) or 0) <= 0:
                    missing.append(field)
            except (TypeError, ValueError):
                missing.append(field)
            continue
        if field == "minimum_n":
            try:
                if int(card.get(field) or 0) <= 0:
                    missing.append(field)
            except (TypeError, ValueError):
                missing.append(field)
            continue
        if not _clean_text(card.get(field)):
            missing.append(field)
    return missing


def _close_missing_fields(patch: dict[str, Any]) -> list[str]:
    return [field for field in REQUIRED_CLOSE_FIELDS if not _clean_text(patch.get(field))]


def _is_wave_name(name: str | None) -> bool:
    return bool(re.search(r"\bwave\b", name or "", flags=re.IGNORECASE))


def is_experiment_batch(batch: LeadGenBatchRow) -> bool:
    return (
        batch.experiment_status != "none"
        or bool(_as_dict(batch.experiment_json))
        or _is_wave_name(batch.name)
    )


def experiment_card_summary(batch: LeadGenBatchRow) -> dict[str, Any]:
    card = _as_dict(batch.experiment_json)
    missing = _card_missing_fields(card)
    return {
        "status": batch.experiment_status,
        "card": card,
        "is_experiment": is_experiment_batch(batch),
        "is_ready": not missing and bool(card),
        "missing_fields": missing,
        "updated_at": batch.experiment_updated_at.isoformat() if batch.experiment_updated_at else None,
        "closed_at": batch.experiment_closed_at.isoformat() if batch.experiment_closed_at else None,
    }


def _set_experiment_status(batch: LeadGenBatchRow, status: str, *, now: datetime | None = None) -> None:
    if status not in EXPERIMENT_STATUSES:
        raise ValueError("invalid_experiment_status")
    batch.experiment_status = status
    batch.experiment_updated_at = now or _utcnow()
    if status in TERMINAL_EXPERIMENT_STATUSES:
        batch.experiment_closed_at = batch.experiment_updated_at


def _measurement_window_hours(card: dict[str, Any]) -> int:
    try:
        return max(1, min(int(card.get("measurement_window_hours") or 72), 720))
    except (TypeError, ValueError):
        return 72


def _experiment_started_at(batch: LeadGenBatchRow, items: list[LeadGenBatchItemRow]) -> datetime | None:
    sent_times: list[datetime] = []
    for item in items:
        reason = _as_dict(item.reason_json)
        sent_at = _parse_datetime(reason.get("last_sent_at"))
        if sent_at:
            sent_times.append(sent_at)
    if sent_times:
        return min(sent_times)
    return batch.started_at or batch.approved_at


def _sync_due_status(batch: LeadGenBatchRow, items: list[LeadGenBatchItemRow], *, now: datetime | None = None) -> bool:
    if batch.experiment_status not in {"scheduled", "measuring"}:
        return False
    card = _as_dict(batch.experiment_json)
    started_at = _experiment_started_at(batch, items)
    if not started_at:
        return False
    due_at = started_at + timedelta(hours=_measurement_window_hours(card))
    if (now or _utcnow()) >= due_at:
        _set_experiment_status(batch, "awaiting_verdict", now=now)
        return True
    return False


async def set_batch_experiment(
    batch_id: str,
    patch: dict[str, Any],
    *,
    actor: str = "operator",
) -> dict[str, Any]:
    if not isinstance(patch, dict):
        raise ValueError("experiment_patch_must_be_object")
    now = _utcnow()
    async with AsyncSessionLocal() as session:
        batch = await session.get(LeadGenBatchRow, batch_id)
        if not batch:
            raise ValueError("batch_not_found")
        current = _as_dict(batch.experiment_json)
        card = {**current, **patch}
        card["last_updated_by"] = actor
        card["last_updated_at"] = now.isoformat()
        batch.experiment_json = card
        if batch.experiment_status in TERMINAL_EXPERIMENT_STATUSES:
            status = batch.experiment_status
        else:
            status = "ready" if not _card_missing_fields(card) else "draft"
        _set_experiment_status(batch, status, now=now)
        await session.commit()
        await session.refresh(batch)
        return {"batch_id": batch.id, "experiment": experiment_card_summary(batch)}


async def close_batch_experiment(
    batch_id: str,
    patch: dict[str, Any],
    *,
    actor: str = "operator",
    superseded: bool = False,
) -> dict[str, Any]:
    if not isinstance(patch, dict):
        raise ValueError("experiment_close_patch_must_be_object")
    missing = _close_missing_fields(patch)
    if missing:
        raise ValueError(f"experiment_close_missing_fields:{','.join(missing)}")
    now = _utcnow()
    async with AsyncSessionLocal() as session:
        batch = await session.get(LeadGenBatchRow, batch_id)
        if not batch:
            raise ValueError("batch_not_found")
        card = _as_dict(batch.experiment_json)
        card.update(patch)
        card["closed_by"] = actor
        card["closed_at"] = now.isoformat()
        batch.experiment_json = card
        _set_experiment_status(batch, "superseded" if superseded else "closed", now=now)
        await session.commit()
        await session.refresh(batch)
        return {"batch_id": batch.id, "experiment": experiment_card_summary(batch)}


async def assert_batch_experiment_send_gate(session, batch: LeadGenBatchRow) -> None:
    if not is_experiment_batch(batch):
        return
    if batch.experiment_status in TERMINAL_EXPERIMENT_STATUSES:
        raise ValueError(f"experiment_{batch.experiment_status}: batch cannot send as an active wave")
    card = _as_dict(batch.experiment_json)
    missing = _card_missing_fields(card)
    if missing:
        raise ValueError(f"experiment_card_required:missing={','.join(missing)}")
    if batch.experiment_status in {"none", "draft"}:
        _set_experiment_status(batch, "ready")
        await session.flush()


async def assert_experiment_send_gate_for_item(session, batch_item_id: str) -> LeadGenBatchRow | None:
    item = await session.get(LeadGenBatchItemRow, batch_item_id) if batch_item_id else None
    if not item:
        return None
    batch = await session.get(LeadGenBatchRow, item.batch_id)
    if not batch:
        return None
    await assert_batch_experiment_send_gate(session, batch)
    return batch


async def mark_experiment_scheduled_for_item(session, batch_item_id: str) -> None:
    batch = await assert_experiment_send_gate_for_item(session, batch_item_id)
    if not batch or not is_experiment_batch(batch):
        return
    if batch.experiment_status in {"ready", "draft"}:
        _set_experiment_status(batch, "scheduled")


async def mark_experiment_measuring_for_item(session, batch_item_id: str) -> None:
    item = await session.get(LeadGenBatchItemRow, batch_item_id) if batch_item_id else None
    if not item:
        return
    batch = await session.get(LeadGenBatchRow, item.batch_id)
    if not batch or not is_experiment_batch(batch):
        return
    if batch.experiment_status in {"ready", "draft", "scheduled"}:
        _set_experiment_status(batch, "measuring")


def signal_quality(event_type: str, raw_event: dict[str, Any] | None = None, *, user_agent: str | None = None) -> str:
    raw = raw_event or {}
    ua = (user_agent or raw.get("user_agent") or raw.get("ua") or "").lower()
    if any(pattern in ua for pattern in SCANNER_UA_PATTERNS):
        return "scanner"
    if event_type == "page_session":
        try:
            time_ms = int(raw.get("time_on_page_ms") or 0)
        except (TypeError, ValueError):
            time_ms = 0
        if not ua:
            return "suspect"
        if any(pattern in ua for pattern in BROWSER_UA_PATTERNS) and time_ms >= 3000:
            return "human"
        return "suspect"
    if event_type == "link_clicked":
        if not ua:
            return "unknown"
        if any(pattern in ua for pattern in BROWSER_UA_PATTERNS):
            return "suspect"
        return "unknown"
    return "unknown"


def _is_sent(item: LeadGenBatchItemRow) -> bool:
    reason = _as_dict(item.reason_json)
    return bool(
        item.approval_status == "started"
        or reason.get("last_sent_at")
        or reason.get("last_sent_message_id")
    )


def _group_key(value: Any, fallback: str) -> str:
    clean = _clean_text(value)
    return clean or fallback


def _rollup_group(
    items: list[LeadGenBatchItemRow],
    observations_by_item: dict[str, list[LeadGenObservationRow]],
    key_fn,
) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for item in items:
        key = key_fn(item)
        row = rows.setdefault(key, {"key": key, "planned": 0, "sent": 0, "bounced": 0, "replies": 0})
        row["planned"] += 1
        if _is_sent(item):
            row["sent"] += 1
        if item.outcome == "bounce":
            row["bounced"] += 1
        for obs in observations_by_item.get(item.id, []):
            if obs.classified_outcome in REPLY_OUTCOMES or obs.event_type in {"email_reply", "email_reply_received"}:
                row["replies"] += 1
    return sorted(rows.values(), key=lambda row: (-int(row["sent"]), row["key"]))


async def experiment_rollup(batch_id: str) -> dict[str, Any]:
    now = _utcnow()
    async with AsyncSessionLocal() as session:
        batch = await session.get(LeadGenBatchRow, batch_id)
        if not batch:
            raise ValueError("batch_not_found")
        items = list((
            await session.execute(
                select(LeadGenBatchItemRow)
                .where(LeadGenBatchItemRow.batch_id == batch_id)
                .order_by(LeadGenBatchItemRow.created_at.asc())
            )
        ).scalars().all())
        _sync_due_status(batch, items, now=now)
        if session.is_modified(batch):
            await session.commit()
            await session.refresh(batch)
        observations = list((
            await session.execute(
                select(LeadGenObservationRow)
                .where(LeadGenObservationRow.batch_id == batch_id)
                .order_by(LeadGenObservationRow.created_at.asc())
            )
        ).scalars().all())
        item_ids = [item.id for item in items]
        clicks: list[AuditLinkClickRow] = []
        inbound: list[InboundEmailRow] = []
        if item_ids:
            clicks = list((
                await session.execute(
                    select(AuditLinkClickRow)
                    .where(AuditLinkClickRow.batch_item_id.in_(item_ids))
                    .order_by(AuditLinkClickRow.clicked_at.asc())
                )
            ).scalars().all())
            inbound = list((
                await session.execute(
                    select(InboundEmailRow)
                    .where(InboundEmailRow.matched_batch_item_id.in_(item_ids))
                    .order_by(InboundEmailRow.received_at.asc())
                )
            ).scalars().all())

    observations_by_item: dict[str, list[LeadGenObservationRow]] = defaultdict(list)
    event_counts: Counter[str] = Counter()
    signal_counts: Counter[str] = Counter()
    reply_strength_counts: Counter[str] = Counter()
    for obs in observations:
        event_counts[obs.event_type] += 1
        if obs.batch_item_id:
            observations_by_item[obs.batch_item_id].append(obs)
        if obs.event_type in {"page_session", "link_clicked"}:
            signal_counts[f"{obs.event_type}:{signal_quality(obs.event_type, _as_dict(obs.raw_event_json))}"] += 1
        if obs.event_type in {"email_reply", "email_reply_received"}:
            raw = _as_dict(obs.raw_event_json)
            strength = _group_key(raw.get("attribution_strength"), "weak")
            reply_strength_counts[strength] += 1

    click_quality = Counter(signal_quality("link_clicked", user_agent=click.user_agent) for click in clicks)
    sent = sum(1 for item in items if _is_sent(item))
    bounced = sum(1 for item in items if item.outcome == "bounce")
    failed = event_counts.get("email_send_failed", 0)
    strong_replies = sum(reply_strength_counts[key] for key in ("strong", "medium"))
    weak_replies = sum(reply_strength_counts.values()) - strong_replies
    page_human = signal_counts.get("page_session:human", 0)
    page_suspect = signal_counts.get("page_session:suspect", 0)

    return {
        "batch_id": batch_id,
        "experiment": experiment_card_summary(batch),
        "measurement": {
            "planned": len(items),
            "approved": sum(1 for item in items if item.approval_status in {"approved", "started"}),
            "sent": sent,
            "send_failed": failed,
            "bounced": bounced + event_counts.get("email_bounce", 0),
            "raw_clicks": len(clicks),
            "scanner_clicks": click_quality.get("scanner", 0),
            "suspect_clicks": click_quality.get("suspect", 0),
            "unknown_clicks": click_quality.get("unknown", 0),
            "human_page_sessions": page_human,
            "suspect_page_sessions": page_suspect,
            "strong_human_replies": strong_replies,
            "weak_attributed_replies": weak_replies,
            "inbound_messages": len(inbound),
            "meetings": event_counts.get("consult_booked", 0),
        },
        "event_counts": dict(event_counts),
        "signal_quality": {
            "clicks": dict(click_quality),
            "observations": dict(signal_counts),
            "replies": dict(reply_strength_counts),
        },
        "groups": {
            "by_transport": _rollup_group(
                items,
                observations_by_item,
                lambda item: _group_key(_as_dict(item.reason_json).get("last_sent_transport"), "unsent"),
            ),
            "by_persona": _rollup_group(
                items,
                observations_by_item,
                lambda item: _group_key(item.persona, "unknown"),
            ),
            "by_variant": _rollup_group(
                items,
                observations_by_item,
                lambda item: _group_key(
                    _as_dict(item.reason_json).get("last_sent_composer_variant_key")
                    or _as_dict(item.reason_json).get("composer_variant_key"),
                    "baseline",
                ),
            ),
        },
        "data_quality": {
            "missing_card_fields": _card_missing_fields(_as_dict(batch.experiment_json)),
            "reply_metric_counts_only_strong_or_medium": True,
            "clicks_are_never_counted_as_human_without_page_or_reply_evidence": True,
        },
    }


async def list_experiment_batches(
    *,
    limit: int = 50,
    status: str | None = None,
) -> dict[str, Any]:
    limit = max(1, min(int(limit), 200))
    now = _utcnow()
    async with AsyncSessionLocal() as session:
        conditions = [
            or_(
                LeadGenBatchRow.experiment_status != "none",
                LeadGenBatchRow.name.ilike("%wave%"),
            )
        ]
        if status and status != "all":
            conditions.append(LeadGenBatchRow.experiment_status == status)
        batches = list((
            await session.execute(
                select(LeadGenBatchRow)
                .where(*conditions)
                .order_by(desc(LeadGenBatchRow.created_at))
                .limit(limit)
            )
        ).scalars().all())
        if batches:
            batch_ids = [batch.id for batch in batches]
            items = list((
                await session.execute(
                    select(LeadGenBatchItemRow).where(LeadGenBatchItemRow.batch_id.in_(batch_ids))
                )
            ).scalars().all())
            items_by_batch: dict[str, list[LeadGenBatchItemRow]] = defaultdict(list)
            for item in items:
                items_by_batch[item.batch_id].append(item)
            changed = False
            for batch in batches:
                changed = _sync_due_status(batch, items_by_batch.get(batch.id, []), now=now) or changed
            if changed:
                await session.commit()
                for batch in batches:
                    await session.refresh(batch)
    rows = []
    for batch in batches:
        rows.append({
            "batch_id": batch.id,
            "batch_name": batch.name,
            "batch_status": batch.status,
            "created_at": batch.created_at.isoformat() if batch.created_at else None,
            "approved_at": batch.approved_at.isoformat() if batch.approved_at else None,
            "experiment": experiment_card_summary(batch),
        })
    return {"experiments": rows}
