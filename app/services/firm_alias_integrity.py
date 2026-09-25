"""Firm-domain alias validation, auditing, and conservative index repair."""
from __future__ import annotations

import re
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import delete, select, text

from app.db import AsyncSessionLocal
from app.db.models import FirmAliasRow, PifFirmRow


_HOST_RE = re.compile(
    r"^(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})$",
    re.IGNORECASE,
)

# These are shared infrastructure or publishing roots, never a firm's identity.
_SHARED_ROOTS = {
    "aim.com",
    "aol.com",
    "att.net",
    "bill.com",
    "business.site",
    "ccsend.com",
    "clio.com",
    "facebook.com",
    "filemail.com",
    "freshdesk.com",
    "gmail.com",
    "google.com",
    "hotmail.com",
    "icloud.com",
    "instagram.com",
    "law.com",
    "linkedin.com",
    "maildrop.clio.com",
    "movedocs.com",
    "outlook.com",
    "proton.me",
    "protonmail.com",
    "yahoo.com",
    "zohodesk.com",
}


def normalize_identity_domain(value: Any, *, allow_shared: bool = False) -> str:
    """Return a strict ASCII hostname or an empty string.

    This is an identifier validator, not a best-effort extractor. Notes, email
    addresses, redactions, phone numbers, and other research prose must fail.
    """
    raw = str(value or "").strip().lower()
    if not raw or "@" in raw or any(char.isspace() for char in raw):
        return ""
    try:
        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    except ValueError:
        return ""
    try:
        has_port = parsed.port is not None
    except ValueError:
        return ""
    if parsed.username or parsed.password or has_port:
        return ""
    host = (parsed.hostname or "").strip(".")
    if host.startswith("www."):
        host = host[4:]
    if not _HOST_RE.fullmatch(host):
        return ""
    if not allow_shared and host in _SHARED_ROOTS:
        return ""
    return host


def verified_manual_domains(firm: PifFirmRow) -> set[str]:
    source = firm.source_json if isinstance(firm.source_json, dict) else {}
    overrides = source.get("_possibleos_manual_overrides")
    aliases = overrides.get("aliases") if isinstance(overrides, dict) else None
    values = aliases.get("domains") if isinstance(aliases, dict) else None
    if not isinstance(values, list):
        return set()
    return {domain for value in values if (domain := normalize_identity_domain(value))}


def is_trusted_domain_alias(firm: PifFirmRow | None, domain: str) -> bool:
    if firm is None:
        return False
    normalized = normalize_identity_domain(domain)
    if not normalized:
        return False
    canonical = normalize_identity_domain(firm.canonical_website or firm.website)
    return normalized == canonical or normalized in verified_manual_domains(firm)


def _firm_rank(firm: PifFirmRow) -> tuple[int, int, int, int, float, str]:
    research_done = str(firm.research_status or "").lower() in {"completed", "done", "enriched"}
    people_count = len(firm.contacts or []) + len(firm.leadership or []) + len(firm.staff or [])
    updated = firm.updated_at or firm.synced_at or firm.source_updated_at
    timestamp = updated.timestamp() if updated else 0.0
    return (
        int(firm.profile_source == "manual"),
        int(bool(firm.manually_added)),
        int(research_done),
        people_count,
        timestamp,
        firm.id,
    )


def build_domain_alias_plan(firms: list[PifFirmRow]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Build canonical-first ownership; manual alternates never beat canonicals."""
    canonical_claims: dict[str, list[PifFirmRow]] = defaultdict(list)
    for firm in firms:
        domain = normalize_identity_domain(firm.canonical_website or firm.website)
        if domain:
            canonical_claims[domain].append(firm)

    desired: dict[str, str] = {}
    duplicates: list[dict[str, Any]] = []
    for domain, claimants in sorted(canonical_claims.items()):
        ordered = sorted(claimants, key=_firm_rank, reverse=True)
        desired[domain] = ordered[0].id
        if len(ordered) > 1:
            duplicates.append({
                "domain": domain,
                "selected_firm_id": ordered[0].id,
                "firm_ids": [firm.id for firm in ordered],
                "firm_names": [firm.firm_name for firm in ordered],
            })

    for firm in firms:
        for domain in sorted(verified_manual_domains(firm)):
            desired.setdefault(domain, firm.id)
    return desired, duplicates


async def audit_firm_aliases() -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        firms = list((await session.execute(select(PifFirmRow))).scalars().all())
        aliases = list((await session.execute(select(FirmAliasRow))).scalars().all())

    desired, duplicates = build_domain_alias_plan(firms)
    existing = {row.alias_value: row.firm_id for row in aliases if row.alias_type == "domain"}
    malformed = sorted(
        row.alias_value for row in aliases
        if row.alias_type == "domain" and not normalize_identity_domain(row.alias_value)
    )
    wrong_owner = sorted(
        domain for domain, owner in existing.items()
        if domain in desired and desired[domain] != owner
    )
    untrusted = sorted(domain for domain in existing if domain not in desired)
    missing = sorted(domain for domain in desired if domain not in existing)
    return {
        "status": "audit",
        "firms": len(firms),
        "aliases": len(aliases),
        "domain_aliases": len(existing),
        "desired_domain_aliases": len(desired),
        "wrong_owner_count": len(wrong_owner),
        "untrusted_count": len(untrusted),
        "missing_count": len(missing),
        "malformed_count": len(malformed),
        "duplicate_canonical_count": len(duplicates),
        "samples": {
            "wrong_owner": wrong_owner[:25],
            "untrusted": untrusted[:25],
            "missing": missing[:25],
            "malformed": malformed[:25],
            "duplicate_canonicals": duplicates[:25],
        },
    }


async def rebuild_firm_aliases(*, dry_run: bool = True) -> dict[str, Any]:
    """Rebuild domain aliases from canonical identity and manual verification."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        await session.execute(text("SELECT pg_advisory_xact_lock(671934205)"))
        firms = list((await session.execute(select(PifFirmRow))).scalars().all())
        aliases = list((await session.execute(
            select(FirmAliasRow).where(FirmAliasRow.alias_type == "domain")
        )).scalars().all())
        desired, duplicates = build_domain_alias_plan(firms)
        existing = {row.alias_value: row.firm_id for row in aliases}
        removed = sorted(domain for domain in existing if domain not in desired)
        reassigned = sorted(
            domain for domain, owner in existing.items()
            if domain in desired and desired[domain] != owner
        )
        inserted = sorted(domain for domain in desired if domain not in existing)
        result = {
            "status": "dry_run" if dry_run else "rebuilt",
            "existing_domain_aliases": len(existing),
            "desired_domain_aliases": len(desired),
            "removed": len(removed),
            "reassigned": len(reassigned),
            "inserted": len(inserted),
            "duplicate_canonical_count": len(duplicates),
            "samples": {
                "removed": removed[:25],
                "reassigned": reassigned[:25],
                "inserted": inserted[:25],
                "duplicate_canonicals": duplicates[:25],
            },
        }
        if dry_run:
            return result
        await session.execute(delete(FirmAliasRow).where(FirmAliasRow.alias_type == "domain"))
        session.add_all([
            FirmAliasRow(alias_type="domain", alias_value=domain, firm_id=firm_id, synced_at=now)
            for domain, firm_id in sorted(desired.items())
        ])
        await session.commit()
        return result


async def verify_firm_domain_alias(
    firm_id: str,
    domain: str,
    *,
    evidence_url: str,
) -> dict[str, Any]:
    """Persist one operator-verified alternate without replacing other aliases."""
    normalized = normalize_identity_domain(domain)
    evidence = str(evidence_url or "").strip()
    if not normalized:
        raise ValueError("invalid_identity_domain")
    if not evidence.lower().startswith(("http://", "https://")):
        raise ValueError("evidence_url_required")
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        firm = await session.get(PifFirmRow, firm_id, with_for_update=True)
        if firm is None:
            raise ValueError("firm_not_found")
        canonical_owner = (await session.execute(
            select(PifFirmRow.id).where(
                PifFirmRow.id != firm.id,
                (PifFirmRow.canonical_website == normalized) | (PifFirmRow.website == normalized),
            ).limit(1)
        )).scalar_one_or_none()
        if canonical_owner:
            raise ValueError(f"domain_is_canonical_for:{canonical_owner}")

        source = deepcopy(firm.source_json) if isinstance(firm.source_json, dict) else {}
        overrides = source.get("_possibleos_manual_overrides")
        if not isinstance(overrides, dict):
            overrides = {}
        alias_overrides = overrides.get("aliases")
        if not isinstance(alias_overrides, dict):
            alias_overrides = {}
        domains = list(alias_overrides.get("domains") or [])
        canonical = normalize_identity_domain(firm.canonical_website or firm.website)
        for value in (canonical, normalized):
            if value and value not in domains:
                domains.append(value)
        alias_overrides["domains"] = domains
        overrides["aliases"] = alias_overrides
        source["_possibleos_manual_overrides"] = overrides
        evidence_rows = source.get("_possibleos_verified_alias_evidence")
        if not isinstance(evidence_rows, dict):
            evidence_rows = {}
        evidence_rows[normalized] = {"url": evidence, "verified_at": now.isoformat()}
        source["_possibleos_verified_alias_evidence"] = evidence_rows
        firm.source_json = source
        firm.updated_at = now

        alias = await session.get(
            FirmAliasRow,
            {"alias_type": "domain", "alias_value": normalized},
            with_for_update=True,
        )
        if alias is None:
            session.add(FirmAliasRow(
                alias_type="domain",
                alias_value=normalized,
                firm_id=firm.id,
                synced_at=now,
            ))
        else:
            alias.firm_id = firm.id
            alias.synced_at = now
        await session.commit()
        return {
            "status": "verified",
            "firm_id": firm.id,
            "firm_name": firm.firm_name,
            "canonical_website": firm.canonical_website or firm.website,
            "alias": normalized,
            "evidence_url": evidence,
        }
