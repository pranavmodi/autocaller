"""Local behavior and ICP derivations for extracted PIF firms."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, func, select

from app.db import AsyncSessionLocal
from app.db.models import EmailLogRow, FrontFirmActivityRow, InboundEmailRow, PifFirmRow


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def analyze_behavior_locally(firm_id: str) -> dict[str, Any] | None:
    async with AsyncSessionLocal() as session:
        firm = await session.get(PifFirmRow, firm_id)
        if firm is None:
            return None
        activity = (await session.execute(
            select(FrontFirmActivityRow)
            .where(FrontFirmActivityRow.pif_id == firm_id)
            .order_by(desc(FrontFirmActivityRow.warm_score), desc(FrontFirmActivityRow.last_seen_at))
            .limit(1)
        )).scalar_one_or_none()
        behavior = dict(activity.behavioral_json) if activity and isinstance(activity.behavioral_json, dict) else {}
        behavior.update({
            "provider": "possibleos_local",
            "contact_count": activity.contact_count if activity else len(firm.contacts or []),
            "conversation_count": len(firm.conversation_ids or []),
            "last_seen_at": activity.last_seen_at.isoformat() if activity and activity.last_seen_at else None,
            "last_referral_at": activity.last_referral_at.isoformat() if activity and activity.last_referral_at else None,
            "last_records_at": activity.last_records_at.isoformat() if activity and activity.last_records_at else None,
            "inbox_breakdown": activity.inbox_breakdown if activity else {},
            "tech_signals": activity.tech_signals if activity else {},
            "warm_score": activity.warm_score if activity else 0,
            "analyzed_at": _utcnow().isoformat(),
        })
        firm.behavioral_data = behavior
        firm.warm_score = float(behavior["warm_score"] or 0)
        firm.updated_at = _utcnow()
        await session.commit()
        return behavior


async def score_firm_locally(firm_id: str) -> dict[str, Any] | None:
    async with AsyncSessionLocal() as session:
        firm = await session.get(PifFirmRow, firm_id)
        if firm is None:
            return None
        behavior = firm.behavioral_data if isinstance(firm.behavioral_data, dict) else {}
        components = {
            "pi_entity": 20 if firm.entity_type == "pi_law_firm" else 5,
            "canonical_website": 15 if firm.canonical_website else 0,
            "leadership": min(15, len(firm.leadership or []) * 5),
            "staff": min(15, len(firm.staff or [])),
            "vendor_evidence": 10 if firm.vendor_stack else 0,
            "relationship": min(15, int(float(behavior.get("warm_score") or firm.warm_score or 0) / 7)),
            "contactability": 10 if firm.emails else 5 if firm.phones else 0,
        }
        score = max(0, min(100, sum(components.values())))
        tier = "A" if score >= 75 else "B" if score >= 60 else "C" if score >= 40 else "D"
        now = _utcnow()
        firm.icp_score = score
        firm.icp_tier = tier
        firm.score_breakdown = {
            "provider": "possibleos_local",
            "components": components,
            "total": score,
            "scored_at": now.isoformat(),
        }
        firm.icp_scored_at = now
        firm.updated_at = now
        await session.commit()
        return {"id": firm.id, "icp_score": score, "icp_tier": tier, "score_breakdown": firm.score_breakdown}


def _email(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized or None


def _merge_profile(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    merged = dict(target)
    for key in ("name", "title", "phone", "extension", "linkedin", "source_url"):
        if source.get(key) and not merged.get(key):
            merged[key] = source[key]
    return merged


async def synthesize_contact_intelligence_locally(firm_id: str) -> dict[str, Any] | None:
    """Build the former EmailTag leadership-history/signature outputs locally.

    Possible OS does not copy PHI-bearing message bodies from EmailTag. It uses
    safe extracted contact fields plus local outbound/inbound communication
    metadata, preserving the useful operator view without recreating that data
    dependency.
    """
    async with AsyncSessionLocal() as session:
        firm = await session.get(PifFirmRow, firm_id)
        if firm is None:
            return None

        people: dict[str, dict[str, Any]] = {}
        for source_name, rows in (
            ("extracted_contact", firm.contacts or []),
            ("web_leadership", firm.leadership or []),
            ("web_staff", firm.staff or []),
        ):
            for raw in rows:
                if not isinstance(raw, dict):
                    continue
                email = _email(raw.get("email"))
                name = str(raw.get("name") or "").strip()
                key = email or (f"name:{name.lower()}" if name else "")
                if not key:
                    continue
                candidate = {
                    "name": name or None,
                    "title": str(raw.get("title") or "").strip() or None,
                    "email": email,
                    "phone": str(raw.get("phone") or "").strip() or None,
                    "extension": str(raw.get("extension") or "").strip() or None,
                    "linkedin": str(raw.get("linkedin") or "").strip() or None,
                    "source_url": str(raw.get("source_url") or "").strip() or None,
                    "sources": [source_name],
                }
                existing = people.get(key, {})
                merged = _merge_profile(existing, candidate)
                merged["email"] = email or existing.get("email")
                merged["sources"] = sorted(set([*(existing.get("sources") or []), source_name]))
                people[key] = merged

        email_keys = [key for key in people if "@" in key]
        outbound_rows = []
        inbound_rows = []
        if email_keys:
            outbound_rows = (await session.execute(
                select(
                    func.lower(EmailLogRow.recipient_email),
                    func.count(EmailLogRow.id),
                    func.max(EmailLogRow.sent_at),
                )
                .where(func.lower(EmailLogRow.recipient_email).in_(email_keys))
                .group_by(func.lower(EmailLogRow.recipient_email))
            )).all()
            inbound_rows = (await session.execute(
                select(
                    func.lower(InboundEmailRow.from_email),
                    func.count(InboundEmailRow.id),
                    func.max(InboundEmailRow.received_at),
                )
                .where(
                    InboundEmailRow.matched_pif_id == firm_id,
                    func.lower(InboundEmailRow.from_email).in_(email_keys),
                )
                .group_by(func.lower(InboundEmailRow.from_email))
            )).all()

        outbound = {str(email): (int(count), latest) for email, count, latest in outbound_rows}
        inbound = {str(email): (int(count), latest) for email, count, latest in inbound_rows}
        for key, profile in people.items():
            if "@" not in key:
                continue
            sent_count, last_sent = outbound.get(key, (0, None))
            received_count, last_received = inbound.get(key, (0, None))
            profile["communications"] = {
                "outbound_count": sent_count,
                "inbound_count": received_count,
                "last_outbound_at": last_sent.isoformat() if last_sent else None,
                "last_inbound_at": last_received.isoformat() if last_received else None,
            }

        leadership_history = []
        for leader in firm.leadership or []:
            if not isinstance(leader, dict):
                continue
            email = _email(leader.get("email"))
            profile = people.get(email or "", {})
            communications = profile.get("communications") or {}
            leadership_history.append({
                "name": leader.get("name"),
                "title": leader.get("title"),
                "email": email,
                **communications,
                "source": "possibleos_local_comms",
            })

        now = _utcnow()
        profiles = {
            key: {**value, "updated_at": now.isoformat()}
            for key, value in people.items()
        }
        behavior = dict(firm.behavioral_data) if isinstance(firm.behavioral_data, dict) else {}
        behavior["contact_profiles"] = profiles
        research = dict(firm.research_data) if isinstance(firm.research_data, dict) else {}
        research["leadership_email_history"] = leadership_history
        research["contact_intelligence_provider"] = "possibleos_local_comms"
        research["contact_intelligence_updated_at"] = now.isoformat()
        firm.contact_profiles = profiles
        firm.behavioral_data = behavior
        firm.research_data = research
        firm.updated_at = now
        await session.commit()
        return {
            "contact_profile_count": len(profiles),
            "leadership_history_count": len(leadership_history),
        }
