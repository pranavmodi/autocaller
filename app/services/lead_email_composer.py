"""Dynamic lead-gen email composer using a local SKILL.md."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import desc, or_, select

from app.db import AsyncSessionLocal
from app.db.models import ConsultBookingRow, EmailLogRow, EmailSequenceRow, FirmContactRow, InboundEmailRow
from app.services.llm_gateway import LLMGatewayError, call_skill_json
from app.services.sequences.possible_minds_dynamic import objective_for


DEFAULT_SKILL_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills/possible-minds-lead-email-composer/SKILL.md"
)
CONSULT_URL = "https://getpossibleminds.com/consult"


@dataclass
class LeadEmailComposition:
    subject: str
    body: str
    angle: str
    cta: str
    reasoning: str
    risk_flags: list[str]
    requires_human_review: bool
    blog_link_used: str | None
    model: str
    raw_response: str


class LeadEmailComposerError(RuntimeError):
    pass


def _domain(email: str | None) -> str:
    value = (email or "").strip().lower()
    if "@" not in value:
        return ""
    return value.rsplit("@", 1)[-1]


def _excerpt(value: str | None, limit: int = 700) -> str:
    text = " ".join((value or "").split())
    return text[:limit]


def _sender_payload() -> dict[str, str]:
    return {
        "name": os.getenv("SALES_REP_NAME", "").strip() or "Pranav",
        "title": os.getenv("SALES_REP_TITLE", "").strip() or "Founder",
        "company": "Possible Minds",
        "consult_url": CONSULT_URL,
    }


def _blog_posts() -> list[dict[str, str]]:
    raw = os.getenv("LEAD_GEN_BLOG_LINKS_JSON", "").strip()
    if not raw:
        raw = os.getenv("LEAD_GEN_BLOG_LINKS", "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        parsed = json.loads(raw)
        return [
            {"title": str(item.get("title") or ""), "url": str(item.get("url") or "")}
            for item in parsed
            if isinstance(item, dict) and item.get("url")
        ]
    return [{"title": "", "url": url.strip()} for url in raw.split(",") if url.strip()]


def _ensure_consult_signature(body: str, sender: dict[str, str]) -> str:
    body = (body or "").strip()
    if CONSULT_URL in body:
        return body
    name = sender.get("name") or "Pranav"
    title = sender.get("title") or "Founder"
    return f"{body}\n\n-- {name}\n{title}, Possible Minds\n{CONSULT_URL}".strip()


def _validate(parsed: dict[str, Any]) -> None:
    missing = [
        field for field in ("subject", "body", "angle", "cta", "reasoning", "requires_human_review")
        if field not in parsed
    ]
    if missing:
        raise LeadEmailComposerError(f"composer JSON missing fields: {missing}")
    body = str(parsed.get("body") or "")
    if CONSULT_URL not in body:
        return
    if "patient" in body.lower() and "front" in body.lower():
        raise LeadEmailComposerError("composer body appears to expose sensitive Front/patient context")


async def build_lead_email_context(
    *,
    contact: FirmContactRow,
    firm_name: str,
    sequence: EmailSequenceRow,
    step_num: int,
) -> dict[str, Any]:
    contact_domain = _domain(contact.email)
    async with AsyncSessionLocal() as session:
        previous_emails = (await session.execute(
            select(EmailLogRow)
            .where(
                or_(
                    EmailLogRow.pif_id == contact.pif_id,
                    EmailLogRow.recipient_email == (contact.email or "").strip().lower(),
                )
            )
            .order_by(desc(EmailLogRow.sent_at))
            .limit(8)
        )).scalars().all()
        replies = (await session.execute(
            select(InboundEmailRow)
            .where(
                or_(
                    InboundEmailRow.matched_contact_id == contact.id,
                    InboundEmailRow.matched_pif_id == contact.pif_id,
                    InboundEmailRow.from_email == (contact.email or "").strip().lower(),
                )
            )
            .order_by(desc(InboundEmailRow.received_at))
            .limit(8)
        )).scalars().all()
        consult_filters = []
        if contact_domain:
            consult_filters.append(ConsultBookingRow.email.ilike(f"%@{contact_domain}"))
        if firm_name:
            consult_filters.append(ConsultBookingRow.firm_name.ilike(f"%{firm_name}%"))
        consults = []
        if consult_filters:
            consults = (await session.execute(
                select(ConsultBookingRow)
                .where(or_(*consult_filters))
                .order_by(desc(ConsultBookingRow.created_at))
                .limit(5)
            )).scalars().all()
        recent_consults = (await session.execute(
            select(ConsultBookingRow)
            .order_by(desc(ConsultBookingRow.created_at))
            .limit(10)
        )).scalars().all()

    sender = _sender_payload()
    return {
        "firm": {
            "name": firm_name,
            "pif_id": contact.pif_id,
            "domain": contact_domain,
            "relationship_signals": [],
        },
        "contact": {
            "id": contact.id,
            "name": contact.full_name,
            "first_name": contact.first_name,
            "email": contact.email,
            "title": contact.title,
            "source": contact.source,
        },
        "sequence": {
            "template_key": sequence.template_key,
            "step_num": step_num,
            "current_step": sequence.current_step,
            "steps_total": sequence.steps_total,
            "objective": objective_for(step_num),
            "variant": sequence.variant,
        },
        "history": {
            "previous_emails": [
                {
                    "subject": row.subject,
                    "excerpt": _excerpt(row.body_excerpt),
                    "message_type": row.message_type,
                    "status": row.status,
                    "sent_at": row.sent_at.isoformat() if row.sent_at else None,
                }
                for row in previous_emails
            ],
            "replies": [
                {
                    "subject": row.subject,
                    "from_email": row.from_email,
                    "excerpt": _excerpt(row.text_excerpt or row.body_text),
                    "received_at": row.received_at.isoformat() if row.received_at else None,
                    "classification_status": row.classification_status,
                }
                for row in replies
            ],
            "booked_consults": [
                {
                    "firm_name": row.firm_name,
                    "email_domain": _domain(row.email),
                    "notes": _excerpt(row.notes, 300),
                    "status": row.status,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in consults
            ],
            "recent_booked_consult_patterns": [
                {
                    "firm_name": row.firm_name,
                    "email_domain": _domain(row.email),
                    "notes": _excerpt(row.notes, 220),
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in recent_consults
            ],
        },
        "front_signals": [],
        "inferred_pain_points": [],
        "blog_posts": _blog_posts(),
        "policy": {
            "target_metric": "booked_qualified_conversations",
            "hard_rules": [
                "Plaintext only",
                "Do not mention private Front message details",
                "Always include consult URL in signature",
                "Use at most one blog link",
            ],
        },
        "sender": sender,
    }


async def compose_lead_email(
    *,
    contact: FirmContactRow,
    firm_name: str,
    sequence: EmailSequenceRow,
    step_num: int,
    model: str | None = None,
) -> LeadEmailComposition:
    payload = await build_lead_email_context(
        contact=contact,
        firm_name=firm_name,
        sequence=sequence,
        step_num=step_num,
    )
    skill_path = os.getenv("LEAD_EMAIL_COMPOSER_SKILL_PATH", str(DEFAULT_SKILL_PATH))
    try:
        result = await call_skill_json(
            skill_path=skill_path,
            payload=payload,
            required_fields=["subject", "body", "angle", "cta", "reasoning", "requires_human_review"],
            model=model or os.getenv("LEAD_EMAIL_COMPOSER_MODEL", "openclaw"),
            max_tokens=int(os.getenv("LEAD_EMAIL_COMPOSER_MAX_TOKENS", "1800")),
        )
    except LLMGatewayError as e:
        raise LeadEmailComposerError(str(e)) from e

    parsed = result.parsed
    _validate(parsed)
    body = _ensure_consult_signature(str(parsed.get("body") or ""), payload["sender"])
    return LeadEmailComposition(
        subject=str(parsed.get("subject") or "").strip()[:500],
        body=body,
        angle=str(parsed.get("angle") or "").strip(),
        cta=str(parsed.get("cta") or "").strip(),
        reasoning=str(parsed.get("reasoning") or "").strip(),
        risk_flags=[str(x) for x in (parsed.get("risk_flags") or []) if str(x).strip()],
        requires_human_review=bool(parsed.get("requires_human_review")),
        blog_link_used=(str(parsed.get("blog_link_used") or "").strip() or None),
        model=result.model,
        raw_response=result.raw_response,
    )
