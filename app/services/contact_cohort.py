"""Pure helpers for curated outreach cohort selection."""
from __future__ import annotations

import random
from collections.abc import Iterable, Mapping
from typing import Any


def email_domain(value: Any) -> str:
    """Return a normalized domain for an email address, or an empty string."""
    email = str(value or "").strip().lower()
    local, separator, domain = email.rpartition("@")
    if not separator or not local or not domain:
        return ""
    return domain.rstrip(".")


def select_curated_contact_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    max_per_firm: int,
    max_per_domain: int,
    second_contact_min_team: int = 0,
    limit: int = 0,
    seed: int = 0,
) -> list[dict[str, Any]]:
    """Deduplicate eligible rows and apply firm and email-domain caps."""
    firms: dict[str, list[dict[str, Any]]] = {}
    seen_emails: set[str] = set()
    for raw_row in rows:
        row = dict(raw_row)
        email = str(row.get("email") or "").strip().lower()
        domain = str(row.get("email_domain") or email_domain(email)).strip().lower()
        if not email or not domain or email in seen_emails:
            continue
        seen_emails.add(email)
        row["email_domain"] = domain
        firms.setdefault(str(row.get("pif_id") or ""), []).append(row)

    firm_order = list(firms)
    if seed:
        random.Random(seed).shuffle(firm_order)

    selected: list[dict[str, Any]] = []
    domain_counts: dict[str, int] = {}
    for pif_id in firm_order:
        contacts = firms[pif_id]
        firm_cap = max_per_firm
        if second_contact_min_team and len(contacts) < second_contact_min_team:
            firm_cap = 1
        firm_count = 0
        for row in contacts:
            if firm_count >= firm_cap:
                break
            domain = row["email_domain"]
            if domain_counts.get(domain, 0) >= max_per_domain:
                continue
            selected.append(row)
            firm_count += 1
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
            if limit and len(selected) >= limit:
                return selected
    return selected
