"""Operator-curated lead-gen batch helpers."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from app.db import AsyncSessionLocal
from app.db.models import (
    FirmContactRow,
    LeadGenBatchItemRow,
    LeadGenBatchRow,
    PatientRow,
    PifFirmRow,
)
from app.services.lead_gen_cybernetic import ensure_default_policy
from app.services.sequences.registry import DEFAULT_TEMPLATE_KEY, normalize_template_key


def _new_id() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _batch_to_dict(batch: LeadGenBatchRow) -> dict[str, Any]:
    return {
        "id": batch.id,
        "name": batch.name,
        "target_metric": batch.target_metric,
        "template_key": batch.template_key,
        "policy_version": batch.policy_version,
        "status": batch.status,
        "counts": batch.counts_json or {},
        "created_by": batch.created_by,
        "approved_by": batch.approved_by,
        "approved_at": batch.approved_at.isoformat() if batch.approved_at else None,
        "started_at": batch.started_at.isoformat() if batch.started_at else None,
        "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "updated_at": batch.updated_at.isoformat() if batch.updated_at else None,
    }


async def _load_batch_or_raise(session, batch_id: str) -> LeadGenBatchRow:
    batch = await session.get(LeadGenBatchRow, batch_id)
    if not batch:
        raise ValueError("batch_not_found")
    return batch


async def _resolve_contact(session, ref: str) -> FirmContactRow | None:
    clean_ref = str(ref or "").strip()
    if not clean_ref:
        return None
    contact = await session.get(FirmContactRow, clean_ref)
    if contact:
        return contact
    email = clean_ref.lower()
    if "@" not in email:
        return None
    return (await session.execute(
        select(FirmContactRow)
        .where(func.lower(FirmContactRow.email) == email)
        .order_by(FirmContactRow.updated_at.desc())
        .limit(1)
    )).scalar_one_or_none()


async def _existing_contact_ids(session, batch_id: str) -> set[str]:
    rows = (await session.execute(
        select(LeadGenBatchItemRow.contact_id)
        .where(LeadGenBatchItemRow.batch_id == batch_id)
    )).scalars().all()
    return {str(row) for row in rows if row}


async def _live_item_count(session, batch_id: str) -> int:
    count = (await session.execute(
        select(func.count(LeadGenBatchItemRow.id))
        .where(LeadGenBatchItemRow.batch_id == batch_id)
    )).scalar_one()
    return int(count or 0)


async def _firm_name_for_contact(session, contact: FirmContactRow) -> str:
    pif_id = str(contact.pif_id or "").strip()
    if not pif_id:
        return ""
    native_name = (await session.execute(
        select(PifFirmRow.firm_name)
        .where(PifFirmRow.id == pif_id)
        .limit(1)
    )).scalar_one_or_none()
    if native_name:
        return str(native_name)
    rows = (await session.execute(
        select(PatientRow.patient_id, PatientRow.firm_name).where(
            PatientRow.patient_id.in_([f"pif-{pif_id}", f"mc-{pif_id}"])
        )
    )).all()
    fallback: dict[str, str] = {}
    for patient_id, firm_name in rows:
        if firm_name:
            fallback[str(patient_id)] = str(firm_name)
    return fallback.get(f"pif-{pif_id}") or fallback.get(f"mc-{pif_id}") or pif_id


def _repair_counts(batch: LeadGenBatchRow, live_count: int) -> dict[str, Any]:
    counts = dict(batch.counts_json or {})
    counts["returned"] = live_count
    counts["requested"] = live_count
    batch.counts_json = counts
    batch.updated_at = _utcnow()
    return counts


async def create_curated_batch(
    name: str,
    template_key: str = DEFAULT_TEMPLATE_KEY,
    target_metric: str = "meetings_booked",
    created_by: str = "operator",
    status: str = "approved",
) -> dict[str, Any]:
    """Create an empty operator-curated lead-gen batch."""
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("name_required")
    template_key = normalize_template_key(template_key)
    policy = await ensure_default_policy()
    batch = LeadGenBatchRow(
        id=_new_id(),
        name=clean_name,
        target_metric=str(target_metric or "meetings_booked").strip() or "meetings_booked",
        template_key=template_key,
        policy_version=policy.version,
        status=status,
        counts_json={
            "basis": "operator-curated",
            "returned": 0,
            "requested": 0,
        },
        created_by=str(created_by or "operator").strip() or "operator",
    )
    async with AsyncSessionLocal() as session:
        session.add(batch)
        await session.commit()
    return _batch_to_dict(batch)


async def add_contacts_to_batch(
    batch_id: str,
    contact_refs: list[str],
    actor: str = "operator",
) -> dict[str, Any]:
    """Add resolvable contacts to an operator-curated batch idempotently."""
    clean_refs = [str(ref).strip() for ref in contact_refs if str(ref or "").strip()]
    item_ids: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []

    async with AsyncSessionLocal() as session:
        batch = await _load_batch_or_raise(session, batch_id)
        existing_ids = await _existing_contact_ids(session, batch_id)

        for ref in clean_refs:
            contact = await _resolve_contact(session, ref)
            if not contact or not contact.id:
                skipped.append({"ref": ref, "reason": "unresolved"})
                continue
            if not str(contact.email or "").strip():
                skipped.append({
                    "ref": ref,
                    "reason": "missing_email",
                    "contact_id": str(contact.id),
                })
                continue
            if str(contact.id) in existing_ids:
                skipped.append({
                    "ref": ref,
                    "reason": "already_in_batch",
                    "contact_id": str(contact.id),
                    "contact_email": contact.email or "",
                })
                continue

            firm_name = await _firm_name_for_contact(session, contact)
            item = LeadGenBatchItemRow(
                id=_new_id(),
                batch_id=batch.id,
                contact_id=contact.id,
                pif_id=contact.pif_id,
                firm_name=firm_name or contact.pif_id,
                contact_name=contact.full_name or "",
                contact_email=contact.email or "",
                contact_title=contact.title or "",
                persona=contact.persona or "",
                template_key=batch.template_key,
                score=0,
                reason_json={
                    "source": "operator-curated",
                    "actor": str(actor or "operator").strip() or "operator",
                },
                approval_status="pending",
            )
            session.add(item)
            existing_ids.add(str(contact.id))
            item_ids.append({
                "contact_email": item.contact_email,
                "item_id": item.id,
            })

        await session.flush()
        live_count = await _live_item_count(session, batch.id)
        counts = _repair_counts(batch, live_count)
        await session.commit()

    return {
        "batch_id": batch_id,
        "added": len(item_ids),
        "skipped": skipped,
        "item_ids": item_ids,
        "counts": counts,
    }


async def recount_batch(batch_id: str) -> dict[str, Any]:
    """Repair a batch's counts_json from the live item count."""
    async with AsyncSessionLocal() as session:
        batch = await _load_batch_or_raise(session, batch_id)
        live_count = await _live_item_count(session, batch_id)
        counts = _repair_counts(batch, live_count)
        await session.commit()
    return {
        "batch_id": batch_id,
        "counts": counts,
        "returned": live_count,
        "requested": live_count,
    }
