"""Dynamic lead-gen email composer using a local SKILL.md."""
from __future__ import annotations

import json
import os
import re
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import desc, or_, select

from app.db import AsyncSessionLocal
from app.db.models import ConsultBookingRow, EmailSequenceRow, FirmContactRow, InboundEmailRow
from app.services.llm_gateway import LLMGatewayError, call_skill_json
from app.services.lead_email_composer_variants import (
    EXPERIMENT_KEY,
    choose_composer_skill_variant,
    get_composer_skill_variant,
)
from app.services.product_traces import safe_record_product_trace


DEFAULT_SKILL_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills/possible-minds-lead-email-composer/SKILL.md"
)
CONSULT_URL = "https://getpossibleminds.com/consult"
EMAIL_DASH_TRANSLATION = str.maketrans({"—": "-", "–": "-"})
ORG_NAME_WORDS = {
    "accident",
    "center",
    "centers",
    "clinic",
    "firm",
    "group",
    "imaging",
    "injury",
    "law",
    "legal",
    "medical",
    "office",
    "orthopedic",
    "spine",
}
GENERIC_CONTACT_NAMES = {"admin", "contact", "hello", "info", "intake", "office", "team"}


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
    composer_experiment_key: str
    composer_variant_key: str
    skill_path: str
    skill_sha256: str | None


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


def _conversation_state(
    *,
    reply_count: int,
    zoho_sent_count: int,
) -> dict[str, Any]:
    prior_outbound_count = zoho_sent_count
    return {
        "is_first_touch": prior_outbound_count == 0 and reply_count == 0,
        "prior_outbound_count": prior_outbound_count,
        "prior_reply_count": reply_count,
        "has_replies": reply_count > 0,
        "has_zoho_sent_history": zoho_sent_count > 0,
        "prior_outbound_source": "zoho_sent",
        "composer_goal": (
            "Compose the next appropriate email from the real conversation "
            "history and firm/contact context. Do not follow fixed template copy."
        ),
    }


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


def _sanitize_email_copy(value: str | None) -> str:
    text = (value or "").strip().translate(EMAIL_DASH_TRANSLATION)
    lines = []
    for line in text.splitlines():
        salutation = re.match(r"^(Hi|Hello|Hey)\s+(.+?)\s+-\s*$", line.strip(), re.IGNORECASE)
        if salutation:
            lines.append(f"{salutation.group(1)} {salutation.group(2)},")
        else:
            lines.append(line)
    return "\n".join(lines).strip()


def _sanitize_subject(value: str | None) -> str:
    subject = _sanitize_email_copy(value)
    precise_prefix = "quick question about precise imaging"
    if subject.lower().startswith(precise_prefix):
        cleaned = subject[len("Quick question about "):].strip()
        return cleaned[:1].upper() + cleaned[1:]
    return subject


def _file_sha256(path: str) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except Exception:
        return None


def _sequence_snapshot(sequence: Any, *, step_num: int) -> dict[str, Any]:
    return {
        "template_key": getattr(sequence, "template_key", None),
        "current_step": getattr(sequence, "current_step", None),
        "steps_total": getattr(sequence, "steps_total", None),
        "variant": getattr(sequence, "variant", None),
        "step_num": step_num,
    }


def _normalize_name(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _looks_like_org_name(value: str | None) -> bool:
    normalized = _normalize_name(value)
    return any(f" {word} " in f" {normalized} " for word in ORG_NAME_WORDS)


def _has_usable_person_name(contact: FirmContactRow, firm_name: str) -> bool:
    first_name = (contact.first_name or "").strip()
    full_name = (contact.full_name or "").strip()
    if not first_name:
        return False
    if _normalize_name(first_name) in GENERIC_CONTACT_NAMES:
        return False
    if _normalize_name(full_name) == _normalize_name(firm_name):
        return False
    if _looks_like_org_name(full_name):
        return False
    return True


def _sanitize_body_salutation(body: str, *, contact: FirmContactRow, firm_name: str) -> str:
    if _has_usable_person_name(contact, firm_name):
        return body
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        salutation = re.match(r"^(Hi|Hello|Hey)(?:\s+[^,!.]+)?[,!.]\s*$", line.strip(), re.IGNORECASE)
        if salutation:
            lines[index] = f"{salutation.group(1)},"
        break
    return "\n".join(lines).strip()


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
) -> dict[str, Any]:
    contact_domain = _domain(contact.email)
    zoho_sent_messages = []
    zoho_sent_lookup: dict[str, Any] = {"status": "not_attempted"}
    if contact.email:
        try:
            from app.services.inbound_email import fetch_zoho_sent_messages_for_recipient

            zoho_sent_messages = await fetch_zoho_sent_messages_for_recipient(
                contact.email,
                limit=int(os.getenv("LEAD_EMAIL_ZOHO_SENT_LIMIT", "5")),
                since_days=int(os.getenv("LEAD_EMAIL_ZOHO_SENT_SINCE_DAYS", "365")),
            )
            zoho_sent_lookup = {
                "status": "ok",
                "source": "zoho_imap_sent",
                "count": len(zoho_sent_messages),
            }
        except Exception as e:
            zoho_sent_lookup = {
                "status": "failed",
                "source": "zoho_imap_sent",
                "error": f"{type(e).__name__}: {str(e)[:160]}",
            }

    async with AsyncSessionLocal() as session:
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
        "history": {
            "previous_emails": [],
            "zoho_sent_emails": [
                {
                    "subject": msg.subject,
                    "to": msg.to,
                    "cc": msg.cc,
                    "excerpt": _excerpt(msg.body_text),
                    "sent_at": msg.received_at.isoformat() if msg.received_at else None,
                    "mailbox": msg.mailbox,
                    "uid": msg.uid,
                }
                for msg in zoho_sent_messages
            ],
            "zoho_sent_lookup": zoho_sent_lookup,
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
        "conversation_state": _conversation_state(
            reply_count=len(replies),
            zoho_sent_count=len(zoho_sent_messages),
        ),
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
    composer_variant_key: str | None = None,
    research_evidence: dict[str, Any] | None = None,
    selection_evidence: dict[str, Any] | None = None,
) -> LeadEmailComposition:
    payload = await build_lead_email_context(
        contact=contact,
        firm_name=firm_name,
    )
    if research_evidence:
        payload["research_evidence"] = research_evidence
    if selection_evidence:
        payload["selection_evidence"] = selection_evidence
    env_skill_path = os.getenv("LEAD_EMAIL_COMPOSER_SKILL_PATH", "").strip()
    if env_skill_path:
        skill_path = env_skill_path
        composer_experiment_key = "env_override"
        composer_variant_key = "env_override"
        skill_sha256 = _file_sha256(skill_path)
    else:
        selected_variant = (
            get_composer_skill_variant(composer_variant_key)
            if composer_variant_key
            else choose_composer_skill_variant(contact.id)
        )
        if composer_variant_key and selected_variant is None:
            raise LeadEmailComposerError(f"unknown composer variant: {composer_variant_key}")
        skill_path = selected_variant.skill_path
        composer_experiment_key = EXPERIMENT_KEY
        composer_variant_key = selected_variant.key
        skill_sha256 = selected_variant.skill_sha256
    selected_model = model or os.getenv("LEAD_EMAIL_COMPOSER_MODEL", "openclaw")
    trace_context = {
        "firm_name": firm_name,
        "contact_id": contact.id,
        "contact_email": contact.email,
        "contact_name": contact.full_name,
        "pif_id": contact.pif_id,
        "sequence": _sequence_snapshot(sequence, step_num=step_num),
        "research_evidence": research_evidence or {},
        "selection_evidence": selection_evidence or {},
        "skill_path": skill_path,
        "skill_sha256": skill_sha256,
        "composer_experiment_key": composer_experiment_key,
        "composer_variant_key": composer_variant_key,
        "model": selected_model,
    }
    await safe_record_product_trace(
        actor_type="system",
        event_type="email_context_built",
        surface="lead-gen",
        entity_type="firm_contact",
        entity_id=contact.id,
        input_json={
            "firm": payload.get("firm", {}),
            "contact": payload.get("contact", {}),
            "conversation_state": payload.get("conversation_state", {}),
            "policy": payload.get("policy", {}),
        },
        output_json=payload,
        context_json=trace_context,
    )
    try:
        result = await call_skill_json(
            skill_path=skill_path,
            payload=payload,
            required_fields=["subject", "body", "angle", "cta", "reasoning", "requires_human_review"],
            model=selected_model,
            max_tokens=int(os.getenv("LEAD_EMAIL_COMPOSER_MAX_TOKENS", "1800")),
        )
    except LLMGatewayError as e:
        await safe_record_product_trace(
            actor_type="system",
            event_type="email_composition_failed",
            surface="lead-gen",
            entity_type="firm_contact",
            entity_id=contact.id,
            input_json=payload,
            output_json={"error": str(e)},
            context_json=trace_context,
        )
        raise LeadEmailComposerError(str(e)) from e

    parsed = result.parsed
    _validate(parsed)
    body = _sanitize_email_copy(str(parsed.get("body") or ""))
    body = _sanitize_body_salutation(body, contact=contact, firm_name=firm_name)
    body = _ensure_consult_signature(body, payload["sender"])
    composition = LeadEmailComposition(
        subject=_sanitize_subject(str(parsed.get("subject") or ""))[:500],
        body=body,
        angle=str(parsed.get("angle") or "").strip(),
        cta=str(parsed.get("cta") or "").strip(),
        reasoning=str(parsed.get("reasoning") or "").strip(),
        risk_flags=[str(x) for x in (parsed.get("risk_flags") or []) if str(x).strip()],
        requires_human_review=bool(parsed.get("requires_human_review")),
        blog_link_used=(str(parsed.get("blog_link_used") or "").strip() or None),
        model=result.model,
        raw_response=result.raw_response,
        composer_experiment_key=composer_experiment_key,
        composer_variant_key=composer_variant_key,
        skill_path=skill_path,
        skill_sha256=skill_sha256,
    )
    await safe_record_product_trace(
        actor_type="system",
        event_type="email_composed",
        surface="lead-gen",
        entity_type="firm_contact",
        entity_id=contact.id,
        input_json=payload,
        output_json={
            "subject": composition.subject,
            "body": composition.body,
            "angle": composition.angle,
            "cta": composition.cta,
            "reasoning": composition.reasoning,
            "risk_flags": composition.risk_flags,
            "requires_human_review": composition.requires_human_review,
            "blog_link_used": composition.blog_link_used,
            "model": composition.model,
            "composer_experiment_key": composition.composer_experiment_key,
            "composer_variant_key": composition.composer_variant_key,
            "skill_path": composition.skill_path,
            "skill_sha256": composition.skill_sha256,
        },
        context_json=trace_context,
        metadata_json={"raw_response_excerpt": _excerpt(composition.raw_response, 1200)},
    )
    return composition
