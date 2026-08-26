"""Firm selection and lead preparation for operator-run calls."""
from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, select

from app.db import AsyncSessionLocal
from app.db.models import FirmContactRow, PatientRow, PifFirmRow
from app.services.firm_intel_sync import _vendor_entries_for_row, _vendor_label
from app.services.phone_normalize import normalize_phone


LAW_FIRM_ENTITY_TYPES = {"pi_law_firm", "law_firm", "personal_injury_law_firm"}
DECISION_PERSONAS = {"founder_owner", "managing_partner", "coo_ops"}
FOUNDER_TERMS = ("founder", "founding", "owner", "principal")


def _text(person: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = person.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _contact_id(pif_id: str, name: str, phone: str) -> str:
    raw = f"{pif_id}|{name.lower()}|{phone}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _contacts_for_firm(row: PifFirmRow) -> list[dict[str, Any]]:
    contacts: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for source, people in (("leadership", row.leadership or []), ("staff", row.staff or []), ("contacts", row.contacts or [])):
        for person in people:
            if not isinstance(person, dict):
                continue
            name = _text(person, "name", "full_name")
            phone = normalize_phone(_text(person, "phone"))
            if not name or not phone:
                continue
            dedupe_key = (name.lower(), phone)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            title = _text(person, "title", "job_title", "position")
            contacts.append({
                "id": _contact_id(row.id, name, phone), "pif_id": row.id, "name": name,
                "title": title, "role_category": _text(person, "role_category", "persona", "role"),
                "firm_name": row.firm_name or "", "phone": phone,
                "email": _text(person, "email") or None,
                "linkedin": _text(person, "linkedin", "linkedin_url") or None,
                "source": source,
                "is_decision_maker": bool(person.get("is_decision_maker")) or source == "leadership",
                "website": row.canonical_website or row.website,
            })
    return contacts


def _matches(contact: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    haystack = " ".join(str(contact.get(key) or "") for key in (
        "name", "title", "role_category", "firm_name", "phone", "email",
    )).lower()
    return all(token in haystack for token in query.lower().split())


def _known_people(row: PifFirmRow) -> list[dict[str, Any]]:
    people: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in (row.leadership or [], row.staff or [], row.contacts or []):
        for person in source:
            if not isinstance(person, dict):
                continue
            name = _text(person, "name", "full_name")
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            people.append(person)
    return people


def _size_from_text(value: Any) -> tuple[int | None, str]:
    raw = str(value or "").strip()
    text = raw.lower().replace("–", "-").replace("—", "-")
    ranges = re.findall(r"(\d+)\s*(?:-|to)\s*(\d+)", text)
    if ranges:
        low, high = (int(value) for value in ranges[-1])
        return round((low + high) / 2), raw
    numbers = [int(value) for value in re.findall(r"\d+", text)]
    return (numbers[-1], raw) if numbers else (None, raw)


def _firm_size(row: PifFirmRow) -> tuple[int | None, str, str]:
    research = row.research_data or {}
    raw = research.get("firm_size") or research.get("size_hint") or ""
    parsed, label = _size_from_text(raw)
    known_count = len(_known_people(row))
    lower = label.lower()

    # Explicit employee/team ranges are the strongest source. Attorney-only
    # counts are lower bounds, so a larger researched roster is more useful.
    explicitly_people = any(term in lower for term in ("employee", "people", "staff", "team", "linkedin"))
    if explicitly_people and parsed is not None:
        return parsed, label, "researched firm size"
    if 15 <= known_count <= 50 and (parsed is None or parsed < 15):
        return known_count, f"{known_count} researched people", "deduplicated leadership/staff roster"
    if parsed is not None:
        return parsed, label, "researched firm size"
    if known_count:
        return known_count, f"{known_count} researched people", "deduplicated leadership/staff roster"
    return None, "Unknown", ""


def _contact_rank(contact: FirmContactRow) -> tuple[int, str]:
    persona = (contact.persona or "").lower()
    title = (contact.title or contact.research_title or "").lower()
    if persona == "founder_owner" or any(term in title for term in FOUNDER_TERMS):
        rank = 0
    elif persona == "managing_partner" or "managing partner" in title or "managing attorney" in title:
        rank = 1
    elif persona == "coo_ops" or any(term in title for term in ("chief operating", "operations", "administrator")):
        rank = 2
    elif contact.source == "pif_leadership" or "partner" in title:
        rank = 3
    else:
        rank = 4
    return rank, contact.full_name.lower()


def _person_like_name(value: str) -> bool:
    name = value.strip()
    words = re.findall(r"[A-Za-z][A-Za-z'.-]+", name)
    return bool("@" not in name and len(words) >= 2)


def _valid_us_phone(value: str | None) -> str | None:
    phone = normalize_phone(value or "")
    return phone if re.fullmatch(r"\+1\d{10}", phone or "") else None


def _contact_from_directory_row(contact: FirmContactRow, firm: PifFirmRow) -> dict[str, Any] | None:
    phone = _valid_us_phone(contact.phone)
    if not phone or not _person_like_name(contact.full_name):
        return None
    return {
        "id": contact.id, "pif_id": contact.pif_id, "name": contact.full_name.strip(),
        "title": (contact.title or contact.research_title or "").strip(),
        "role_category": (contact.persona or "").strip(), "firm_name": (firm.firm_name or "").strip(),
        "phone": phone, "email": contact.email, "linkedin": contact.linkedin_url,
        "source": contact.source,
        "is_decision_maker": contact.source == "pif_leadership" or contact.persona in DECISION_PERSONAS,
        "website": firm.canonical_website or firm.website,
    }


def _leadership_brief(row: PifFirmRow) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for person in _known_people(row):
        if person not in (row.leadership or []) and not person.get("is_decision_maker"):
            continue
        result.append({
            "name": _text(person, "name", "full_name"),
            "title": _text(person, "title", "job_title", "position"),
            "email": _text(person, "email") or None,
            "phone": normalize_phone(_text(person, "phone")) or None,
            "linkedin": _text(person, "linkedin", "linkedin_url") or None,
        })
        if len(result) == 8:
            break
    return result


def _firm_brief(row: PifFirmRow, contacts: list[FirmContactRow]) -> dict[str, Any] | None:
    callable_contacts = [
        contact for contact in contacts
        if _valid_us_phone(contact.phone) and _person_like_name(contact.full_name)
    ]
    if not callable_contacts:
        return None
    callable_contacts.sort(key=_contact_rank)
    target = _contact_from_directory_row(callable_contacts[0], row)
    if target is None:
        return None
    size, size_label, size_basis = _firm_size(row)
    if size is None or not 15 <= size <= 50:
        return None

    leadership = _leadership_brief(row)
    founders = [
        person for person in leadership
        if any(term in (person.get("title") or "").lower() for term in FOUNDER_TERMS)
    ]
    vendors = _vendor_entries_for_row(row)
    technology = [
        {"key": str(entry.get("vendor") or ""), "label": _vendor_label(str(entry.get("vendor") or "")),
         "source": str(entry.get("source") or ""), "confidence": entry.get("confidence")}
        for entry in vendors if entry.get("vendor")
    ]
    research = row.research_data or {}
    behavior = row.behavioral_data or {}
    return {
        "pif_id": row.id, "firm_name": row.firm_name or "", "website": row.canonical_website or row.website,
        "metro": row.metro or research.get("metro") or research.get("city"),
        "team_size": size, "team_size_label": size_label, "team_size_basis": size_basis,
        "icp_score": row.icp_score, "icp_tier": row.icp_tier,
        "summary": str(research.get("summary") or "")[:600] or None,
        "practice_areas": list(research.get("practice_areas") or [])[:6],
        "conversation_count": len(row.conversation_ids or []),
        "monthly_email_volume": behavior.get("monthly_email_volume"),
        "primary_pain_point": behavior.get("primary_pain_point"),
        "target_contact": target, "founders": founders, "leadership": leadership,
        "technology": technology,
    }


def _firm_matches(firm: dict[str, Any], query: str) -> bool:
    if not query.strip():
        return True
    values = [firm.get("firm_name"), firm.get("metro"), firm.get("team_size_label")]
    values.extend(person.get("name") for person in firm.get("leadership", []))
    values.extend(person.get("title") for person in firm.get("leadership", []))
    values.extend(vendor.get("label") for vendor in firm.get("technology", []))
    target = firm.get("target_contact") or {}
    values.extend([target.get("name"), target.get("title"), target.get("phone"), target.get("email")])
    haystack = " ".join(str(value or "") for value in values).lower()
    return all(token.lower() in haystack for token in query.split())


def _firm_key(firm: dict[str, Any]) -> str:
    website = str(firm.get("website") or "").strip()
    if website:
        parsed = urlparse(website if "://" in website else f"https://{website}")
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if host:
            return f"web:{host}"
    name = re.sub(r"[^a-z0-9]+", "", str(firm.get("firm_name") or "").lower())
    return f"name:{name}"


async def list_call_lab_firms(*, query: str = "", limit: int = 50) -> dict[str, Any]:
    limit = max(1, min(50, int(limit)))
    async with AsyncSessionLocal() as session:
        # Vendor is an explicit hard filter. The canonical case_mgmt field is
        # used so generic evidence text cannot create a false Filevine match.
        rows = (await session.execute(
            select(PifFirmRow)
            .where(
                PifFirmRow.entity_type.in_(LAW_FIRM_ENTITY_TYPES),
                func.lower(PifFirmRow.vendor_stack["case_mgmt"].astext) == "filevine",
            )
        )).scalars().all()
        firm_ids = [row.id for row in rows]
        contacts = (await session.execute(
            select(FirmContactRow).where(
                FirmContactRow.pif_id.in_(firm_ids),
                FirmContactRow.phone.isnot(None),
                func.btrim(FirmContactRow.phone) != "",
            )
        )).scalars().all() if firm_ids else []

    contacts_by_firm: dict[str, list[FirmContactRow]] = {}
    for contact in contacts:
        contacts_by_firm.setdefault(contact.pif_id, []).append(contact)
    firms = [brief for row in rows if (brief := _firm_brief(row, contacts_by_firm.get(row.id, [])))]
    firms.sort(key=lambda firm: (
        -(firm.get("icp_score") if firm.get("icp_score") is not None else -1),
        -int(firm.get("conversation_count") or 0),
        str(firm.get("firm_name") or "").lower(),
    ))
    curated: list[dict[str, Any]] = []
    seen_firms: set[str] = set()
    seen_targets: set[str] = set()
    for firm in firms:
        key = _firm_key(firm)
        target = firm["target_contact"]
        target_key = f"{target['name'].lower()}|{target['phone']}"
        if key in seen_firms or target_key in seen_targets:
            continue
        seen_firms.add(key)
        seen_targets.add(target_key)
        curated.append(firm)
        if len(curated) == 50:
            break
    filtered = [firm for firm in curated if _firm_matches(firm, query)]
    return {
        "items": filtered[:limit], "total": len(filtered), "curated_total": len(curated),
        "vendor": "filevine", "size_min": 15, "size_max": 50, "limit": limit,
    }


async def get_call_lab_contact(pif_id: str, contact_id: str) -> dict[str, Any] | None:
    async with AsyncSessionLocal() as session:
        result = (await session.execute(
            select(FirmContactRow, PifFirmRow)
            .join(PifFirmRow, PifFirmRow.id == FirmContactRow.pif_id)
            .where(FirmContactRow.id == contact_id, FirmContactRow.pif_id == pif_id,
                   PifFirmRow.entity_type.in_(LAW_FIRM_ENTITY_TYPES))
        )).one_or_none()
    if result is None:
        return None
    return _contact_from_directory_row(result[0], result[1])


async def upsert_call_lab_patient(contact: dict[str, Any]) -> str:
    pif_id, phone = str(contact["pif_id"]), str(contact["phone"])
    patient_id = f"calllab-{pif_id[:36]}-{hashlib.sha1(phone.encode('utf-8')).hexdigest()[:8]}"
    async with AsyncSessionLocal() as session:
        row = await session.get(PatientRow, patient_id)
        if row is None:
            row = PatientRow(patient_id=patient_id, name=contact["name"], phone=phone)
            session.add(row)
        row.name, row.phone = str(contact["name"]), phone
        row.firm_name = str(contact.get("firm_name") or "")[:255] or None
        row.website = str(contact.get("website") or "")[:512] or None
        row.email = str(contact.get("email") or "")[:255] or None
        row.title = str(contact.get("title") or "")[:128] or None
        row.source, row.practice_area, row.name_is_person = "call_lab", "personal injury", True
        row.tags = sorted(set([*(row.tags or []), "call-lab", "filevine", f"pif:{pif_id}"]))
        row.notes = f"Operator call from Filevine Call Lab | PIF ID: {pif_id}"
        await session.commit()
    return patient_id
