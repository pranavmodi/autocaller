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


async def transcribe_recording_to_segments(call_id: str) -> int:
    """Run segment-level Whisper on a call's recording and splice each
    segment into `call_logs.transcript` as a turn.

    Used when the live transcript is incomplete — specifically for
    calls where the operator took over (the orchestrator doesn't feed
    operator audio to the voice backend, so the live transcript is
    missing that side). Also a safety net for any other case where the
    live STT silently broke.

    Speaker labelling: Whisper doesn't diarize, and the Telnyx recording
    mixes both sides into a single track, so every segment is tagged
    `speaker="recorded"` with a note. Downstream consumers (judge, UI)
    can display these distinctly from the live-captured `ai` / `patient`
    turns.

    Existing live turns are preserved — new segments are APPENDED, with
    a leading `system` marker so a reader can see the boundary.
    Returns the count of segments added (0 if nothing was added).
    """
    import json as _json

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(CallLogRow).where(CallLogRow.call_id == call_id)
        )
        row = result.scalar_one_or_none()

    if not row or not row.recording_path:
        return 0

    abs_path = resolve_recording_path(row.recording_path)
    if abs_path is None:
        logger.debug("Recording file not found for %s: %s", call_id, row.recording_path)
        return 0

    # gpt-4o-transcribe doesn't yet expose segment timestamps; fall back
    # to whisper-1 which does. Cost is marginally higher but still cents
    # per call for typical cold-call durations.
    cli = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
    try:
        with open(abs_path, "rb") as f:
            file_bytes = f.read()
        resp = await cli.audio.transcriptions.create(
            model="whisper-1",
            file=("recording.mp3", file_bytes, "audio/mpeg"),
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
    except Exception as e:
        logger.warning("segment Whisper failed for %s: %s", call_id, e)
        return 0

    segments = getattr(resp, "segments", None) or []
    if not segments:
        logger.debug("Whisper returned no segments for %s", call_id)
        return 0

    # Compose turns anchored at started_at + segment.start offset.
    started = row.started_at
    if started is None:
        return 0

    from datetime import timedelta
    new_turns = [
        {
            "speaker": "system",
            "text": (
                f"— post-call Whisper transcript spliced below "
                f"({len(segments)} segments; operator + prospect mixed)"
            ),
            "timestamp": (started + timedelta(seconds=0.0)).isoformat(),
        }
    ]
    for seg in segments:
        seg_start = float(getattr(seg, "start", 0.0) or 0.0)
        text = (getattr(seg, "text", "") or "").strip()
        if not text:
            continue
        new_turns.append({
            "speaker": "recorded",
            "text": text,
            "timestamp": (started + timedelta(seconds=seg_start)).isoformat(),
        })

    if len(new_turns) <= 1:
        return 0

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(CallLogRow).where(CallLogRow.call_id == call_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            return 0
        existing = list(row.transcript or [])
        # Idempotency: if a prior run already added a "post-call Whisper
        # transcript spliced" system marker, skip.
        already = any(
            (t.get("speaker") == "system"
             and "post-call Whisper transcript spliced" in (t.get("text") or ""))
            for t in existing
        )
        if already:
            return 0
        merged = existing + new_turns
        # SQLAlchemy JSONB dirty-tracking needs a new object, not in-place.
        row.transcript = merged
        # Also populate the plain-text whisper_transcript column for the judge.
        full_text = "\n".join(
            (getattr(s, "text", "") or "").strip() for s in segments
        ).strip()
        if full_text and not (row.whisper_transcript or "").strip():
            row.whisper_transcript = full_text
        await session.commit()

    logger.info(
        "Spliced %d Whisper segments into transcript for call %s",
        len(new_turns) - 1, call_id,
    )
    return len(new_turns) - 1


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
