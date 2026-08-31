"""Discover firm sitemaps and persist URL-inventory changes over time."""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import os
import socket
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse
from xml.etree import ElementTree as ET

import httpx
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.db.models import FirmSitemapSnapshotRow, PifFirmRow


USER_AGENT = "PossibleOS-Sitemap-Monitor/1.0"
MAX_SITEMAPS = max(1, int(os.getenv("PIF_SITEMAP_MAX_FILES", "30")))
MAX_URLS = max(100, int(os.getenv("PIF_SITEMAP_MAX_URLS", "20000")))
MAX_BYTES = max(100_000, int(os.getenv("PIF_SITEMAP_MAX_BYTES", "5000000")))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _website_url(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))


def _public_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def _assert_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Sitemap URL must use public HTTP or HTTPS")
    if parsed.username or parsed.password:
        raise ValueError("Sitemap URL credentials are not allowed")
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve {parsed.hostname}") from exc
    ips = {row[4][0].split("%")[0] for row in addresses}
    if not ips or any(not _public_ip(ip) for ip in ips):
        raise ValueError("Sitemap URL resolved to a non-public address")


async def _fetch(client: httpx.AsyncClient, url: str) -> tuple[bytes, str]:
    current = url
    for _ in range(5):
        await _assert_public_url(current)
        response = await client.get(current, follow_redirects=False)
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location")
            if not location:
                raise RuntimeError(f"HTTP {response.status_code} without a redirect location")
            current = urljoin(current, location)
            continue
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}")
        body = response.content
        if len(body) > MAX_BYTES:
            raise RuntimeError(f"Sitemap response exceeded {MAX_BYTES} bytes")
        return body, str(response.url)
    raise RuntimeError("Too many sitemap redirects")


def _xml_locations(body: bytes) -> tuple[str, list[str]]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise RuntimeError("Invalid sitemap XML") from exc
    kind = root.tag.rsplit("}", 1)[-1].lower()
    locations = [
        str(node.text or "").strip()
        for node in root.findall(".//{*}loc")
        if str(node.text or "").strip()
    ]
    return kind, locations


def _robots_sitemaps(text: str, base_url: str) -> list[str]:
    found: list[str] = []
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip().lower() == "sitemap" and value.strip():
            found.append(urljoin(base_url, value.strip()))
    return found


def _normalized_page_url(value: str) -> str | None:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", "", parsed.query, ""))


async def collect_sitemap_inventory(base_url: str) -> dict[str, Any]:
    origin = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"
    candidates: list[str] = []
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": USER_AGENT}) as client:
        try:
            robots_body, _ = await _fetch(client, f"{origin}/robots.txt")
            candidates.extend(_robots_sitemaps(robots_body.decode("utf-8", "replace"), origin))
        except Exception as exc:
            errors.append(f"robots.txt: {exc}")
        candidates.extend([f"{origin}/sitemap.xml", f"{origin}/sitemap_index.xml"])

        queue = list(dict.fromkeys(candidates))
        seen: set[str] = set()
        successful: list[str] = []
        pages: set[str] = set()
        truncated = False
        while queue and len(seen) < MAX_SITEMAPS and len(pages) < MAX_URLS:
            sitemap_url = queue.pop(0)
            if sitemap_url in seen:
                continue
            seen.add(sitemap_url)
            try:
                body, resolved_url = await _fetch(client, sitemap_url)
                kind, locations = _xml_locations(body)
            except Exception as exc:
                errors.append(f"{sitemap_url}: {exc}")
                continue
            successful.append(resolved_url)
            if kind == "sitemapindex":
                queue.extend(location for location in locations if location not in seen)
                continue
            if kind != "urlset":
                errors.append(f"{resolved_url}: unsupported root element {kind}")
                continue
            for location in locations:
                normalized = _normalized_page_url(location)
                if normalized:
                    pages.add(normalized)
                if len(pages) >= MAX_URLS:
                    truncated = True
                    break
        if queue and len(seen) >= MAX_SITEMAPS:
            truncated = True

    return {
        "sitemap_urls": list(dict.fromkeys(successful)),
        "urls": sorted(pages),
        "truncated": truncated,
        "errors": errors,
    }


async def monitor_firm_sitemap(pif_id: str) -> dict[str, Any]:
    now = _utcnow()
    async with AsyncSessionLocal() as session:
        firm = await session.get(PifFirmRow, pif_id)
        if firm is None:
            raise ValueError("Firm record not found")
        website = _website_url(firm.canonical_website or firm.website)
        previous = (await session.execute(
            select(FirmSitemapSnapshotRow)
            .where(
                FirmSitemapSnapshotRow.pif_id == pif_id,
                FirmSitemapSnapshotRow.status == "completed",
            )
            .order_by(FirmSitemapSnapshotRow.fetched_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        previous_id = previous.id if previous else None
        previous_hash = previous.url_hash if previous else None
        previous_urls = list(previous.urls or []) if previous else []

    status = "missing"
    error: str | None = None
    inventory: dict[str, Any] = {"sitemap_urls": [], "urls": [], "truncated": False, "errors": []}
    if website:
        try:
            inventory = await collect_sitemap_inventory(website)
            status = "completed" if inventory["sitemap_urls"] else "missing"
            if status == "missing":
                error = "; ".join(inventory["errors"][:3]) or "No valid sitemap found"
        except Exception as exc:
            status = "failed"
            error = str(exc)[:1000]
    else:
        error = "No canonical website available"

    urls = list(inventory["urls"])
    prior_urls = set(previous_urls)
    current_urls = set(urls)
    added = sorted(current_urls - prior_urls) if previous_id and status == "completed" else []
    removed = sorted(prior_urls - current_urls) if previous_id and status == "completed" else []
    url_hash = hashlib.sha256("\n".join(urls).encode("utf-8")).hexdigest() if status == "completed" else None
    changed = (
        None
        if status != "completed" or previous_id is None
        else previous_hash != url_hash
    )
    snapshot_id = previous_id if previous_id and changed is False else uuid.uuid4().hex

    async with AsyncSessionLocal() as session:
        firm = await session.get(PifFirmRow, pif_id)
        if firm is None:
            raise ValueError("Firm record not found")
        if changed is not False:
            session.add(FirmSitemapSnapshotRow(
                id=snapshot_id,
                pif_id=pif_id,
                website=website,
                status=status,
                sitemap_urls=inventory["sitemap_urls"],
                urls=urls,
                url_hash=url_hash,
                added_urls=added,
                removed_urls=removed,
                truncated=bool(inventory["truncated"]),
                error=error,
                fetched_at=now,
            ))
        research = dict(firm.research_data) if isinstance(firm.research_data, dict) else {}
        summary = {
            "status": status,
            "provider": "possibleos_sitemap_monitor",
            "checked_at": now.isoformat(),
            "website": website,
            "sitemap_urls": inventory["sitemap_urls"],
            "url_count": len(urls),
            "changed": changed,
            "added_count": len(added),
            "removed_count": len(removed),
            "added_urls": added[:100],
            "removed_urls": removed[:100],
            "truncated": bool(inventory["truncated"]),
            "snapshot_id": snapshot_id,
            "error": error,
        }
        research["sitemap_monitor"] = summary
        firm.research_data = research
        firm.updated_at = now
        await session.commit()
        return summary


async def list_firm_sitemap_history(pif_id: str, *, limit: int = 20) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        firm = await session.get(PifFirmRow, pif_id)
        if firm is None:
            raise ValueError("Firm record not found")
        snapshots = (await session.execute(
            select(FirmSitemapSnapshotRow)
            .where(FirmSitemapSnapshotRow.pif_id == pif_id)
            .order_by(FirmSitemapSnapshotRow.fetched_at.desc())
            .limit(max(1, min(limit, 100)))
        )).scalars().all()
    return {
        "pif_id": pif_id,
        "items": [
            {
                "id": row.id,
                "website": row.website,
                "status": row.status,
                "sitemap_urls": row.sitemap_urls or [],
                "url_count": len(row.urls or []),
                "added_count": len(row.added_urls or []),
                "removed_count": len(row.removed_urls or []),
                "added_urls": row.added_urls or [],
                "removed_urls": row.removed_urls or [],
                "truncated": row.truncated,
                "error": row.error,
                "fetched_at": row.fetched_at.isoformat(),
            }
            for row in snapshots
        ],
    }
