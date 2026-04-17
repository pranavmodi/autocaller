"""Call recording service — downloads Twilio recordings to local disk."""
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


def _recordings_root() -> Path:
    """Root directory for stored recordings, relative to the backend app/."""
    root = Path(__file__).resolve().parent.parent / "audio" / "recordings"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _recording_path_for_call(call_id: str, now: Optional[datetime] = None) -> Path:
    """Build the on-disk path for a recording, sharded by YYYY/MM."""
    now = now or datetime.now(timezone.utc)
    year = f"{now.year:04d}"
    month = f"{now.month:02d}"
    folder = _recordings_root() / year / month
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{call_id}.mp3"


def _relative_recording_path(abs_path: Path) -> str:
    """Return the recording path relative to the recordings root, for DB storage."""
    try:
        return str(abs_path.relative_to(_recordings_root()))
    except ValueError:
        return abs_path.name


def resolve_recording_path(relative_path: str) -> Optional[Path]:
    """Resolve a stored relative path back to an absolute path for serving."""
    if not relative_path:
        return None
    abs_path = _recordings_root() / relative_path
    # Prevent path traversal by confirming the resolved path stays under root
    try:
        abs_path = abs_path.resolve()
        root = _recordings_root().resolve()
        abs_path.relative_to(root)
    except (ValueError, OSError):
        return None
    return abs_path if abs_path.is_file() else None


async def download_twilio_recording(
    call_id: str,
    recording_sid: str,
    recording_url: str,
    recording_duration: int = 0,
    delete_from_twilio: bool = True,
    carrier: str = "twilio",
) -> Optional[dict]:
    """Download a recording to local disk and return metadata.

    Works for both Twilio and Telnyx:
    - Twilio: URL needs `.mp3` suffix + basic-auth download + optional delete.
    - Telnyx: URL is a pre-signed S3 link (already has .mp3 in path);
      no auth needed; no server-side delete (Telnyx auto-expires).

    Returns a dict with {path, size_bytes, duration_seconds, format} on
    success, or None on failure.
    """
    is_telnyx = carrier == "telnyx" or "telnyx" in recording_url or "telephony-recorder-prod" in recording_url

    if is_telnyx:
        download_url = recording_url
        auth = None
    else:
        account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
        auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        if not account_sid or not auth_token:
            logger.warning("Twilio credentials missing; cannot download recording")
            return None
        download_url = recording_url if recording_url.endswith(".mp3") else f"{recording_url}.mp3"
        auth = (account_sid, auth_token)

    dest_path = _recording_path_for_call(call_id)
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(download_url, auth=auth)
            resp.raise_for_status()
            content = resp.content
    except Exception as e:
        logger.warning("Failed to download recording %s for call %s: %s", recording_sid, call_id, e)
        return None

    try:
        dest_path.write_bytes(content)
    except Exception as e:
        logger.warning("Failed to save recording for call %s to %s: %s", call_id, dest_path, e)
        return None

    size_bytes = dest_path.stat().st_size
    logger.info(
        "Saved recording for call %s: %s (%d bytes, %ds)",
        call_id, dest_path, size_bytes, recording_duration,
    )

    if not is_telnyx and delete_from_twilio:
        try:
            from app.services.twilio_voice_service import _get_twilio_client
            client = _get_twilio_client()
            client.recordings(recording_sid).delete()
            logger.info("Deleted recording %s from Twilio (call=%s)", recording_sid, call_id)
        except Exception as e:
            logger.warning("Failed to delete recording %s from Twilio: %s", recording_sid, e)

    return {
        "path": _relative_recording_path(dest_path),
        "size_bytes": size_bytes,
        "duration_seconds": recording_duration,
        "format": "mp3",
    }
