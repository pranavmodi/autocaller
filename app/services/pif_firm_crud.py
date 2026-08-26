"""Operator-managed CRUD for the local PI-firm directory.

The directory is primarily an EmailTag mirror, but operators also need to add
research-backed firms before they exist upstream. These writes keep the same
row and alias contracts as the sync path while recording manual provenance.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, or_, select

from app.db import AsyncSessionLocal
from app.db.models import FirmAliasRow, PifFirmRow
from app.services.firm_intel_sync import ensure_firm_intel_tables, get_mirrored_pif_firm
from app.services.front_sync import is_consumer_domain, normalize_domain


class PifFirmCrudError(ValueError):
    """Base error for operator firm writes."""


class PifFirmNotFoundError(PifFirmCrudError):
    pass


class PifFirmConflictError(PifFirmCrudError):
    def __init__(self, message: str, *, firm_id: str | None = None):
        super().__init__(message)
        self.firm_id = firm_id


class PifFirmProtectedError(PifFirmCrudError):
    pass


WRITE_FIELDS = {
    "firm_id",
    "firm_name",
    "website",
    "canonical_website",
    "entity_type",
    "metro",
    "warm_score",
    "emails",
    "phones",
    "fax",
    "addresses",
    "contacts",
    "leadership",
    "staff",
    "contact_profiles",
    "research_data",
    "behavioral_data",
    "score_breakdown",
    "conversation_ids",
    "extraction_notes",
    "vendor_stack",
    "icp_score",
    "icp_tier",
    "research_status",
    "staff_research_status",
    "first_contacted_precise_at",
    "last_researched_at",
    "icp_scored_at",
    "aliases",
    "provenance",
}

LIST_FIELDS = {
    "emails",
    "phones",
    "addresses",
    "contacts",
    "leadership",
    "staff",
    "conversation_ids",
}

DICT_FIELDS = {
    "contact_profiles",
    "research_data",
    "behavioral_data",
    "score_breakdown",
    "vendor_stack",
    "provenance",
}

SCALAR_FIELDS = {
    "firm_name",
    "entity_type",
    "metro",
    "warm_score",
    "fax",
    "extraction_notes",
    "icp_score",
    "icp_tier",
    "research_status",
    "staff_research_status",
}

TIMESTAMP_FIELDS = {
    "first_contacted_precise_at",
    "last_researched_at",
    "icp_scored_at",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: Any, field: str) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        raise PifFirmCrudError(f"{field} must be an ISO-8601 timestamp or null")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise PifFirmCrudError(f"{field} must be an ISO-8601 timestamp or null") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _normalize_aliases(value: Any) -> dict[str, list[str]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise PifFirmCrudError("aliases must be an object")
    out: dict[str, list[str]] = {}
    for key in ("domains", "vanity_domains", "legacy_pif_ids"):
        raw_values = value.get(key, [])
        if not isinstance(raw_values, list):
            raise PifFirmCrudError(f"aliases.{key} must be a list")
        normalized: list[str] = []
        for raw in raw_values:
            text = str(raw or "").strip()
            if not text:
                continue
            if key != "legacy_pif_ids":
                text = normalize_domain(text)
                if not text or is_consumer_domain(text):
                    raise PifFirmCrudError(f"invalid firm domain alias: {raw}")
            if text not in normalized:
                normalized.append(text)
        out[key] = normalized
    return out


def normalize_firm_write(payload: dict[str, Any], *, creating: bool) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PifFirmCrudError("firm payload must be a JSON object")
    unknown = sorted(set(payload) - WRITE_FIELDS)
    if unknown:
        raise PifFirmCrudError(f"unsupported fields: {', '.join(unknown)}")

    normalized = deepcopy(payload)
    for field in LIST_FIELDS:
        if field in normalized and not isinstance(normalized[field], list):
            raise PifFirmCrudError(f"{field} must be a list")
    for field in DICT_FIELDS:
        if field in normalized and not isinstance(normalized[field], dict):
            raise PifFirmCrudError(f"{field} must be an object")
    if "aliases" in normalized:
        normalized["aliases"] = _normalize_aliases(normalized["aliases"])
    for field in TIMESTAMP_FIELDS:
        if field in normalized:
            normalized[field] = _parse_timestamp(normalized[field], field)

    if "firm_name" in normalized:
        normalized["firm_name"] = str(normalized["firm_name"] or "").strip()
        if not normalized["firm_name"]:
            raise PifFirmCrudError("firm_name cannot be empty")

    website_supplied = "website" in normalized or "canonical_website" in normalized
    if website_supplied:
        raw_website = normalized.get("canonical_website") or normalized.get("website")
        domain = normalize_domain(str(raw_website or ""))
        if not domain or is_consumer_domain(domain):
            raise PifFirmCrudError("website must be a valid non-consumer domain or URL")
        normalized["website"] = domain
        normalized["canonical_website"] = domain

    if "firm_id" in normalized:
        normalized["firm_id"] = str(normalized["firm_id"] or "").strip()
        if not normalized["firm_id"]:
            normalized.pop("firm_id")
        elif len(normalized["firm_id"]) > 64:
            raise PifFirmCrudError("firm_id cannot exceed 64 characters")

    if creating:
        if not normalized.get("firm_name"):
            raise PifFirmCrudError("firm_name is required")
        if not normalized.get("canonical_website"):
            raise PifFirmCrudError("website or canonical_website is required")
    elif not normalized:
        raise PifFirmCrudError("update payload cannot be empty")
    return normalized


def _person_values(people: list[dict[str, Any]], field: str, *, lower: bool = False) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for person in people:
        if not isinstance(person, dict):
            continue
        value = str(person.get(field) or "").strip()
        if not value:
            continue
        value = value.lower() if lower else value
        if value not in seen:
            seen.add(value)
            values.append(value)
    return values


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _record_manual_overrides(row: PifFirmRow, payload: dict[str, Any]) -> None:
    source = deepcopy(row.source_json) if isinstance(row.source_json, dict) else {}
    overrides = source.get("_possibleos_manual_overrides")
    if not isinstance(overrides, dict):
        overrides = {}
    overrides.update(_json_safe(payload))
    source["_possibleos_manual_overrides"] = overrides
    row.source_json = source


def _effective_aliases(row: PifFirmRow, payload: dict[str, Any]) -> dict[str, list[str]]:
    raw = row.raw_json if isinstance(row.raw_json, dict) else {}
    if "aliases" in payload:
        aliases = deepcopy(payload["aliases"])
    else:
        aliases = _normalize_aliases(raw.get("aliases"))
    canonical = row.canonical_website or row.website
    if canonical:
        domains = aliases.setdefault("domains", [])
        if canonical not in domains:
            domains.insert(0, canonical)
    aliases.setdefault("vanity_domains", [])
    aliases.setdefault("legacy_pif_ids", [])
    return aliases


def _apply_payload(row: PifFirmRow, payload: dict[str, Any], *, now: datetime, creating: bool) -> dict[str, list[str]]:
    for field in SCALAR_FIELDS:
        if field in payload:
            setattr(row, field, payload[field])
    if "canonical_website" in payload:
        row.website = payload["canonical_website"]
        row.canonical_website = payload["canonical_website"]
    for field in LIST_FIELDS | DICT_FIELDS:
        if field in payload:
            setattr(row, field, deepcopy(payload[field]))
    for field in TIMESTAMP_FIELDS:
        if field in payload:
            setattr(row, field, payload[field])

    people_changed = bool({"contacts", "leadership", "staff"} & set(payload))
    if "contacts" in payload:
        contacts = [item for item in row.contacts if isinstance(item, dict)]
        if "leadership" not in payload:
            row.leadership = [item for item in contacts if item.get("is_decision_maker") is True]
        if "staff" not in payload:
            row.staff = [item for item in contacts if item.get("is_decision_maker") is not True]
    elif people_changed:
        row.contacts = [
            *[item for item in (row.leadership or []) if isinstance(item, dict)],
            *[item for item in (row.staff or []) if isinstance(item, dict)],
        ]
    if people_changed:
        if "emails" not in payload:
            row.emails = _person_values(row.contacts or [], "email", lower=True)
        if "phones" not in payload:
            row.phones = _person_values(row.contacts or [], "phone")

    aliases = _effective_aliases(row, payload)
    existing_raw = deepcopy(row.raw_json) if isinstance(row.raw_json, dict) else {}
    provenance = deepcopy(existing_raw.get("provenance")) if isinstance(existing_raw.get("provenance"), dict) else {}
    provenance.update(deepcopy(payload.get("provenance") or {}))
    provenance.setdefault("source", "possibleos_manual")
    provenance["operator_updated_at"] = now.isoformat()
    if creating:
        provenance.setdefault("operator_created_at", now.isoformat())

    row.profile_source = "manual" if creating else (row.profile_source or "manual")
    if creating:
        row.manually_added = True
    row.synced_at = now
    row.updated_at = now
    if creating:
        row.source_created_at = now
    if row.profile_source == "manual":
        row.source_updated_at = now

    identity = deepcopy(existing_raw.get("identity")) if isinstance(existing_raw.get("identity"), dict) else {}
    identity.update({
        "metro": row.metro,
        "entity_type": row.entity_type,
        "icp_tier": row.icp_tier,
    })
    icp = deepcopy(existing_raw.get("icp")) if isinstance(existing_raw.get("icp"), dict) else {}
    icp.update({
        "score": row.icp_score,
        "tier": row.icp_tier,
        "score_breakdown": row.score_breakdown or {},
    })
    existing_raw.update({
        "firm_id": row.id,
        "firm_name": row.firm_name,
        "canonical_website": row.canonical_website,
        "aliases": aliases,
        "identity": identity,
        "people": row.contacts or [],
        "vendor_stack": row.vendor_stack or {},
        "research": row.research_data or {},
        "behavior": row.behavioral_data or {},
        "icp": icp,
        "provenance": provenance,
    })
    row.raw_json = existing_raw
    source = deepcopy(row.source_json) if isinstance(row.source_json, dict) else {}
    source.update({
        "id": row.id,
        "firm_name": row.firm_name,
        "entity_type": row.entity_type,
        "operator_managed": True,
        "operator_updated_at": now.isoformat(),
    })
    source.setdefault("created_at", now.isoformat())
    row.source_json = source
    return aliases


async def _resolve_row(session, value: str) -> PifFirmRow | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    row = await session.get(PifFirmRow, raw)
    if row is not None:
        return row
    domain = normalize_domain(raw)
    if not domain:
        return None
    alias = await session.get(FirmAliasRow, {"alias_type": "domain", "alias_value": domain})
    if alias is not None:
        return await session.get(PifFirmRow, alias.firm_id)
    result = await session.execute(
        select(PifFirmRow).where(
            or_(PifFirmRow.canonical_website == domain, PifFirmRow.website == domain)
        )
    )
    return result.scalar_one_or_none()


async def _domain_owner(session, domain: str) -> str | None:
    alias = await session.get(FirmAliasRow, {"alias_type": "domain", "alias_value": domain})
    if alias is not None:
        return alias.firm_id
    result = await session.execute(
        select(PifFirmRow.id).where(
            or_(PifFirmRow.canonical_website == domain, PifFirmRow.website == domain)
        )
    )
    return result.scalar_one_or_none()


async def _replace_aliases(
    session,
    firm_id: str,
    aliases: dict[str, list[str]],
    *,
    now: datetime,
) -> int:
    await session.execute(delete(FirmAliasRow).where(FirmAliasRow.firm_id == firm_id))
    candidates: list[tuple[str, str]] = []
    candidates.extend(("domain", value) for value in aliases.get("domains", []))
    candidates.extend(("vanity_domain", value) for value in aliases.get("vanity_domains", []))
    candidates.extend(("legacy_pif_id", value) for value in aliases.get("legacy_pif_ids", []))
    for alias_type, alias_value in candidates:
        session.add(FirmAliasRow(
            alias_type=alias_type,
            alias_value=alias_value,
            firm_id=firm_id,
            synced_at=now,
        ))
    return len(candidates)


def _result(status: str, row: PifFirmRow, *, aliases_touched: int, dry_run: bool) -> dict[str, Any]:
    return {
        "status": status,
        "dry_run": dry_run,
        "firm_id": row.id,
        "firm_name": row.firm_name,
        "canonical_website": row.canonical_website or row.website,
        "profile_source": row.profile_source,
        "manually_added": bool(row.manually_added),
        "aliases_touched": aliases_touched,
        "vendor_stack": row.vendor_stack or {},
    }


async def create_pif_firm(payload: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    data = normalize_firm_write(payload, creating=True)
    await ensure_firm_intel_tables()
    now = _utcnow()
    firm_id = data.pop("firm_id", None) or f"manual-{uuid4().hex}"
    domain = data["canonical_website"]
    async with AsyncSessionLocal() as session:
        if await session.get(PifFirmRow, firm_id) is not None:
            raise PifFirmConflictError(f"firm_id already exists: {firm_id}", firm_id=firm_id)
        owner = await _domain_owner(session, domain)
        if owner:
            raise PifFirmConflictError(
                f"domain already belongs to firm {owner}: {domain}", firm_id=owner
            )
        row = PifFirmRow(id=firm_id, created_at=now)
        _record_manual_overrides(row, data)
        aliases = _apply_payload(row, data, now=now, creating=True)
        if dry_run:
            return _result("would_create", row, aliases_touched=sum(map(len, aliases.values())), dry_run=True)
        session.add(row)
        alias_count = await _replace_aliases(session, firm_id, aliases, now=now)
        await session.commit()
        return _result("created", row, aliases_touched=alias_count, dry_run=False)


async def update_pif_firm(
    value: str,
    payload: dict[str, Any],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    data = normalize_firm_write(payload, creating=False)
    data.pop("firm_id", None)
    await ensure_firm_intel_tables()
    now = _utcnow()
    async with AsyncSessionLocal() as session:
        row = await _resolve_row(session, value)
        if row is None:
            raise PifFirmNotFoundError(f"firm not found: {value}")
        domain = data.get("canonical_website")
        if domain:
            owner = await _domain_owner(session, domain)
            if owner and owner != row.id:
                raise PifFirmConflictError(
                    f"domain already belongs to firm {owner}: {domain}", firm_id=owner
                )
        target = deepcopy(row) if dry_run else row
        _record_manual_overrides(target, data)
        aliases = _apply_payload(target, data, now=now, creating=False)
        if dry_run:
            return _result("would_update", target, aliases_touched=sum(map(len, aliases.values())), dry_run=True)
        alias_count = await _replace_aliases(session, row.id, aliases, now=now)
        await session.commit()
        return _result("updated", row, aliases_touched=alias_count, dry_run=False)


async def upsert_pif_firm(payload: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    data = normalize_firm_write(payload, creating=True)
    await ensure_firm_intel_tables()
    async with AsyncSessionLocal() as session:
        existing = None
        if data.get("firm_id"):
            existing = await _resolve_row(session, data["firm_id"])
        if existing is None:
            existing = await _resolve_row(session, data["canonical_website"])
        existing_id = existing.id if existing is not None else None
    if existing_id:
        data.pop("firm_id", None)
        return await update_pif_firm(existing_id, data, dry_run=dry_run)
    return await create_pif_firm(data, dry_run=dry_run)


async def delete_pif_firm(
    value: str,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    await ensure_firm_intel_tables()
    async with AsyncSessionLocal() as session:
        row = await _resolve_row(session, value)
        if row is None:
            raise PifFirmNotFoundError(f"firm not found: {value}")
        if row.profile_source != "manual" and not force:
            raise PifFirmProtectedError(
                "refusing to delete an upstream-synced firm without force=true; it may return on the next sync"
            )
        result = {
            "status": "would_delete" if dry_run else "deleted",
            "dry_run": dry_run,
            "firm_id": row.id,
            "firm_name": row.firm_name,
            "profile_source": row.profile_source,
            "manually_added": bool(row.manually_added),
            "operational_data_preserved": True,
        }
        if dry_run:
            return result
        await session.execute(delete(FirmAliasRow).where(FirmAliasRow.firm_id == row.id))
        await session.delete(row)
        await session.commit()
        return result


async def get_pif_firm_for_crud(value: str) -> dict[str, Any] | None:
    """Resolve IDs or domains and return the complete mirror representation."""
    await ensure_firm_intel_tables()
    async with AsyncSessionLocal() as session:
        row = await _resolve_row(session, value)
        firm_id = row.id if row is not None else None
    return await get_mirrored_pif_firm(firm_id) if firm_id else None


def apply_stored_manual_overrides(
    row: PifFirmRow,
    payload: dict[str, Any],
    *,
    now: datetime,
) -> None:
    """Reapply durable local overrides after an upstream mirror refresh."""
    raw_json = deepcopy(row.raw_json) if isinstance(row.raw_json, dict) else {}
    raw_aliases = raw_json.get("aliases")
    if isinstance(raw_aliases, dict):
        for key in ("domains", "vanity_domains"):
            values = raw_aliases.get(key)
            if isinstance(values, list):
                raw_aliases[key] = [
                    value
                    for value in values
                    if (domain := normalize_domain(str(value or "")))
                    and not is_consumer_domain(domain)
                ]
        raw_json["aliases"] = raw_aliases
        row.raw_json = raw_json

    cleaned_payload = deepcopy(payload)
    aliases = cleaned_payload.get("aliases")
    if isinstance(aliases, dict):
        cleaned_aliases = deepcopy(aliases)
        for key in ("domains", "vanity_domains"):
            values = cleaned_aliases.get(key)
            if isinstance(values, list):
                cleaned_aliases[key] = [
                    value
                    for value in values
                    if (domain := normalize_domain(str(value or "")))
                    and not is_consumer_domain(domain)
                ]
        cleaned_payload["aliases"] = cleaned_aliases

    data = normalize_firm_write(cleaned_payload, creating=False)
    _record_manual_overrides(row, data)
    _apply_payload(row, data, now=now, creating=False)
