"""Bounded public-page reads for career verification; no form submission."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import random
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx


async def public_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.port not in (None, 443):
        raise ValueError("only public HTTPS URLs are allowed")
    # Reject literal private/loopback addresses synchronously. Besides closing the
    # SSRF path early, this avoids leaving a resolver thread behind on cancellation.
    try:
        literal = ipaddress.ip_address(parts.hostname)
    except ValueError:
        literal = None
    if literal is not None:
        if not literal.is_global:
            raise ValueError("non-public source address rejected")
        return url
    addresses = await asyncio.get_running_loop().getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("non-public source address rejected")
    return url


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.scripts = []
        self.links = []
        self.script = None
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "script":
            self.script = [] if values.get("type") == "application/ld+json" or values.get("id") == "__NEXT_DATA__" else None
            self.skip += 1
        elif tag == "style":
            self.skip += 1
        elif tag == "a" and values.get("href"):
            self.links.append(values["href"])

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            if tag == "script" and self.script is not None:
                try:
                    data = json.loads("".join(self.script))
                    if isinstance(data, dict) and "props" in data:
                        data = data.get("props", {}).get("pageProps", {}).get("apiData", data)
                    self.scripts.append(data)
                except (ValueError, TypeError):
                    pass
                self.script = None
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if self.script is not None:
            self.script.append(data)
        elif not self.skip:
            self.text.append(data)


def extract_page(html: str) -> str:
    # Public content APIs and some ATS endpoints return JSON rather than HTML.
    # Decode once before serializing with real Unicode characters so exact
    # evidence excerpts are compared to the document's meaning instead of its
    # wire-level escape sequences (for example, `\u00f3`).
    try:
        document = json.loads(html)
    except (json.JSONDecodeError, TypeError):
        document = None
    if isinstance(document, (dict, list)):
        return json.dumps(document, ensure_ascii=False)[:60000]
    parser = PageText()
    parser.feed(html)
    # ATS JSON carries dates, location restrictions and live application metadata.
    structured = json.dumps(parser.scripts, ensure_ascii=True)[:60000]
    return "\n".join([" ".join(" ".join(parser.text).split())[:18000], structured,
                      "Links: " + " ".join(parser.links[:150])])


async def fetch_page(url: str, *, attempts: int = 3) -> dict:
    last_error = None
    for attempt in range(attempts):
        try:
            current = url
            async with httpx.AsyncClient(timeout=25, trust_env=False, headers={"User-Agent": "PossibleOSCareerResearch/1.0"}) as client:
                for _ in range(6):
                    await public_url(current)
                    async with client.stream("GET", current) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            current = urljoin(current, response.headers["location"])
                            continue
                        if response.status_code == 429 or response.status_code >= 500:
                            raise RuntimeError(f"HTTP {response.status_code}")
                        if response.status_code not in {200, 404, 410}:
                            raise RuntimeError(f"unverified HTTP {response.status_code}")
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > 2_000_000:
                                raise RuntimeError("page exceeds 2MB verification limit")
                        return {"requested_url": url, "final_url": current, "http_status": response.status_code,
                                "content": extract_page(bytes(body).decode("utf-8", errors="replace"))}
                raise RuntimeError("redirect limit exceeded")
        except (httpx.HTTPError, RuntimeError, OSError, ValueError, KeyError) as exc:
            last_error = str(exc)
            if attempt + 1 < attempts:
                await asyncio.sleep(min(30, 2 ** (attempt + 1)) + random.random())
    raise RuntimeError(f"verification fetch failed for {url}: {last_error}")
