"""Per-recipient email composer.

Calls the openclaw LLM gateway with the blog-outreach-composer skill
loaded as a system prompt and a structured JSON payload as the user
message. The LLM returns JSON with subject/preheader/body_html/plaintext
/reasoning; we validate, return as a dataclass.

The composer does NOT substitute the tracking URL — it returns the
literal `{{TRACKED_POST_URL}}` placeholder, and the send pipeline swaps
it in just before send. This keeps the LLM honest about what it produced
and lets the operator preview the exact body that will go out.

Gateway URL + token are read from the openclaw config when not set in
the environment. Mission Control follows the same pattern."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx


logger = logging.getLogger(__name__)


# --- Config ----------------------------------------------------------------

DEFAULT_SKILL_PATH = Path(__file__).resolve().parents[2] / ".claude/skills/blog-outreach-composer/SKILL.md"
SKILL_PATH = Path(os.getenv("BLOG_OUTREACH_SKILL_PATH", str(DEFAULT_SKILL_PATH)))

GATEWAY_URL = os.getenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789/v1/chat/completions")
OPENCLAW_CONFIG_PATH = Path(os.getenv("OPENCLAW_CONFIG_PATH", "/root/.openclaw/openclaw.json"))

COMPOSER_MODEL = os.getenv("BLOG_OUTREACH_MODEL", "openclaw")
COMPOSER_TIMEOUT_S = int(os.getenv("BLOG_OUTREACH_TIMEOUT_S", "180"))
COMPOSER_MAX_TOKENS = int(os.getenv("BLOG_OUTREACH_MAX_TOKENS", "2000"))
COMPOSER_RETRIES = int(os.getenv("BLOG_OUTREACH_RETRIES", "3"))

# The literal placeholder the SKILL.md tells the LLM to emit. The send
# pipeline substitutes the real tracked URL just before sending.
TRACKED_URL_PLACEHOLDER = "{{TRACKED_POST_URL}}"


# --- Public types ----------------------------------------------------------

@dataclass
class ComposedEmail:
    subject: str
    preheader: str
    body_html: str
    plaintext: str
    reasoning: str
    model: str
    raw_response: str = ""  # original JSON the LLM returned, for debugging


@dataclass
class ComposerInput:
    """Payload shape the SKILL.md expects under the user message."""
    post: dict
    recipient: dict
    firm: dict
    sender: dict
    tracked_post_url: str  # the actual tracked URL, just for the LLM's "context" field
    intent: str = "share"

    def to_dict(self) -> dict:
        return {
            "post": self.post,
            "recipient": self.recipient,
            "firm": self.firm,
            "sender": self.sender,
            "tracked_post_url": self.tracked_post_url,
            "intent": self.intent,
        }


class ComposerError(Exception):
    pass


# --- Gateway token ---------------------------------------------------------

_token_cache: Optional[str] = None


def _gateway_token() -> str:
    """Resolve the openclaw gateway bearer token.

    Order: OPENCLAW_GATEWAY_TOKEN env > gateway.auth.token in openclaw.json.
    Cached after first read."""
    global _token_cache
    if _token_cache:
        return _token_cache
    env_tok = os.getenv("OPENCLAW_GATEWAY_TOKEN", "").strip()
    if env_tok:
        _token_cache = env_tok
        return env_tok
    try:
        with open(OPENCLAW_CONFIG_PATH, "r") as f:
            cfg = json.load(f)
        tok = cfg.get("gateway", {}).get("auth", {}).get("token", "").strip()
        if not tok:
            raise ComposerError(
                f"No gateway.auth.token in {OPENCLAW_CONFIG_PATH} and "
                "OPENCLAW_GATEWAY_TOKEN env not set"
            )
        _token_cache = tok
        return tok
    except FileNotFoundError as e:
        raise ComposerError(
            f"openclaw config not found at {OPENCLAW_CONFIG_PATH} — "
            "set OPENCLAW_GATEWAY_TOKEN env"
        ) from e


# --- Skill loader ----------------------------------------------------------

_skill_cache: Optional[str] = None


def _load_skill() -> str:
    global _skill_cache
    if _skill_cache:
        return _skill_cache
    try:
        with open(SKILL_PATH, "r", encoding="utf-8") as f:
            _skill_cache = f.read()
        return _skill_cache
    except FileNotFoundError as e:
        raise ComposerError(f"SKILL.md not found at {SKILL_PATH}") from e


def reload_skill() -> None:
    """Force the skill file to be re-read on next compose call. Useful
    when iterating on the SKILL.md without restarting the daemon."""
    global _skill_cache
    _skill_cache = None


# --- JSON extraction -------------------------------------------------------

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.MULTILINE)


def _extract_json(content: str) -> dict:
    """LLMs sometimes wrap JSON in ``` fences despite being told not to.
    Strip those, then parse."""
    raw = content.strip()
    if raw.startswith("```"):
        m = _JSON_FENCE_RE.search(raw)
        if m:
            raw = m.group(1).strip()
    # Some models prepend a sentence — find the first { and the matching last }.
    if not raw.startswith("{"):
        first = raw.find("{")
        last = raw.rfind("}")
        if first >= 0 and last > first:
            raw = raw[first : last + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ComposerError(f"Composer returned non-JSON: {e}; first 200 chars: {raw[:200]!r}")


_REQUIRED_FIELDS = ("subject", "preheader", "body_html", "plaintext")


def _validate(parsed: dict, payload: ComposerInput) -> None:
    missing = [f for f in _REQUIRED_FIELDS if not parsed.get(f, "").strip()]
    if missing:
        raise ComposerError(f"Composer JSON missing required fields: {missing}")
    # The body and plaintext must both contain the literal placeholder so the
    # send pipeline can substitute the real tracked URL. The SKILL.md is
    # explicit about this — flag if the LLM ignored it.
    if TRACKED_URL_PLACEHOLDER not in parsed["body_html"]:
        raise ComposerError(
            f"body_html missing literal placeholder {TRACKED_URL_PLACEHOLDER}"
        )
    if TRACKED_URL_PLACEHOLDER not in parsed["plaintext"]:
        raise ComposerError(
            f"plaintext missing literal placeholder {TRACKED_URL_PLACEHOLDER}"
        )
    # Guard: LLM must not inline the actual post URL (would bypass tracking).
    bare_url = payload.tracked_post_url  # at this layer this is the tracked URL
    real_post_url = f"https://getpossibleminds.com/blog/{payload.post.get('slug', '')}"
    if real_post_url and real_post_url in parsed["body_html"]:
        raise ComposerError(
            f"body_html contains untracked post URL {real_post_url}; "
            f"must use {TRACKED_URL_PLACEHOLDER}"
        )


# --- The compose call ------------------------------------------------------

async def compose(payload: ComposerInput, *, model: str | None = None) -> ComposedEmail:
    """One-shot LLM call to compose a personalized blog-share email.

    Returns a ComposedEmail with placeholder URLs still embedded — the
    caller is responsible for substituting `{{TRACKED_POST_URL}}` before
    sending."""
    skill = _load_skill()
    model_id = model or COMPOSER_MODEL
    user_payload = json.dumps(payload.to_dict(), indent=2, ensure_ascii=False)

    messages = [
        {"role": "system", "content": skill},
        {"role": "user", "content": user_payload},
    ]
    body = {
        "model": model_id,
        "messages": messages,
        "max_tokens": COMPOSER_MAX_TOKENS,
    }

    last_error: Exception | None = None
    for attempt in range(1, COMPOSER_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=COMPOSER_TIMEOUT_S, verify=False) as client:
                resp = await client.post(
                    GATEWAY_URL,
                    headers={
                        "Authorization": f"Bearer {_gateway_token()}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
            if resp.status_code in (502, 503, 504):
                raise httpx.HTTPStatusError(
                    f"gateway transient {resp.status_code}",
                    request=resp.request, response=resp,
                )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            if not content:
                raise ComposerError("gateway returned empty content")
            parsed = _extract_json(content)
            _validate(parsed, payload)
            return ComposedEmail(
                subject=parsed["subject"].strip(),
                preheader=parsed["preheader"].strip(),
                body_html=parsed["body_html"],
                plaintext=parsed["plaintext"],
                reasoning=(parsed.get("reasoning") or "").strip(),
                model=model_id,
                raw_response=content,
            )
        except (httpx.HTTPStatusError, httpx.ReadTimeout, httpx.ConnectError,
                httpx.RemoteProtocolError) as e:
            last_error = e
            logger.warning("compose attempt %d failed (network): %s", attempt, e)
            if attempt < COMPOSER_RETRIES:
                await asyncio.sleep(2 ** (attempt - 1))
        except ComposerError as e:
            # Validation / format errors aren't usually fixed by retrying the
            # same prompt, but we try once more in case the LLM was sloppy.
            last_error = e
            logger.warning("compose attempt %d failed (format): %s", attempt, e)
            if attempt < COMPOSER_RETRIES:
                await asyncio.sleep(1)
    raise ComposerError(f"compose failed after {COMPOSER_RETRIES} attempts: {last_error}")


def substitute_tracked_url(body: str, tracked_url: str) -> str:
    """Swap the placeholder for the real tracked URL. Used by both the
    HTML body and the plaintext at send time. Idempotent."""
    return body.replace(TRACKED_URL_PLACEHOLDER, tracked_url)
