"""Per-recipient email composer.

Calls the openclaw LLM gateway with the blog-outreach-composer skill
loaded as a system prompt and a structured JSON payload as the user
message. The LLM returns JSON with subject/preheader/body_html/plaintext
/reasoning; we validate, return as a dataclass.

The composer does NOT substitute the tracking URL — it returns the
literal `{{TRACKED_POST_URL}}` placeholder, and the send pipeline swaps
it in just before send. This keeps the LLM honest about what it produced
and lets the operator preview the exact body that will go out.

All model work goes through the shared native OpenClaw RPC client."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.services.llm_gateway import LLMGatewayError, call_skill_json, clear_skill_cache


# --- Config ----------------------------------------------------------------

DEFAULT_SKILL_PATH = Path(__file__).resolve().parents[2] / ".claude/skills/blog-outreach-composer/SKILL.md"
SKILL_PATH = Path(os.getenv("BLOG_OUTREACH_SKILL_PATH", str(DEFAULT_SKILL_PATH)))

COMPOSER_MODEL = os.getenv("BLOG_OUTREACH_MODEL", "openclaw/main")
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


def reload_skill() -> None:
    """Force the skill file to be re-read on next compose call. Useful
    when iterating on the SKILL.md without restarting the daemon."""
    clear_skill_cache()


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
    model_id = model or COMPOSER_MODEL
    try:
        result = await call_skill_json(
            skill_path=SKILL_PATH,
            payload=payload.to_dict(),
            required_fields=list(_REQUIRED_FIELDS),
            model=model_id,
            timeout_s=COMPOSER_TIMEOUT_S,
            max_tokens=COMPOSER_MAX_TOKENS,
            retries=COMPOSER_RETRIES,
            schema_repair_retries=1,
            lane=os.getenv("OPENCLAW_RPC_INTERACTIVE_LANE", "possibleos-interactive"),
            allow_tools=False,
        )
    except LLMGatewayError as exc:
        raise ComposerError(str(exc)) from exc
    parsed = result.parsed
    _validate(parsed, payload)
    return ComposedEmail(
        subject=parsed["subject"].strip(),
        preheader=parsed["preheader"].strip(),
        body_html=parsed["body_html"],
        plaintext=parsed["plaintext"],
        reasoning=(parsed.get("reasoning") or "").strip(),
        model=model_id,
        raw_response=result.raw_response,
    )


def substitute_tracked_url(body: str, tracked_url: str) -> str:
    """Swap the placeholder for the real tracked URL. Used by both the
    HTML body and the plaintext at send time. Idempotent."""
    return body.replace(TRACKED_URL_PLACEHOLDER, tracked_url)
