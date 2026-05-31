"""SEO and agent-optimization audit helpers for Possible Minds."""
from __future__ import annotations

import hashlib
import os
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.db import AsyncSessionLocal
from app.services.operator_notifications import create_operator_notification


DEFAULT_SITE_URL = "https://getpossibleminds.com"
MAX_FETCH_LIMIT = 50


@dataclass
class PageExtract:
    url: str
    status_code: int | None
    title: str
    description: str
    canonical: str
    h1: list[str]
    h2: list[str]
    links: list[str]
    images: list[dict[str, str]]
    schema_count: int
    text: str
    fetch_error: str | None = None


class SeoHTMLParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title_parts: list[str] = []
        self.description = ""
        self.canonical = ""
        self.h1: list[str] = []
        self.h2: list[str] = []
        self.links: list[str] = []
        self.images: list[dict[str, str]] = []
        self.schema_count = 0
        self.text_parts: list[str] = []
        self._tag_stack: list[str] = []
        self._capture_heading: str | None = None
        self._heading_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr = {k.lower(): (v or "") for k, v in attrs}
        self._tag_stack.append(tag)
        if tag == "meta":
            name = (attr.get("name") or attr.get("property") or "").lower()
            if name in {"description", "og:description"} and not self.description:
                self.description = attr.get("content", "").strip()
        elif tag == "link":
            if attr.get("rel", "").lower() == "canonical":
                self.canonical = urljoin(self.base_url, attr.get("href", "").strip())
        elif tag == "a":
            href = attr.get("href", "").strip()
            if href:
                self.links.append(urljoin(self.base_url, href))
        elif tag == "img":
            self.images.append({
                "src": urljoin(self.base_url, attr.get("src", "").strip()),
                "alt": attr.get("alt", "").strip(),
            })
        elif tag == "script":
            script_type = attr.get("type", "").lower()
            if script_type == "application/ld+json":
                self.schema_count += 1
        elif tag in {"h1", "h2"}:
            self._capture_heading = tag
            self._heading_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == self._capture_heading:
            text = _squash(" ".join(self._heading_parts))
            if text:
                if tag == "h1":
                    self.h1.append(text)
                elif tag == "h2":
                    self.h2.append(text)
            self._capture_heading = None
            self._heading_parts = []
        if self._tag_stack:
            self._tag_stack.pop()

    def handle_data(self, data: str) -> None:
        if not data.strip():
            return
        active = self._tag_stack[-1] if self._tag_stack else ""
        if active == "title":
            self.title_parts.append(data.strip())
        if active not in {"script", "style", "noscript"}:
            self.text_parts.append(data.strip())
        if self._capture_heading:
            self._heading_parts.append(data.strip())

    def extract(self, url: str, status_code: int | None, fetch_error: str | None = None) -> PageExtract:
        return PageExtract(
            url=url,
            status_code=status_code,
            title=_squash(" ".join(self.title_parts)),
            description=_squash(self.description),
            canonical=self.canonical,
            h1=self.h1,
            h2=self.h2,
            links=self.links,
            images=self.images,
            schema_count=self.schema_count,
            text=_squash(" ".join(self.text_parts)),
            fetch_error=fetch_error,
        )


def _squash(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _normalize_site_url(site_url: str | None) -> str:
    raw = (site_url or os.getenv("SEO_TARGET_SITE") or DEFAULT_SITE_URL).strip()
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if not parsed.netloc:
        return DEFAULT_SITE_URL
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _same_host(url: str, site_url: str) -> bool:
    return urlparse(url).netloc == urlparse(site_url).netloc


def _action_id(page_url: str, action_type: str) -> str:
    digest = hashlib.sha1(f"{page_url}|{action_type}".encode("utf-8")).hexdigest()[:12]
    return f"{action_type}:{digest}"


async def _fetch_text(client: httpx.AsyncClient, url: str) -> tuple[int | None, str, str | None]:
    try:
        resp = await client.get(url, follow_redirects=True)
        content_type = resp.headers.get("content-type", "")
        if resp.status_code >= 400:
            return resp.status_code, "", f"HTTP {resp.status_code}"
        if "text/html" not in content_type and "xml" not in content_type and "text/plain" not in content_type:
            return resp.status_code, "", f"unsupported content type {content_type[:80]}"
        return resp.status_code, resp.text, None
    except httpx.HTTPError as exc:
        return None, "", str(exc)


async def _discover_urls(site_url: str, limit: int) -> list[str]:
    sitemap_url = f"{site_url}/sitemap.xml"
    urls: list[str] = []
    async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": "PossibleOS-SEO-Audit/1.0"}) as client:
        _status, text, error = await _fetch_text(client, sitemap_url)
    if text and not error:
        try:
            root = ET.fromstring(text.encode("utf-8"))
            for loc in root.findall(".//{*}loc"):
                if loc.text:
                    url = loc.text.strip()
                    if _same_host(url, site_url):
                        urls.append(url)
        except ET.ParseError:
            urls = []
    fallback = [site_url, f"{site_url}/consult", f"{site_url}/blog"]
    for url in fallback:
        if url not in urls:
            urls.insert(0, url)
    clean: list[str] = []
    for url in urls:
        parsed = urlparse(url)
        if not parsed.scheme.startswith("http"):
            continue
        if parsed.path.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf")):
            continue
        normalized = url.rstrip("/")
        if normalized not in clean:
            clean.append(normalized)
        if len(clean) >= limit:
            break
    return clean


async def _fetch_page(client: httpx.AsyncClient, url: str) -> PageExtract:
    status, html, error = await _fetch_text(client, url)
    parser = SeoHTMLParser(url)
    if html and not error:
        parser.feed(html)
    return parser.extract(url, status, error)


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text or ""))


def _has_any(text: str, terms: list[str]) -> bool:
    lower = text.lower()
    return any(term.lower() in lower for term in terms)


def _score_page(page: PageExtract, site_url: str) -> dict[str, Any]:
    text = page.text
    lower = text.lower()
    word_count = _word_count(text)
    internal_links = [link for link in page.links if _same_host(link, site_url)]
    consult_links = [link for link in internal_links if "/consult" in urlparse(link).path]
    missing_image_alt = sum(1 for image in page.images if image.get("src") and not image.get("alt"))
    service_terms = [
        "personal injury",
        "healthcare",
        "ai",
        "automation",
        "workflow",
        "intake",
        "email triage",
        "voice ai",
        "chatbot",
    ]
    proof_terms = ["precise imaging", "500", "hours", "twilio", "autorespond", "case study"]
    question_terms = ["what", "how", "why", "faq", "question", "answer"]

    checks = {
        "title": 30 <= len(page.title) <= 70,
        "description": 70 <= len(page.description) <= 180,
        "h1": len(page.h1) == 1,
        "depth": word_count >= 450,
        "consult_link": bool(consult_links),
        "schema": page.schema_count > 0,
        "internal_links": len(set(internal_links)) >= 3,
        "proof": _has_any(text, proof_terms),
        "service_clarity": _has_any(text, service_terms),
        "answer_format": _has_any(" ".join(page.h2) + " " + lower, question_terms),
    }
    seo_score = round(100 * sum(checks[key] for key in [
        "title", "description", "h1", "depth", "consult_link", "schema", "internal_links",
    ]) / 7)
    aeo_score = round(100 * sum(checks[key] for key in [
        "proof", "service_clarity", "answer_format", "consult_link", "schema",
    ]) / 5)
    overall_score = round((seo_score + aeo_score) / 2)

    issues: list[str] = []
    opportunities: list[str] = []
    actions: list[dict[str, Any]] = []

    def add_action(action_type: str, priority: str, title: str, rationale: str, suggested_change: str, category: str) -> None:
        actions.append({
            "id": _action_id(page.url, action_type),
            "action_type": action_type,
            "priority": priority,
            "title": title,
            "rationale": rationale,
            "suggested_change": suggested_change,
            "category": category,
            "page_url": page.url,
        })

    if page.fetch_error:
        issues.append(f"Fetch failed: {page.fetch_error}")
        add_action(
            "fix_fetch",
            "high",
            f"Fix crawl access for {urlparse(page.url).path or '/'}",
            "The audit could not fetch this page, which means search engines and AI agents may also have trouble reading it.",
            "Check page availability, redirects, robots rules, and server errors.",
            "technical",
        )
    if not checks["title"]:
        issues.append("Title is missing or not in the recommended length range.")
        add_action(
            "improve_title",
            "normal",
            f"Improve title for {urlparse(page.url).path or '/'}",
            "Search results and AI summaries need a clear page title that states the audience and value.",
            "Rewrite the title to name Possible Minds, the buyer category, and the concrete workflow outcome.",
            "seo",
        )
    if not checks["description"]:
        issues.append("Meta description is missing or weak.")
        add_action(
            "improve_description",
            "normal",
            f"Improve meta description for {urlparse(page.url).path or '/'}",
            "A strong description helps search snippets and agent summaries understand who the page is for.",
            "Add a 1-2 sentence description with the target buyer, workflow pain, and consult path.",
            "seo",
        )
    if not checks["h1"]:
        issues.append("Page should have exactly one clear H1.")
        add_action(
            "fix_h1",
            "normal",
            f"Clarify H1 for {urlparse(page.url).path or '/'}",
            "One clear H1 makes the page easier for crawlers, readers, and AI agents to classify.",
            "Use one H1 that names the service or concrete offer instead of a vague headline.",
            "seo",
        )
    if not checks["depth"]:
        opportunities.append("Page may be too thin for competitive search and agent answers.")
        add_action(
            "add_depth",
            "normal",
            f"Add buyer-useful detail to {urlparse(page.url).path or '/'}",
            "Thin pages are harder to rank and harder for AI agents to quote or recommend.",
            "Add concrete sections for problem, workflow, implementation path, proof, risks, and expected results.",
            "content",
        )
    if not checks["consult_link"]:
        issues.append("No obvious consult link found.")
        add_action(
            "add_consult_link",
            "high",
            f"Add consult path to {urlparse(page.url).path or '/'}",
            "The lead generation loop needs every useful page to expose the next conversion step.",
            "Add a contextual link to https://getpossibleminds.com/consult near the top and bottom of the page.",
            "conversion",
        )
    if not checks["schema"]:
        opportunities.append("Structured data is missing.")
        add_action(
            "add_schema",
            "normal",
            f"Add structured data to {urlparse(page.url).path or '/'}",
            "Schema helps search engines and AI agents understand the page type, organization, and answer content.",
            "Add Organization, WebPage, FAQPage, or Article JSON-LD as appropriate.",
            "agent_optimization",
        )
    if not checks["proof"]:
        opportunities.append("Page does not clearly surface proof points.")
        add_action(
            "add_proof",
            "high",
            f"Add proof points to {urlparse(page.url).path or '/'}",
            "AI agents and buyers need specific evidence before trusting a bespoke AI automation vendor.",
            "Mention relevant proof, such as Precise Imaging autoresponders, email triage, website chatbot, intake automation, and measured time saved where accurate.",
            "agent_optimization",
        )
    if not checks["answer_format"]:
        opportunities.append("Page lacks direct answer-style sections.")
        add_action(
            "add_answer_sections",
            "normal",
            f"Add answer sections to {urlparse(page.url).path or '/'}",
            "Agent engines favor pages that answer concrete buyer questions in extractable sections.",
            "Add short Q&A sections for who this is for, what system gets built, how implementation works, timeline, cost factors, and risks.",
            "agent_optimization",
        )
    if missing_image_alt:
        opportunities.append(f"{missing_image_alt} images are missing alt text.")
        add_action(
            "add_image_alt",
            "low",
            f"Add image alt text to {urlparse(page.url).path or '/'}",
            "Missing alt text weakens accessibility and page interpretation.",
            "Add concise, descriptive alt text for product screenshots, diagrams, and proof images.",
            "technical",
        )

    return {
        "url": page.url,
        "status_code": page.status_code,
        "title": page.title,
        "description": page.description,
        "canonical": page.canonical,
        "h1": page.h1,
        "h2": page.h2[:8],
        "word_count": word_count,
        "internal_link_count": len(set(internal_links)),
        "consult_link_count": len(consult_links),
        "schema_count": page.schema_count,
        "missing_image_alt_count": missing_image_alt,
        "seo_score": seo_score,
        "aeo_score": aeo_score,
        "score": overall_score,
        "issues": issues,
        "opportunities": opportunities,
        "actions": actions,
    }


async def run_seo_audit(site_url: str | None = None, limit: int = 20) -> dict[str, Any]:
    site = _normalize_site_url(site_url)
    fetch_limit = max(1, min(limit, MAX_FETCH_LIMIT))
    urls = await _discover_urls(site, fetch_limit)
    async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": "PossibleOS-SEO-Audit/1.0"}) as client:
        pages = [await _fetch_page(client, url) for url in urls]
    scored = [_score_page(page, site) for page in pages]
    issue_counts = Counter(issue for page in scored for issue in page["issues"])
    actions = [action for page in scored for action in page["actions"]]
    priority_order = {"high": 0, "normal": 1, "low": 2}
    actions.sort(key=lambda action: (priority_order.get(action["priority"], 1), action["page_url"], action["action_type"]))
    avg_seo = round(sum(page["seo_score"] for page in scored) / len(scored)) if scored else 0
    avg_aeo = round(sum(page["aeo_score"] for page in scored) / len(scored)) if scored else 0
    return {
        "site_url": site,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "page_count": len(scored),
            "avg_seo_score": avg_seo,
            "avg_aeo_score": avg_aeo,
            "avg_score": round((avg_seo + avg_aeo) / 2),
            "issue_counts": dict(issue_counts.most_common(12)),
            "action_count": len(actions),
            "high_priority_action_count": sum(1 for action in actions if action["priority"] == "high"),
            "top_actions": actions[:10],
        },
        "pages": scored,
        "actions": actions,
    }


async def generate_seo_action_notifications(
    *,
    site_url: str | None = None,
    limit: int = 20,
    action_limit: int = 20,
) -> dict[str, Any]:
    audit = await run_seo_audit(site_url=site_url, limit=limit)
    selected_actions = audit["actions"][: max(1, min(action_limit, 50))]
    created: list[dict[str, Any]] = []
    async with AsyncSessionLocal() as session:
        for action in selected_actions:
            row = await create_operator_notification(
                session,
                notification_type="seo_action",
                title=action["title"],
                body=action["rationale"],
                source_type="seo_audit",
                source_id=action["id"],
                priority=action["priority"],
                stimulus={
                    "page_url": action["page_url"],
                    "category": action["category"],
                    "action_type": action["action_type"],
                    "site_url": audit["site_url"],
                },
                context={
                    "site_url": audit["site_url"],
                    "page_url": action["page_url"],
                    "category": action["category"],
                    "action_domain": "seo_agent_optimization",
                },
                suggested_action={
                    "kind": "seo_action",
                    "label": "Complete SEO/AEO improvement",
                    "href": "/seo",
                    "reasoning": action["rationale"],
                    "suggested_change": action["suggested_change"],
                    "category": action["category"],
                    "requires_human_review": True,
                },
            )
            created.append({
                "notification_id": row.id,
                "status": row.status,
                "action": action,
            })
        await session.commit()
    return {
        "created": created,
        "created_count": len(created),
        "audit": audit,
    }
