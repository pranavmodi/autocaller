"""Map PI firm contacts to composer persona keys.

Design note: behavioral classification from Front inbox attribution and
signature extraction are planned higher-precedence sources. Keep sources in
``PERSONA_SOURCES`` ordered from strongest to weakest so those can be inserted
without changing the no-downgrade update rule.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.db.models import FirmContactRow


PERSONA_KEYS = {
    "founder_owner",
    "managing_partner",
    "coo_ops",
    "intake",
    "records",
    "case_manager",
    "lien_settlement",
    "marketing",
    "attorney",
    "paralegal",
}


@dataclass(frozen=True)
class PersonaMatch:
    persona: str | None
    source: str
    confidence: float


@dataclass(frozen=True)
class _TitleRule:
    persona: str
    phrases: tuple[str, ...]


TITLE_RULES: tuple[_TitleRule, ...] = (
    _TitleRule("founder_owner", ("founder", "owner", "principal", "shareholder")),
    _TitleRule("managing_partner", ("managing partner", "managing attorney", "senior partner", "partner")),
    _TitleRule("coo_ops", ("chief executive officer", "ceo", "president")),
    _TitleRule("coo_ops", ("chief operating officer", "coo", "executive director", "director of operations")),
    _TitleRule("attorney", ("pi practice chair", "practice chair", "litigation lead", "pre-litigation lead", "pre litigation lead")),
    _TitleRule("coo_ops", ("business manager", "operating partner")),
    _TitleRule("attorney", ("trial attorney", "trial lawyer", "litigation attorney", "pre-lit attorney", "pre-litigation attorney", "case attorney", "associate attorney", "senior counsel", "of counsel", "intake attorney", "signing attorney", "settlement attorney", "demand attorney", "attorney", "lawyer")),
    _TitleRule("intake", ("director of intake", "intake director", "intake manager", "intake specialist", "intake coordinator", "contact center manager", "call center manager", "call center lead", "receptionist", "front desk", "client services", "new client specialist", "new client coordinator", "sign-up coordinator", "signup coordinator", "spanish intake", "bilingual intake", "answering-service manager", "answering service manager", "intake vendor owner", "intake")),
    _TitleRule("case_manager", ("senior case manager", "lead case manager", "case management supervisor", "case manager", "client relations manager", "client experience manager", "client liaison", "client concierge", "medical treatment coordinator", "treatment coordinator", "property damage specialist")),
    _TitleRule("paralegal", ("litigation paralegal", "trial paralegal", "pre-lit paralegal", "prelit paralegal", "pre-litigation paralegal", "paralegal")),
    _TitleRule("records", ("medical records manager", "medical records lead", "records manager", "records specialist", "records coordinator", "records clerk", "demand writer", "demand package specialist", "document specialist", "document clerk", "legal assistant")),
    _TitleRule("lien_settlement", ("lien negotiator", "lien specialist", "medical bill reviewer", "bill review specialist", "damages analyst", "settlement coordinator", "settlement specialist", "disbursement coordinator", "provider relations coordinator", "provider relations", "medical network coordinator", "subrogation specialist", "health insurance lien specialist", "lien", "settlement", "disbursement", "subrogation")),
    _TitleRule("marketing", ("marketing director", "director of marketing", "chief marketing officer", "cmo", "digital marketing manager", "ppc manager", "seo manager", "growth manager", "referral relationship manager", "referral coordinator", "community relations", "reputation manager", "reviews manager", "client feedback manager", "business development lead", "bd director", "partnerships manager", "intake analytics owner", "revenue operations", "growth analyst", "marketing")),
    _TitleRule("coo_ops", ("office manager", "firm administrator", "legal administrator", "hr manager", "talent manager", "training manager", "quality assurance lead", "qa manager", "administrative assistant", "compliance officer", "risk manager")),
    _TitleRule("coo_ops", ("chief financial officer", "cfo", "controller", "accounting manager", "bookkeeper", "trust accounting specialist", "revenue operations analyst", "revops", "business analyst", "procurement", "vendor manager")),
    _TitleRule("coo_ops", ("it manager", "systems administrator", "legal operations manager", "legal ops", "systems manager", "filevine admin", "litify admin", "smartadvocate admin", "casepeer admin", "case management system admin", "data analyst", "bi analyst", "automation specialist", "ai lead", "innovation manager")),
    _TitleRule("attorney", ("mass tort attorney", "workers' comp attorney", "workers comp attorney", "premises liability attorney", "catastrophic injury attorney")),
    _TitleRule("case_manager", ("mass tort coordinator", "workers' comp coordinator", "workers comp coordinator", "auto accident team lead", "motor-vehicle accident lead", "motor vehicle accident lead", "bilingual team lead", "hispanic market lead")),
    _TitleRule("coo_ops", ("law firm consultant", "intake consultant", "legal ops consultant", "pi practice consultant")),
    _TitleRule("marketing", ("legal marketing agency", "seo/ppc agency", "intake marketing agency", "podcast host", "newsletter writer", "conference speaker", "thought leader")),
    _TitleRule("coo_ops", ("case management vendor rep", "implementation partner", "filevine consultant", "litify consultant")),
    _TitleRule("lien_settlement", ("medical lien provider", "lien funding company", "medical network rep")),
    _TitleRule("records", ("imaging provider rep", "diagnostics provider rep", "records retrieval vendor", "records vendor", "court reporting", "litigation support vendor")),
)


FUNCTIONAL_EMAIL_PREFIXES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("records", "record", "medicalrecords", "medical.records"), "records"),
    (("intake", "newclient", "new.client", "signup", "signups", "leads"), "intake"),
    (("liens", "lien", "billing", "settlement", "settlements", "disbursement"), "lien_settlement"),
)


def _normalize_text(value: str | None) -> str:
    text = (value or "").strip().lower()
    text = text.replace("&", " and ").replace("/", " ")
    text = re.sub(r"[^a-z0-9'+.-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _phrase_in_text(phrase: str, text: str) -> bool:
    clean = _normalize_text(phrase)
    if not clean or not text:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(clean)}(?![a-z0-9])", text) is not None


def _classify_title(title: str | None, *, source: str) -> PersonaMatch | None:
    text = _normalize_text(title)
    if not text:
        return None
    if any(_phrase_in_text(phrase, text) for phrase in ("co-founder", "co founder", "founder", "founding partner")):
        return PersonaMatch("founder_owner", source, 0.9)
    best: tuple[int, str] | None = None
    for rule in TITLE_RULES:
        for phrase in rule.phrases:
            if _phrase_in_text(phrase, text):
                score = len(_normalize_text(phrase))
                if best is None or score > best[0]:
                    best = (score, rule.persona)
    return PersonaMatch(best[1], source, 0.9) if best else None


def _classify_email(email: str | None) -> PersonaMatch | None:
    local = (email or "").split("@", 1)[0].strip().lower()
    if not local:
        return None
    normalized = re.sub(r"[^a-z0-9.]+", "", local)
    for prefixes, persona in FUNCTIONAL_EMAIL_PREFIXES:
        if any(normalized == prefix or normalized.startswith(f"{prefix}.") for prefix in prefixes):
            return PersonaMatch(persona, "email_prefix", 0.7)
    return None


PERSONA_SOURCES = (
    lambda title, email, name: _classify_title(title, source="title_keyword"),
    lambda title, email, name: _classify_email(email),
)


def classify_contact(title: str | None, email: str | None, name: str | None = None) -> tuple[str | None, str, float]:
    """Classify a contact from title/name/email into a composer persona key."""
    for source in PERSONA_SOURCES:
        match = source(title, email, name)
        if match and match.persona:
            return match.persona, match.source, match.confidence
    return None, "none", 0.0


def classify_contact_fields(
    *,
    research_title: str | None = None,
    title: str | None = None,
    email: str | None = None,
    name: str | None = None,
) -> PersonaMatch:
    for value, source in ((research_title, "research_title"), (title, "title_keyword")):
        match = _classify_title(value, source=source)
        if match:
            return match
    match = _classify_email(email)
    if match:
        return match
    return PersonaMatch(None, "none", 0.0)


async def map_personas(pif_id: str | None = None) -> dict[str, int]:
    """Fill contact persona columns idempotently without lowering confidence."""
    scanned = updated = skipped = 0
    async with AsyncSessionLocal() as session:
        stmt = select(FirmContactRow)
        if pif_id:
            stmt = stmt.where(FirmContactRow.pif_id == str(pif_id))
        contacts = await session.stream_scalars(stmt.execution_options(yield_per=500))
        async for contact in contacts:
            scanned += 1
            if scanned % 250 == 0:
                await asyncio.sleep(0)
            match = classify_contact_fields(
                research_title=contact.research_title,
                title=contact.title,
                email=contact.email,
                name=contact.full_name,
            )
            if not match.persona:
                skipped += 1
                continue
            current = float(contact.persona_confidence or 0.0)
            # Never lower confidence, but DO correct a wrong persona at equal
            # confidence — otherwise an early misclassification is permanent.
            if contact.persona and (
                current > match.confidence
                or (current == match.confidence and contact.persona == match.persona)
            ):
                skipped += 1
                continue
            contact.persona = match.persona
            contact.persona_source = match.source
            contact.persona_confidence = match.confidence
            updated += 1
        await session.commit()
    return {"scanned": scanned, "updated": updated, "skipped": skipped}
