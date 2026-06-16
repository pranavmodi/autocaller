"""Dynamic lead-gen email composer using a local SKILL.md."""
from __future__ import annotations

import json
import logging
import os
import re
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import desc, or_, select

from app.db import AsyncSessionLocal
from app.db.models import ConsultBookingRow, EmailSequenceRow, FirmContactRow, FrontFirmActivityRow, InboundEmailRow, PatientRow, PifFirmRow
from app.services.llm_gateway import LLMGatewayError, call_skill_json

logger = logging.getLogger(__name__)
from app.services.lead_email_composer_variants import (
    EXPERIMENT_KEY,
    choose_composer_skill_variant,
    get_composer_skill_variant,
)
from app.services.listening_client import ListeningClient, ListeningClientError
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
    brief_version: int | None = None


class LeadEmailComposerError(RuntimeError):
    pass


def _domain(email: str | None) -> str:
    value = (email or "").strip().lower()
    if "@" not in value:
        return ""
    return value.rsplit("@", 1)[-1]


def _normalize_competitor_key(name: str | None, domain: str | None) -> str:
    clean_domain = (domain or "").strip().lower()
    if clean_domain:
        return f"domain:{clean_domain}"
    return "name:" + re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def _competitor_confidence(row: dict[str, Any]) -> str:
    score = float(row.get("score") or 0)
    components = row.get("components") if isinstance(row.get("components"), dict) else {}
    if score >= 0.75 and (
        float(components.get("case_mix") or 0) > 0
        or float(components.get("value_tier") or 0) > 0
        or float(components.get("client_switching") or 0) > 0
    ):
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


async def _get_competitors_for_context(**kwargs) -> dict[str, Any]:
    from app.services.competitor_graph import get_competitors

    return await get_competitors(**kwargs)


def _is_competitor_candidate_for_context(firm_name: str | None, domain: str | None) -> bool:
    from app.services.competitor_graph import is_competitor_candidate_name_domain

    return is_competitor_candidate_name_domain(firm_name, domain)


def _clean_competitor_rows(
    rows: list[dict[str, Any]],
    *,
    target_pif_id: str | None,
    target_name: str,
    limit: int,
) -> list[dict[str, Any]]:
    target_key = _normalize_name(target_name)
    seen: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: (-float(item.get("score") or 0), str(item.get("firm_name") or ""))):
        firm_name = str(row.get("firm_name") or "").strip()
        domain = (str(row.get("domain") or "").strip().lower() or None)
        pif_id = str(row.get("pif_id") or "").strip()
        if not firm_name:
            continue
        if target_pif_id and pif_id == target_pif_id:
            continue
        if _normalize_name(firm_name) == target_key:
            continue
        if not _is_competitor_candidate_for_context(firm_name, domain):
            continue
        key = _normalize_competitor_key(firm_name, domain)
        if not key or key in seen:
            continue
        seen.add(key)
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        components = row.get("components") if isinstance(row.get("components"), dict) else {}
        cleaned.append({
            "firm_name": firm_name,
            "domain": domain,
            "pif_id": pif_id or None,
            "metro": row.get("metro"),
            "score": round(float(row.get("score") or 0), 4),
            "confidence": _competitor_confidence(row),
            "why": str(evidence.get("why") or "").strip(),
            "signals": {
                "geo": components.get("geo"),
                "case_mix": components.get("case_mix"),
                "value_tier": components.get("value_tier"),
                "shared_front_activity": components.get("shared_orbit"),
                "client_switching": components.get("client_switching"),
            },
        })
        if len(cleaned) >= limit:
            break
    return cleaned


async def fetch_competitive_context_for_email(
    *,
    contact: FirmContactRow,
    firm_name: str,
    limit: int | None = None,
) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit or os.getenv("LEAD_EMAIL_COMPETITOR_LIMIT", "8")), 12))
    if not contact.pif_id and not _domain(contact.email):
        return {
            "status": "unavailable",
            "source": "local_competitor_graph",
            "reason": "missing_pif_id_or_domain",
            "competitors": [],
            "usage_guidance": "No competitor context available; do not infer or name competitors.",
        }
    try:
        data = await _get_competitors_for_context(
            pif_id=contact.pif_id or "",
            domain=_domain(contact.email),
            limit=max(safe_limit * 2, 10),
        )
    except Exception as e:
        logger.warning("competitor context lookup failed for %s: %s", contact.pif_id or firm_name, e)
        return {
            "status": "unavailable",
            "source": "local_competitor_graph",
            "reason": f"{type(e).__name__}: {str(e)[:160]}",
            "competitors": [],
            "usage_guidance": "Competitor lookup failed; do not infer or name competitors.",
        }

    firm = data.get("firm") if isinstance(data.get("firm"), dict) else None
    rows = data.get("competitors") if isinstance(data.get("competitors"), list) else []
    competitors = _clean_competitor_rows(
        [row for row in rows if isinstance(row, dict)],
        target_pif_id=contact.pif_id,
        target_name=firm_name,
        limit=safe_limit,
    )
    status = "ok" if competitors else "not_found"
    return {
        "status": status,
        "source": "local_competitor_graph",
        "target": {
            "firm_name": firm.get("firm_name") if firm else firm_name,
            "domain": firm.get("domain") if firm else _domain(contact.email),
            "pif_id": firm.get("pif_id") if firm else contact.pif_id,
            "metro": firm.get("metro") if firm else None,
        },
        "competitors": competitors,
        "limit": safe_limit,
        "usage_guidance": (
            "Use as private market context to choose angle and urgency. "
            "Do not name competitors in outbound copy unless the payload gives explicit permission."
        ),
    }


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
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            # Optional config: a malformed LEAD_GEN_BLOG_LINKS_JSON (e.g. a
            # JSON value mangled by `source .env` word-splitting) must never
            # break composition. Degrade to no blog links.
            logger.warning("LEAD_GEN_BLOG_LINKS_JSON is not valid JSON; ignoring blog links")
            return []
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


def _brief_markdown(data: dict[str, Any]) -> str:
    return str(data.get("brief_md") or data.get("markdown") or data.get("body") or "")


def _brief_version(data: dict[str, Any]) -> int | None:
    try:
        return int(data.get("version"))
    except (TypeError, ValueError):
        return None


def _insight_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = data.get("insights")
    if rows is None:
        rows = data.get("items")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    return []


def _listening_query_terms(
    *,
    firm_name: str,
    contact: FirmContactRow,
    patient: PatientRow | None,
) -> str:
    parts = [
        firm_name,
        getattr(contact, "title", None),
        getattr(patient, "practice_area", None) if patient else None,
        getattr(patient, "notes", None) if patient else None,
    ]
    if patient and isinstance(patient.tags, list):
        parts.extend(str(tag) for tag in patient.tags[:8])
    text = " ".join(str(part or "") for part in parts)
    tokens = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower()):
        if token in {
            "firm", "law", "legal", "group", "office", "offices", "the",
            "and", "for", "with", "attorney", "attorneys",
        }:
            continue
        tokens.append(token.replace("_", "-"))
    if not tokens:
        return "personal injury intake operations"
    deduped = list(dict.fromkeys(tokens))
    return " ".join(deduped[:8])


async def fetch_listening_context_for_email(
    *,
    contact: FirmContactRow,
    firm_name: str,
    limit: int = 5,
) -> dict[str, Any]:
    """Fetch the latest mindset brief + matched insights for composer context.

    Soft-fails by design: lead-gen composition must proceed when Mission
    Control is down.
    """
    patient: PatientRow | None = None
    async with AsyncSessionLocal() as session:
        possible_ids = []
        if contact.pif_id:
            possible_ids.extend([f"pif-{contact.pif_id}", f"mc-{contact.pif_id}"])
        if possible_ids:
            patient = (await session.execute(
                select(PatientRow).where(PatientRow.patient_id.in_(possible_ids)).limit(1)
            )).scalar_one_or_none()
        if patient is None and firm_name:
            patient = (await session.execute(
                select(PatientRow)
                .where(PatientRow.firm_name.ilike(f"%{firm_name}%"))
                .limit(1)
            )).scalar_one_or_none()

    query = _listening_query_terms(firm_name=firm_name, contact=contact, patient=patient)
    client = ListeningClient()
    try:
        brief_data = await client.brief()
        insights_data = await client.insights(q=query, limit=limit)
    except ListeningClientError as e:
        return {
            "available": False,
            "brief_version": None,
            "query": query,
            "error": str(e)[:300],
            "insights": [],
        }

    brief_md = _brief_markdown(brief_data)
    insights = _insight_rows(insights_data)[:limit]
    return {
        "available": True,
        "brief_version": _brief_version(brief_data),
        "brief_created_at": brief_data.get("created_at"),
        "query": query,
        "brief_excerpt": _excerpt(brief_md, 1800),
        "insights": [
            {
                "type": row.get("type"),
                "cluster": row.get("cluster"),
                "who_feels_it": row.get("who_feels_it"),
                "severity": row.get("severity"),
                "quote": row.get("quote"),
                "paraphrase": row.get("paraphrase"),
                "source_name": row.get("source_name"),
                "source_kind": row.get("source_kind"),
                "url": row.get("url"),
            }
            for row in insights
        ],
    }


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


# P1: map the firm's observed email sender-role mix to concrete operational pains.
# These are the personas that actually email Precise from the firm; the volume is
# evidence of where the firm's operational drag sits. founder_owner / unknown are
# not pains.
_ROLE_PAIN: dict[str, tuple[str, str]] = {
    "records": ("records_status_followup", "records and bills chase, status reconstruction across portals and faxes"),
    "lien_settlement": ("liens_ar_negotiation", "lien reduction cycles, disbursement delays, and provider follow-up"),
    "case_manager": ("client_status_case_velocity", "client status updates and case velocity, fewer 'any update?' loops"),
    "intake": ("intake_after_hours", "after-hours and overflow intake, speed-to-lead, missed calls"),
    "coo_ops": ("ops_queue_visibility", "queue visibility, handoffs, exception-only workflows, staff workload"),
    "paralegal": ("file_status_followup", "file status and document follow-up"),
    "attorney": ("litigation_status_followup", "records, bills, and status follow-up on every file"),
    "marketing": ("lead_response_conversion", "lead response time, conversion leakage, attribution"),
}


def _derive_pif_signals(pif_row: PifFirmRow | None, contact_email: str | None) -> dict[str, Any]:
    """Turn the emailtag-extracted firm record into composer inputs:
    P1 behavioral pains + firm_behavior, P2 leadership bio/linkedin, P4 ICP/size."""
    empty = {
        "inferred_pain_points": [],
        "firm_behavior": {},
        "firm_meta": {},
        "contact_bio": None,
        "contact_linkedin": None,
    }
    if pif_row is None:
        return empty

    bd = pif_row.behavioral_data if isinstance(pif_row.behavioral_data, dict) else {}
    sender_roles = bd.get("sender_roles") if isinstance(bd.get("sender_roles"), dict) else {}
    ranked = sorted(
        (
            (str(r), int(c))
            for r, c in sender_roles.items()
            if r not in {"unknown", "founder_owner"} and isinstance(c, (int, float)) and c > 0
        ),
        key=lambda x: -x[1],
    )
    pains: list[dict[str, Any]] = []
    for role, count in ranked[:3]:
        m = _ROLE_PAIN.get(role)
        if not m:
            continue
        key, desc = m
        pains.append({"pain": key, "description": desc, "signal": f"{count} {role} emails observed", "weight": count})

    # P1: after-hours intake signal, weighted by message volume across contacts.
    profiles = bd.get("contact_profiles") if isinstance(bd.get("contact_profiles"), dict) else {}
    if not profiles and isinstance(pif_row.contact_profiles, dict):
        profiles = pif_row.contact_profiles
    num = den = 0.0
    topics: dict[str, int] = {}
    for prof in profiles.values():
        if not isinstance(prof, dict):
            continue
        mc = float(prof.get("message_count") or 0)
        ahr = prof.get("after_hours_ratio")
        if ahr is not None and mc > 0:
            num += mc * float(ahr)
            den += mc
        for t, c in (prof.get("topic_mix") or {}).items():
            topics[str(t)] = topics.get(str(t), 0) + int(c or 0)
    after_hours = round(num / den, 2) if den else None
    if after_hours is not None and after_hours >= 0.25:
        pains.insert(0, {
            "pain": "after_hours_intake",
            "description": "a meaningful share of inbound arrives after hours, so leads and requests sit until morning",
            "signal": f"after-hours email ratio {after_hours}",
            "weight": None,
        })
    top_topics = [t for t, _ in sorted(topics.items(), key=lambda x: -x[1])[:4]]

    sb = pif_row.score_breakdown if isinstance(pif_row.score_breakdown, dict) else {}
    firm_meta = {
        "icp_score": pif_row.icp_score,
        "icp_tier": pif_row.icp_tier,
        "size_hint": sb.get("firm_size_reason"),
    }

    # P2: leadership bio + LinkedIn for this contact (match by email).
    bio = linkedin = None
    ce = (contact_email or "").strip().lower()
    if ce:
        for person in (pif_row.leadership or []):
            if not isinstance(person, dict):
                continue
            if (person.get("email") or "").strip().lower() == ce:
                bio = _excerpt(person.get("bio"), 600) or None
                linkedin = person.get("linkedin") or person.get("linkedin_url")
                break

    return {
        "inferred_pain_points": pains,
        "firm_behavior": {
            "top_sender_roles": [{"role": r, "count": c} for r, c in ranked[:5]],
            "after_hours_ratio": after_hours,
            "top_topics": top_topics,
        },
        "firm_meta": firm_meta,
        "contact_bio": bio,
        "contact_linkedin": linkedin,
    }


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
        activity = None
        if contact.pif_id:
            activity = (await session.execute(
                select(FrontFirmActivityRow)
                .where(FrontFirmActivityRow.pif_id == contact.pif_id)
                .order_by(desc(FrontFirmActivityRow.warm_score), desc(FrontFirmActivityRow.last_seen_at))
                .limit(1)
            )).scalar_one_or_none()
        pif_row = await session.get(PifFirmRow, contact.pif_id) if contact.pif_id else None
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
    signals = _derive_pif_signals(pif_row, contact.email)
    competitive_context = await fetch_competitive_context_for_email(
        contact=contact,
        firm_name=firm_name,
    )
    return {
        "firm": {
            "name": firm_name,
            "pif_id": contact.pif_id,
            "domain": contact_domain,
            "relationship_signals": [],
            # P4: ICP + size so framing/economics language is calibrated.
            "icp_score": signals["firm_meta"].get("icp_score"),
            "icp_tier": signals["firm_meta"].get("icp_tier"),
            "size_hint": signals["firm_meta"].get("size_hint"),
        },
        "contact": {
            "id": contact.id,
            "name": contact.full_name,
            "first_name": contact.first_name,
            "email": contact.email,
            "title": contact.title,
            "persona": contact.persona,
            "persona_source": contact.persona_source,
            "persona_confidence": contact.persona_confidence,
            "source": contact.source,
            # P2: personalize from the leadership bio / LinkedIn when present.
            "bio": signals["contact_bio"],
            "linkedin_url": contact.linkedin_url or signals["contact_linkedin"],
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
        "front_signals": {
            "behavior": (activity.behavioral_json if activity else None) or {},
        },
        # P1: the firm's observed email sender-role mix, top topics, and
        # after-hours ratio — evidence of where this firm's operational pain
        # actually is. Drives a firm-specific pain pivot instead of a generic one.
        "firm_behavior": signals["firm_behavior"],
        "inferred_pain_points": signals["inferred_pain_points"],
        "competitive_context": competitive_context,
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
    listening_context = await fetch_listening_context_for_email(
        contact=contact,
        firm_name=firm_name,
        limit=5,
    )
    if listening_context.get("available"):
        payload["listening_mindset_context"] = listening_context
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
    selected_model = model or os.getenv("LEAD_EMAIL_COMPOSER_MODEL", "openclaw/proxy")
    trace_context = {
        "firm_name": firm_name,
        "contact_id": contact.id,
        "contact_email": contact.email,
        "contact_name": contact.full_name,
        "pif_id": contact.pif_id,
        "sequence": _sequence_snapshot(sequence, step_num=step_num),
        "research_evidence": research_evidence or {},
        "selection_evidence": selection_evidence or {},
        "listening_mindset": {
            "available": bool(listening_context.get("available")),
            "brief_version": listening_context.get("brief_version"),
            "query": listening_context.get("query"),
            "insight_count": len(listening_context.get("insights") or []),
            "error": listening_context.get("error"),
        },
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
            "competitive_context": payload.get("competitive_context", {}),
            "policy": payload.get("policy", {}),
            "listening_mindset": payload.get("listening_mindset_context") or {
                "available": False,
                "brief_version": None,
                "query": listening_context.get("query"),
                "error": listening_context.get("error"),
            },
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
        brief_version=listening_context.get("brief_version"),
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
            "brief_version": composition.brief_version,
        },
        context_json=trace_context,
        metadata_json={"raw_response_excerpt": _excerpt(composition.raw_response, 1200)},
    )
    return composition
