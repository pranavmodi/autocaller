import asyncio
import logging
import os
from pathlib import Path

from app.services.llm_gateway import call_skill_json, close_gateway_rpc_clients

logger = logging.getLogger(__name__)

_SKILL_PATH = Path(__file__).resolve().parent / "skills/phone-sim-reply/SKILL.md"


async def _generate_reply(user_text: str):
    """Run one simulator turn and close the RPC socket with its event loop."""
    try:
        return await call_skill_json(
            skill_path=_SKILL_PATH,
            payload={"user_text": (user_text or "").strip()},
            required_fields=["reply"],
            model=os.getenv("PHONE_SIM_REPLY_MODEL", "openclaw/neo"),
            max_tokens=int(os.getenv("PHONE_SIM_REPLY_MAX_TOKENS", "80")),
            allow_tools=False,
        )
    finally:
        await close_gateway_rpc_clients()


def generate_ai_reply(user_text: str) -> str:
    """Produce a short, friendly phone reply via the OpenClaw proxy gateway (OAuth).

    Used only by the local voice-call simulator, which calls this from a worker
    thread — so spinning a fresh event loop with asyncio.run is safe here.
    """
    try:
        result = asyncio.run(_generate_reply(user_text))
        return str(result.parsed.get("reply", "")).strip()
    except Exception as e:  # simulator should never hard-fail on a reply
        logger.warning("generate_ai_reply gateway call failed: %s", e)
        return "Sorry, could you say that again?"
