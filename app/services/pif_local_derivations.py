"""Local behavior and ICP derivations for extracted PIF firms."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select

from app.db import AsyncSessionLocal
from app.db.models import FrontFirmActivityRow, PifFirmRow


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
