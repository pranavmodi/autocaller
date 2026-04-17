"""Post-call Whisper transcription.

After a recording is downloaded, this runs gpt-4o-transcribe on the MP3
to produce a more accurate transcript than the live Gemini/OpenAI STT.
The result is stored in `call_logs.whisper_transcript` and used by the
judge when available.

Runs in the judge loop alongside scoring — same cadence, same background
task. Only processes calls that have a recording but no whisper_transcript.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from openai import AsyncOpenAI
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.db.models import CallLogRow
from app.services.recording_service import resolve_recording_path

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4o-transcribe"


async def transcribe_recording(call_id: str, *, client: Optional[AsyncOpenAI] = None) -> Optional[str]:
    """Transcribe a call's recording via Whisper. Returns the text or None."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(CallLogRow).where(CallLogRow.call_id == call_id)
        )
        row = result.scalar_one_or_none()

    if not row or not row.recording_path:
        return None

    abs_path = resolve_recording_path(row.recording_path)
    if abs_path is None:
        logger.debug("Recording file not found for %s: %s", call_id, row.recording_path)
        return None

    cli = client or AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

    try:
        with open(abs_path, "rb") as f:
            file_bytes = f.read()
        resp = await cli.audio.transcriptions.create(
            model=DEFAULT_MODEL,
            file=("recording.mp3", file_bytes, "audio/mpeg"),
        )
        text = getattr(resp, "text", "") or ""
        text = text.strip()
    except Exception as e:
        logger.warning("Whisper transcription failed for %s: %s", call_id, e)
        return None

    if not text:
        return None

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(CallLogRow).where(CallLogRow.call_id == call_id)
        )
        row = result.scalar_one_or_none()
        if row:
            row.whisper_transcript = text
            await session.commit()

    logger.info("Whisper transcript saved for %s (%d chars)", call_id, len(text))
    return text


async def backfill_whisper_transcripts(limit: int = 10) -> int:
    """Transcribe calls that have recordings but no whisper_transcript.

    Called from the judge loop or CLI. Returns count of newly transcribed.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(CallLogRow.call_id)
            .where(CallLogRow.recording_path.isnot(None))
            .where(CallLogRow.recording_path != "")
            .where(
                (CallLogRow.whisper_transcript.is_(None)) |
                (CallLogRow.whisper_transcript == "")
            )
            .where(CallLogRow.duration_seconds > 5)
            .order_by(CallLogRow.started_at.desc())
            .limit(limit)
        )
        call_ids = [r[0] for r in result.all()]

    if not call_ids:
        return 0

    client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
    count = 0
    for cid in call_ids:
        text = await transcribe_recording(cid, client=client)
        if text:
            count += 1

    return count
