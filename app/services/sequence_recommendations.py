"""Recommend the next contacts to approve for a sequence batch."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import desc, func, select

from app.db import AsyncSessionLocal
from app.db.models import (
    CallLogRow,
    EmailLogRow,
    EmailSequenceRow,
    FirmContactRow,
    FrontFirmActivityRow,
    LeadGenBatchItemRow,
    LeadGenBatchRow,
    LeadGenObservationRow,
    LeadGenPolicyVersionRow,
    PatientRow,
    SmsLogRow,
)

# Fresh-selection firm cooldown: any firm with a successful lead-gen email or
# a batch item created inside this window is excluded from new first-touch
# selection. Follow-ups are owned by sequences/actions, never fresh selection.
EMAIL_FIRM_COOLDOWN_DAYS = 14
from app.services.contact_selection import (
    ContactSelectionInput,
    DEFAULT_CONTACT_SELECTION_WEIGHTS,
    has_usable_email,
    is_target_lead_persona,
    looks_like_non_law_firm,
    score_contact_selection,
)
from app.services.sequences.registry import normalize_template_key
from app.services.sequences.registry import DEFAULT_TEMPLATE_KEY


@dataclass
class Recommendation:
    contact_id: str
    pif_id: str
    firm_name: str
    contact_name: str
    contact_email: str
    contact_title: str
    contact_source: str
    persona: str
    score: int
    reason: str
    score_breakdown: dict[str, int] | None = None
    selection_features: dict[str, Any] | None = None
    selection_signals: list[str] | None = None
    suppressions: list[str] | None = None
    policy_version: str = "contact-selection-default"


def _pif_from_patient_id(patient_id: str | None) -> Optional[str]:
    if not patient_id:
        return None
    if patient_id.startswith("pif-"):
        return patient_id[4:]
    if patient_id.startswith("mc-"):
        return patient_id[3:]
    return None


_has_usable_email = has_usable_email
_is_target_lead_persona = is_target_lead_persona
_looks_like_non_law_firm = looks_like_non_law_firm


async def _active_policy_context(session) -> tuple[str, dict[str, Any]]:
    row = (await session.execute(
        select(LeadGenPolicyVersionRow)
        .where(LeadGenPolicyVersionRow.active.is_(True))
        .order_by(desc(LeadGenPolicyVersionRow.created_at))
    )).scalars().first()
    if not row:
        return "contact-selection-default", DEFAULT_CONTACT_SELECTION_WEIGHTS
    return row.version, row.weights_json or {}


async def recommend_sequence_contacts(
    *,
    template_key: str,
    limit: int = 50,
) -> dict:
    """Return one founder/COO-style contact per untouched firm.

    Prior-email handling (two distinct concerns):
    - Composition still treats Zoho Sent as the authoritative narrative of
      previous outbound email (what the draft may claim about prior contact).
    - Selection additionally suppresses on our own send/batch records, which
      are reliable for "we touched this firm/contact recently" even when a
      send later bounced: contacts that ever received a sent email or sat in
      any batch are excluded; firms with a sent email or batch item inside
      EMAIL_FIRM_COOLDOWN_DAYS are excluded; firms emailed longer ago stay
      selectable for a *different* contact with has_prior_comms=True.
    Existing sequence rows and call/SMS history still suppress the firm.
    """
    template_key = normalize_template_key(template_key)
    limit = max(1, min(limit, 200))
    async with AsyncSessionLocal() as session:
        policy_version, policy_weights = await _active_policy_context(session)
        sms_pifs = {
            p for p in (await session.execute(
                select(SmsLogRow.pif_id).where(SmsLogRow.pif_id.isnot(None))
            )).scalars().all()
            if p
        }
        call_pifs = {
            p for p in (
                _pif_from_patient_id(pid)
                for pid in (await session.execute(
                    select(CallLogRow.patient_id)
                )).scalars().all()
            )
            if p
        }
        contacted_pifs = sms_pifs | call_pifs

        cooldown_cutoff = datetime.now(timezone.utc) - timedelta(days=EMAIL_FIRM_COOLDOWN_DAYS)
        emailed_contact_emails = {
            e.lower() for e in (await session.execute(
                select(EmailLogRow.recipient_email).where(
                    EmailLogRow.status == "sent",
                    EmailLogRow.recipient_email.isnot(None),
                )
            )).scalars().all()
            if e
        }
        emailed_pifs_all = {
            p for p in (await session.execute(
                select(EmailLogRow.pif_id).where(
                    EmailLogRow.status == "sent",
                    EmailLogRow.pif_id.isnot(None),
                )
            )).scalars().all()
            if p
        }
        recent_emailed_pifs = {
            p for p in (await session.execute(
                select(EmailLogRow.pif_id).where(
                    EmailLogRow.status == "sent",
                    EmailLogRow.pif_id.isnot(None),
                    EmailLogRow.sent_at >= cooldown_cutoff,
                )
            )).scalars().all()
            if p
        }
        batch_contact_ids = {
            c for c in (await session.execute(
                select(LeadGenBatchItemRow.contact_id)
            )).scalars().all()
            if c
        }
        recent_batch_pifs = {
            p for p in (await session.execute(
                select(LeadGenBatchItemRow.pif_id)
                .join(LeadGenBatchRow, LeadGenBatchRow.id == LeadGenBatchItemRow.batch_id)
                .where(LeadGenBatchRow.created_at >= cooldown_cutoff)
            )).scalars().all()
            if p
        }
        recent_email_pifs = recent_emailed_pifs | recent_batch_pifs

        # Firms that explicitly declined never re-enter fresh selection.
        declined_pifs = {
            p for p in (await session.execute(
                select(LeadGenObservationRow.pif_id).where(
                    LeadGenObservationRow.classified_outcome.in_(
                        ["declined", "negative_reply", "do_not_contact", "unsubscribe"]
                    ),
                    LeadGenObservationRow.pif_id.isnot(None),
                )
            )).scalars().all()
            if p
        }

        sequence_contact_ids = (await session.execute(
            select(EmailSequenceRow.contact_id).where(
                EmailSequenceRow.template_key == DEFAULT_TEMPLATE_KEY,
            )
        )).scalars().all()
        sequenced_pifs: set[str] = set()
        if sequence_contact_ids:
            sequenced_pifs = {
                p for p in (await session.execute(
                    select(FirmContactRow.pif_id).where(
                        FirmContactRow.id.in_(sequence_contact_ids)
                    )
                )).scalars().all()
                if p
            }

        contacts = (await session.execute(
            select(FirmContactRow).where(
                FirmContactRow.email.isnot(None),
                FirmContactRow.email != "",
            )
        )).scalars().all()

        pif_ids = {c.pif_id for c in contacts if c.pif_id}
        patient_keys = [f"pif-{p}" for p in pif_ids] + [f"mc-{p}" for p in pif_ids]
        patient_rows = (await session.execute(
            select(PatientRow.patient_id, PatientRow.firm_name, PatientRow.state)
            .where(PatientRow.patient_id.in_(patient_keys))
        )).all()
        front_warm_rows = (await session.execute(
            select(FrontFirmActivityRow.pif_id, FrontFirmActivityRow.warm_score)
            .where(FrontFirmActivityRow.pif_id.in_(pif_ids))
        )).all()

    firm_names: dict[str, str] = {}
    states: dict[str, str] = {}
    for patient_id, firm_name, state in patient_rows:
        pif_id = _pif_from_patient_id(patient_id)
        if not pif_id:
            continue
        if firm_name and (pif_id not in firm_names or patient_id.startswith("pif-")):
            firm_names[pif_id] = firm_name
        if state and pif_id not in states:
            states[pif_id] = state
    front_warm_scores = {
        str(pif_id): int(warm_score or 0)
        for pif_id, warm_score in front_warm_rows
        if pif_id
    }

    best_by_firm: dict[str, Recommendation] = {}
    counts = {
        "contacts_seen": len(contacts),
        "suppressed_contacted_firm": 0,
        "suppressed_prior_email_contact": 0,
        "suppressed_recent_email_firm": 0,
        "suppressed_declined_firm": 0,
        "suppressed_existing_sequence": 0,
        "suppressed_unusable_email": 0,
        "suppressed_non_law_firm": 0,
        "suppressed_non_persona": 0,
        "suppressed_missing_firm_name": 0,
        "suppressed_duplicate_email": 0,
    }
    for c in contacts:
        if not c.pif_id:
            continue
        if not has_usable_email(c.email):
            counts["suppressed_unusable_email"] += 1
            continue
        if c.pif_id in contacted_pifs:
            counts["suppressed_contacted_firm"] += 1
            continue
        if c.id in batch_contact_ids or (c.email or "").lower() in emailed_contact_emails:
            counts["suppressed_prior_email_contact"] += 1
            continue
        if c.pif_id in declined_pifs:
            counts["suppressed_declined_firm"] += 1
            continue
        if c.pif_id in recent_email_pifs:
            counts["suppressed_recent_email_firm"] += 1
            continue
        if c.pif_id in sequenced_pifs:
            counts["suppressed_existing_sequence"] += 1
            continue
        firm_name = firm_names.get(c.pif_id, "")
        if not firm_name:
            counts["suppressed_missing_firm_name"] += 1
            continue
        if looks_like_non_law_firm(firm_name, c.title):
            counts["suppressed_non_law_firm"] += 1
            continue
        if not is_target_lead_persona(c.title, c.source):
            counts["suppressed_non_persona"] += 1
            continue
        scored = score_contact_selection(
            ContactSelectionInput(
                contact_id=c.id,
                pif_id=c.pif_id,
                firm_name=firm_name,
                contact_name=c.full_name,
                contact_email=c.email or "",
                contact_title=c.title or "",
                contact_source=c.source or "",
                state=states.get(c.pif_id),
                has_prior_comms=c.pif_id in emailed_pifs_all,
                has_existing_sequence=False,
                front_warm_score=front_warm_scores.get(c.pif_id, 0),
            ),
            policy_weights=policy_weights,
        )
        if "missing_persona" in scored.suppressions or scored.score <= 0:
            counts["suppressed_non_persona"] += 1
            continue
        reason = scored.reason
        rec = Recommendation(
            contact_id=c.id,
            pif_id=c.pif_id,
            firm_name=firm_name,
            contact_name=c.full_name,
            contact_email=c.email or "",
            contact_title=c.title or "",
            contact_source=c.source,
            persona=scored.persona,
            score=scored.score,
            reason=reason,
            score_breakdown=scored.score_breakdown,
            selection_features=scored.features,
            selection_signals=scored.signals,
            suppressions=scored.suppressions,
            policy_version=policy_version,
        )
        current = best_by_firm.get(c.pif_id)
        if not current or rec.score > current.score:
            best_by_firm[c.pif_id] = rec

    candidates = sorted(
        best_by_firm.values(),
        key=lambda r: (-r.score, r.firm_name.lower(), r.contact_name.lower()),
    )
    recommended: list[Recommendation] = []
    used_emails: set[str] = set()
    for candidate in candidates:
        email_key = candidate.contact_email.strip().lower()
        if email_key in used_emails:
            counts["suppressed_duplicate_email"] += 1
            continue
        used_emails.add(email_key)
        recommended.append(candidate)
        if len(recommended) >= limit:
            break
    return {
        "template_key": template_key,
        "limit": limit,
        "recommended": [r.__dict__ for r in recommended],
        "counts": counts | {
            "contacted_firms": len(contacted_pifs),
            "sequenced_firms": len(sequenced_pifs),
            "eligible_firms": len(best_by_firm),
            "returned": len(recommended),
        },
    }
