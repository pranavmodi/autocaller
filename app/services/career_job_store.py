"""Merge verified career-search jobs into the existing firm posting collection."""
from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PROVIDER = "possibleos_daily_career_search"


def source_identity(url: str) -> str:
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/")
    if parts.hostname == "jobs.jobvite.com" and path.endswith("/apply"):
        path = path[:-6]
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query)
                             if not k.lower().startswith("utm_") and k.lower() not in {"ref", "source", "gh_src"}))
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def same_job(left: dict, right: dict) -> bool:
    left_urls = {source_identity(u) for u in [left.get("source_url"), *(left.get("source_urls") or [])] if u}
    right_urls = {source_identity(u) for u in [right.get("source_url"), *(right.get("source_urls") or [])] if u}
    if left_urls & right_urls:
        return True
    return bool(left.get("requisition_id") and left.get("requisition_id") == right.get("requisition_id")
                and left.get("ats_provider") and str(left.get("ats_provider")).strip().casefold() == str(right.get("ats_provider") or "").strip().casefold())


def merge_career_postings(existing: list[dict], incoming: list[dict]) -> tuple[list[dict], int]:
    result = deepcopy(existing)
    added = 0
    for item in incoming:
        match = next((i for i, old in enumerate(result) if same_job(old, item)), None)
        if match is None:
            result.append(deepcopy(item))
            added += 1
            continue
        old = result[match]
        merged = {**old, **deepcopy(item)}
        # A recheck is not a new publication or a new discovery.
        for field in ("id", "first_seen_at", "posted_date", "employer_posted_date", "ats_created_at"):
            if old.get(field) is not None:
                merged[field] = old[field]
        if old.get("posted_date") is not None:
            merged["date_evidence"] = deepcopy(old.get("date_evidence"))
        merged["source_urls"] = sorted(set(filter(None, [old.get("source_url"), item.get("source_url"),
            *(old.get("source_urls") or []), *(item.get("source_urls") or [])])))
        result[match] = merged
    return result, added


def preserve_career_postings(existing: Any, researched: Any) -> list[dict]:
    """Routine research may replace its own snapshot, never verified daily rows."""
    daily = [p for p in (existing or []) if isinstance(p, dict) and p.get("discovery_provider") == PROVIDER]
    result = [deepcopy(p) for p in (researched or []) if isinstance(p, dict)]
    # The broad snapshot is not the old record: it must not supply original dates.
    for protected in daily:
        match = next((i for i, p in enumerate(result) if same_job(p, protected)), None)
        if match is None:
            result.append(deepcopy(protected))
        else:
            result[match] = {**result[match], **deepcopy(protected)}
    return result


def job_id(domain: str, posting: dict) -> str:
    key = f"{str(posting.get('ats_provider') or '').strip().casefold()}:{posting['requisition_id']}" if posting.get("requisition_id") else source_identity(posting["source_url"])
    return "career_" + hashlib.sha256(f"{domain}:{key}".encode()).hexdigest()[:24]
