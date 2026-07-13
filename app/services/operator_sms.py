"""Operator alerts — WhatsApp first (openclaw CLI), Telnyx SMS fallback.

Shared helper for pinging the operator when something needs attention
(workshop registrations, bookings, ...). WhatsApp is the primary channel:
the operator's number is Indian (+91) and Telnyx SMS to India fails without
DLT/alpha-sender registration (error 40306), which is also why the older
inline consult SMS alerts silently fail. Best-effort: never raises; returns
False when unconfigured or every channel fails so callers can log and move
on. Consults/dashboard predate this module and still carry inline copies.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess

import httpx

logger = logging.getLogger(__name__)


async def notify_operator(text: str, *, tag: str = "operator-alert") -> bool:
    """Alert the operator: WhatsApp via openclaw CLI, then Telnyx SMS."""
    to = os.getenv("OPERATOR_WHATSAPP", "+918287149638").strip()
    if to:
        def _send() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["openclaw", "message", "send", "--channel", "whatsapp",
                 "-t", to, "--message", text[:1500]],
                capture_output=True, text=True, timeout=45, check=False,
            )

        try:
            proc = await asyncio.to_thread(_send)
            if proc.returncode == 0:
                logger.info("[%s] WhatsApp sent to %s", tag, to)
                return True
            logger.warning(
                "[%s] WhatsApp failed rc=%s: %s", tag, proc.returncode,
                (proc.stderr or proc.stdout or "")[-200:],
            )
        except Exception as exc:
            logger.warning("[%s] WhatsApp send failed: %s", tag, type(exc).__name__)
    return await notify_operator_sms(text, tag=tag)


async def notify_operator_sms(text: str, *, tag: str = "operator-sms") -> bool:
    """Send `text` to NOTIFY_NUMBER via Telnyx. Returns True on success."""
    from app.services.twilio_sms_service import get_notify_number

    notify = get_notify_number()
    api_key = os.getenv("TELNYX_API_KEY", "").strip()
    from_number = os.getenv("TELNYX_FROM_NUMBER", "").strip()
    if not (notify and api_key and from_number):
        logger.info("[%s] skipped — NOTIFY_NUMBER/TELNYX_* not set", tag)
        return False
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.telnyx.com/v2/messages",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": from_number,
                    "to": notify,
                    "text": text[:1500],
                    "type": "SMS",
                },
            )
        if resp.status_code >= 300:
            logger.warning("[%s] Telnyx HTTP %s: %s", tag, resp.status_code, resp.text[:200])
            return False
        logger.info("[%s] sent to %s", tag, notify)
        return True
    except Exception as exc:
        logger.warning("[%s] send failed: %s", tag, type(exc).__name__)
        return False
