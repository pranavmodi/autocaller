"""Outbound-comms logger. Writes one row to email_logs / sms_logs per
provider call. Failures here are swallowed — logging must never break
the actual send.

Both writers run synchronously and use the SYNC SQLAlchemy engine, so
they're callable from sync send-paths (Resend HTTPS POST, Twilio
`messages.create`) without an event loop. The async paths just
`asyncio.to_thread(...)` around them, same pattern the rest of the
codebase uses for sync services.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


_ENGINE: Optional[Engine] = None


def _engine() -> Engine:
    """Lazy sync engine, separate from the daemon's async engine. We
    open one connection per write — volumes are tiny."""
    global _ENGINE
    if _ENGINE is None:
        url = os.getenv("DATABASE_URL", "")
        if not url:
            raise RuntimeError("DATABASE_URL not set")
        # The async URL uses asyncpg; swap to the sync driver for this
        # logger so we don't have to await.
        sync_url = url.replace("+asyncpg", "+psycopg2").replace(
            "postgresql://", "postgresql+psycopg2://",
        )
        _ENGINE = create_engine(sync_url, pool_pre_ping=True, pool_size=2)
    return _ENGINE


def _excerpt(s: str, n: int = 100_000) -> str:
    """Retain the sent message body; the Text column is not an excerpt limit."""
    s = (s or "").strip()
    return s[:n]


def log_email(
    *,
    recipient_email: str,
    subject: str,
    body: str,
    message_type: str = "other",
    transport: str = "resend",
    message_id: Optional[str] = None,
    status: str = "sent",
    error: Optional[str] = None,
    pif_id: Optional[str] = None,
    call_id: Optional[str] = None,
    recipient_name: Optional[str] = None,
    brief_version: Optional[int] = None,
) -> None:
    """Insert one row into email_logs. Never raises."""
    try:
        with _engine().begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO email_logs (
                        id, pif_id, call_id, recipient_email, recipient_name,
                        subject, body_excerpt, message_type, transport,
                        message_id, status, error, sent_at, brief_version
                    ) VALUES (
                        :id, :pif_id, :call_id, :to, :to_name,
                        :subject, :body, :mtype, :transport,
                        :mid, :status, :err, :sent_at, :brief_version
                    )
                    """
                ),
                {
                    "id": uuid.uuid4().hex,
                    "pif_id": pif_id,
                    "call_id": call_id,
                    "to": (recipient_email or "").strip().lower()[:320],
                    "to_name": (recipient_name or None),
                    "subject": (subject or "")[:5000],
                    "body": _excerpt(body),
                    "mtype": (message_type or "other")[:64],
                    "transport": (transport or "resend")[:16],
                    "mid": (message_id or None),
                    "status": (status or "sent")[:16],
                    "err": error,
                    "sent_at": datetime.now(timezone.utc),
                    "brief_version": brief_version,
                },
            )
    except Exception as e:
        logger.warning("email_logs insert failed: %s", e)


def log_sms(
    *,
    recipient_phone: str,
    body: str,
    message_sid: Optional[str] = None,
    status: str = "sent",
    error: Optional[str] = None,
    pif_id: Optional[str] = None,
    call_id: Optional[str] = None,
    recipient_name: Optional[str] = None,
) -> None:
    """Insert one row into sms_logs. Never raises."""
    try:
        with _engine().begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO sms_logs (
                        id, pif_id, call_id, recipient_phone, recipient_name,
                        body, message_sid, status, error, sent_at
                    ) VALUES (
                        :id, :pif_id, :call_id, :to, :to_name,
                        :body, :sid, :status, :err, :sent_at
                    )
                    """
                ),
                {
                    "id": uuid.uuid4().hex,
                    "pif_id": pif_id,
                    "call_id": call_id,
                    "to": (recipient_phone or "").strip()[:32],
                    "to_name": (recipient_name or None),
                    "body": (body or "")[:5000],
                    "sid": (message_sid or None),
                    "status": (status or "sent")[:16],
                    "err": error,
                    "sent_at": datetime.now(timezone.utc),
                },
            )
    except Exception as e:
        logger.warning("sms_logs insert failed: %s", e)
