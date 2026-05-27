"""Fetch a Possible Minds blog post's structured metadata for outreach.

Reads the canonical post entry from the local webnew repo's blog index
(`app/blog/page.tsx`), then optionally enriches with a few paragraphs of
body text by fetching the live URL. Excerpts are optional — if the live
fetch fails (offline, redeploy in flight, post not yet live), the
composer still gets title + description + category + tags + readTime.

Path to the webnew repo is configurable via WEBNEW_REPO_PATH env var
(default: /home/pranav/getpossibleminds). The live URL is built from
WEBSITE_BASE_URL (default: https://getpossibleminds.com).
"""
from __future__ import annotations

import logging
import os
import re
import html
from dataclasses import dataclass, field, asdict
from typing import Optional

import httpx


logger = logging.getLogger(__name__)


WEBNEW_REPO_PATH = os.getenv("WEBNEW_REPO_PATH", "/home/pranav/getpossibleminds")
WEBSITE_BASE_URL = os.getenv("WEBSITE_BASE_URL", "https://getpossibleminds.com").rstrip("/")


@dataclass
class BlogPost:
    slug: str
    url: str
    title: str
    description: str
    category: str = ""
    tags: list[str] = field(default_factory=list)
    read_time: str = ""
    date: str = ""
    excerpts: list[str] = field(default_factory=list)

    def to_composer_input(self) -> dict:
        """Shape the composer SKILL.md expects under the `post` key."""
        return {
            "title": self.title,
            "slug": self.slug,
            "description": self.description,
            "category": self.category,
            "tags": self.tags,
            "read_time": self.read_time,
            "excerpts": self.excerpts,
        }


class BlogPostNotFound(Exception):
    pass


def _index_path() -> str:
    return os.path.join(WEBNEW_REPO_PATH, "app", "blog", "page.tsx")


def _parse_index_entry(index_src: str, slug: str) -> dict:
    """Find the JS object literal in the `posts` array whose href is /blog/<slug>.
    Returns a dict with parsed string/list fields; raises BlogPostNotFound if missing.

    The TSX index uses a fixed shape (one object per post, fields on their own lines).
    We slice from the opening `{` of the matching entry to its closing `},` and run
    field-level regexes — robust against added fields, ignores order."""
    # Each post object opens with `{` on its own line and contains `href: "/blog/<slug>"`.
    # Find the opening `{` that precedes the matching href line.
    href_pattern = re.compile(
        r"\{\s*[^{}]*?href:\s*[\"'`]/blog/" + re.escape(slug) + r"[\"'`][\s\S]*?\n\s*\},",
        re.MULTILINE,
    )
    m = href_pattern.search(index_src)
    if not m:
        raise BlogPostNotFound(f"No entry for /blog/{slug} in {_index_path()}")
    block = m.group(0)

    def _str_field(name: str) -> str:
        # Matches: name: "value" | 'value' | `value`. Captures the inner value.
        # Allows multi-line strings via [\s\S] inside the quotes.
        pat = re.compile(
            rf"{name}:\s*([\"'`])([\s\S]*?)\1\s*,",
            re.MULTILINE,
        )
        mm = pat.search(block)
        return mm.group(2).strip() if mm else ""

    def _list_field(name: str) -> list[str]:
        # Matches: name: [ "a", "b", 'c' ]
        pat = re.compile(rf"{name}:\s*\[([\s\S]*?)\]", re.MULTILINE)
        mm = pat.search(block)
        if not mm:
            return []
        inner = mm.group(1)
        items = re.findall(r"[\"'`]([^\"'`]+)[\"'`]", inner)
        return [s.strip() for s in items if s.strip()]

    return {
        "title": _str_field("title"),
        "description": _str_field("description"),
        "category": _str_field("category"),
        "date": _str_field("date"),
        "read_time": _str_field("readTime"),
        "tags": _list_field("tags"),
    }


# --- Live-fetch excerpts ---------------------------------------------------

# Strip common boilerplate paragraphs the navigation/footer renders. The
# `<article>` element scopes the body but if extraction widens we still
# filter these out.
_EXCERPT_DENYLIST_PATTERNS = (
    re.compile(r"book a free strategy call", re.I),
    re.compile(r"^pranav modi", re.I),
    re.compile(r"min read$", re.I),
    re.compile(r"^home\b", re.I),
)


def _looks_like_boilerplate(text: str) -> bool:
    if len(text) < 60:
        return True
    return any(p.search(text) for p in _EXCERPT_DENYLIST_PATTERNS)


_ARTICLE_OPEN_RE = re.compile(r"<article\b[^>]*>", re.I)
_ARTICLE_CLOSE_RE = re.compile(r"</article>", re.I)
_P_BLOCK_RE = re.compile(r"<p\b[^>]*>([\s\S]*?)</p>", re.I)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _extract_excerpts_from_html(page_html: str, max_excerpts: int = 3) -> list[str]:
    """Pull the first 2-3 substantive `<p>` blocks from the `<article>` element.
    Best-effort; returns an empty list if nothing usable found."""
    open_m = _ARTICLE_OPEN_RE.search(page_html)
    close_m = _ARTICLE_CLOSE_RE.search(page_html, open_m.end() if open_m else 0)
    if open_m and close_m:
        scope = page_html[open_m.end():close_m.start()]
    else:
        scope = page_html

    excerpts: list[str] = []
    for m in _P_BLOCK_RE.finditer(scope):
        inner = m.group(1)
        text = _TAG_STRIP_RE.sub(" ", inner)
        text = html.unescape(text)
        text = _WS_RE.sub(" ", text).strip()
        if not text or _looks_like_boilerplate(text):
            continue
        excerpts.append(text)
        if len(excerpts) >= max_excerpts:
            break
    return excerpts


async def _fetch_excerpts(url: str, timeout: float = 10.0) -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "autocaller-blog-fetch/1.0"})
        if resp.status_code != 200:
            logger.info("blog excerpt fetch %s returned %s", url, resp.status_code)
            return []
        return _extract_excerpts_from_html(resp.text)
    except Exception as e:
        logger.info("blog excerpt fetch %s failed: %s", url, e)
        return []


# --- Public API ------------------------------------------------------------

def fetch_post_sync(slug: str) -> BlogPost:
    """Read structured metadata for a blog post by slug (no excerpts)."""
    try:
        with open(_index_path(), "r", encoding="utf-8") as f:
            src = f.read()
    except FileNotFoundError as e:
        raise BlogPostNotFound(
            f"Webnew repo not found at {WEBNEW_REPO_PATH} — set WEBNEW_REPO_PATH"
        ) from e
    meta = _parse_index_entry(src, slug)
    return BlogPost(
        slug=slug,
        url=f"{WEBSITE_BASE_URL}/blog/{slug}",
        title=meta["title"],
        description=meta["description"],
        category=meta["category"],
        tags=meta["tags"],
        read_time=meta["read_time"],
        date=meta["date"],
        excerpts=[],
    )


async def fetch_post(slug: str, *, with_excerpts: bool = True) -> BlogPost:
    """Read structured metadata + optional live-page excerpts.

    Excerpt fetch failures are non-fatal — composer still works without them."""
    post = fetch_post_sync(slug)
    if with_excerpts:
        post.excerpts = await _fetch_excerpts(post.url)
    return post


def list_local_slugs() -> list[str]:
    """All blog-post slugs known to the local webnew repo. Useful for the
    CLI's `outreach campaigns create` autocomplete + audit."""
    try:
        with open(_index_path(), "r", encoding="utf-8") as f:
            src = f.read()
    except FileNotFoundError:
        return []
    return re.findall(r"href:\s*[\"'`]/blog/([a-z0-9][a-z0-9\-]*)[\"'`]", src)
