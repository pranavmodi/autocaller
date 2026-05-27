"""Recommend the next contacts to approve for a sequence batch."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.db.models import (
    CallLogRow,
    EmailLogRow,
    EmailSequenceRow,
    FirmContactRow,
    PatientRow,
    SmsLogRow,
)
from app.services.sequences.registry import normalize_template_key


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


def _pif_from_patient_id(patient_id: str | None) -> Optional[str]:
    if not patient_id:
        return None
    if patient_id.startswith("pif-"):
        return patient_id[4:]
    if patient_id.startswith("mc-"):
        return patient_id[3:]
    return None


def _persona_score(title: str | None, source: str | None) -> tuple[int, str]:
    t = (title or "").lower()
    if any(x in t for x in ("founder", "co-founder", "owner")):
        return 100, "founder/owner"
    if "chief operating" in t or "coo" in t:
        return 98, "COO"
    if "managing partner" in t or "principal" in t:
        return 94, "managing partner"
    if "operations" in t or "office manager" in t:
        return 88, "operations leader"
    if "partner" in t:
        return 82, "partner"
    if source == "patients_dm":
        return 70, "known decision-maker contact"
    return 0, ""


def _has_usable_email(email: str | None) -> bool:
    value = (email or "").strip().lower()
    if not value or value in {"null", "none", "n/a", "na"}:
        return False
    if "email protected" in value or "[email" in value:
        return False
    return "@" in value and "." in value.rsplit("@", 1)[-1]


def _looks_like_non_law_firm(firm_name: str, title: str | None) -> bool:
    """Suppress obvious non-law providers that share the same PIF contact table."""
    name = firm_name.lower()
    title_text = (title or "").lower()
    strong_non_law_markers = (
        "attorney service",
        "chiropractor",
        "chiropractic",
        "doctor of chiropractic",
        "lien services",
        "mri",
        "radiologist",
        "releasepoint",
        "synergy",
    )
    if any(marker in name or marker in title_text for marker in strong_non_law_markers):
        return True
    legal_markers = (
        "law",
        "legal",
        "attorney",
        "trial",
        "injury",
        "llp",
        "aplc",
        "plc",
        "p.c.",
        " pc",
    )
    if any(marker in name or marker in title_text for marker in legal_markers):
        return False
    non_law_markers = (
        "chiro",
        "clinic",
        "diagnostic",
        "financial",
        "health",
        "hospital",
        "imaging",
        "insurance",
        "medical",
        "radiology",
        "registry",
        "spine",
        "wellness",
    )
    return any(marker in name or marker in title_text for marker in non_law_markers)


async def recommend_sequence_contacts(
    *,
    template_key: str,
    limit: int = 50,
) -> dict:
    """Return one founder/COO-style contact per untouched firm.

    "Untouched" uses the same backing tables as the comms feed: call_logs,
    email_logs, and sms_logs. Any comms history suppresses the firm for v1.
    Existing sequence rows also suppress the firm so we do not multi-thread.
    """
    template_key = normalize_template_key(template_key)
    limit = max(1, min(limit, 200))
    async with AsyncSessionLocal() as session:
        email_pifs = {
            p for p in (await session.execute(
                select(EmailLogRow.pif_id).where(EmailLogRow.pif_id.isnot(None))
            )).scalars().all()
            if p
        }
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
        contacted_pifs = email_pifs | sms_pifs | call_pifs

        sequence_contact_ids = (await session.execute(
            select(EmailSequenceRow.contact_id)
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

    best_by_firm: dict[str, Recommendation] = {}
    counts = {
        "contacts_seen": len(contacts),
        "suppressed_contacted_firm": 0,
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
        if not _has_usable_email(c.email):
            counts["suppressed_unusable_email"] += 1
            continue
        if c.pif_id in contacted_pifs:
            counts["suppressed_contacted_firm"] += 1
            continue
        if c.pif_id in sequenced_pifs:
            counts["suppressed_existing_sequence"] += 1
            continue
        score, persona = _persona_score(c.title, c.source)
        if score <= 0:
            counts["suppressed_non_persona"] += 1
            continue
        firm_name = firm_names.get(c.pif_id, "")
        if not firm_name:
            counts["suppressed_missing_firm_name"] += 1
            continue
        if _looks_like_non_law_firm(firm_name, c.title):
            counts["suppressed_non_law_firm"] += 1
            continue
        if states.get(c.pif_id):
            score += 2
        if c.source == "pif_leadership":
            score += 3
        reason = f"{persona}; no comms history found; no existing sequence"
        rec = Recommendation(
            contact_id=c.id,
            pif_id=c.pif_id,
            firm_name=firm_name,
            contact_name=c.full_name,
            contact_email=c.email or "",
            contact_title=c.title or "",
            contact_source=c.source,
            persona=persona,
            score=score,
            reason=reason,
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
