"""Paced, read-only Front inbox endpoints for the PossibleOS operator UI."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import time
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.services.front_sync import FRONT_ENV_PATH

router = APIRouter(prefix="/api/front-ui", tags=["front-ui"])

# One lane for every Front call from this feature. It prevents browsing and a
# long export from multiplying traffic against the shared Front credential.
_request_lock = asyncio.Lock()
_export_lock = asyncio.Lock()
_last_request_at = 0.0
_MIN_REQUEST_INTERVAL = 2.0
_MAX_RETRIES = 4
_MAX_EXPORT_DAYS = 7
_MAX_EXPORT_CONVERSATIONS = 250
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_EXPORT_JOBS: dict[str, dict[str, Any]] = {}
_EXPORT_DIR = Path("data/front_ui_exports")


class InboxExportRequest(BaseModel):
    inbox_id: str = Field(..., min_length=1, max_length=128)
    inbox_name: str | None = Field(None, max_length=200)
    date_from: str
    date_to: str


def _front_settings() -> tuple[str, str]:
    load_dotenv(FRONT_ENV_PATH)
    token = os.getenv("FRONT_AUTH_TOKEN", "").strip()
    base = os.getenv("FRONT_API_BASE_URL", "").strip().rstrip("/")
    if not token or not base:
        raise HTTPException(status_code=503, detail="Front credentials are not configured.")
    return token, base


def _encode_cursor(url: str | None) -> str | None:
    return base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii") if url else None


def _decode_cursor(cursor: str, base: str) -> str:
    try:
        url = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid conversation cursor.") from exc
    parsed = urlparse(url)
    configured_host = urlparse(base).netloc
    is_workspace_host = parsed.netloc.endswith(".api.frontapp.com")
    if parsed.scheme != "https" or (parsed.netloc not in {configured_host, "api2.frontapp.com"} and not is_workspace_host):
        raise HTTPException(status_code=400, detail="Invalid conversation cursor.")
    return url


async def _front_get(
    path_or_url: str,
    *,
    params: dict[str, Any] | None = None,
    cache_seconds: float = 0,
    force: bool = False,
) -> dict[str, Any]:
    """Perform one serialized, rate-limited Front JSON request."""
    global _last_request_at
    token, base = _front_settings()
    url = path_or_url if path_or_url.startswith("https://") else f"{base}{path_or_url}"
    cache_key = f"{url}?{sorted((params or {}).items())}"
    cached = _CACHE.get(cache_key)
    if cache_seconds and not force and cached and cached[0] > time.monotonic():
        return cached[1]

    async with _request_lock:
        cached = _CACHE.get(cache_key)
        if cache_seconds and not force and cached and cached[0] > time.monotonic():
            return cached[1]
        for attempt in range(_MAX_RETRIES):
            delay = _MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request_at)
            if _last_request_at and delay > 0:
                await asyncio.sleep(delay)
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(
                        url,
                        params=params,
                        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    )
                _last_request_at = time.monotonic()
                if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                    try:
                        backoff = max(float(response.headers.get("Retry-After", "10")), _MIN_REQUEST_INTERVAL)
                    except ValueError:
                        backoff = 10.0
                    await asyncio.sleep(min(backoff, 60.0))
                    continue
                response.raise_for_status()
                data = response.json()
                if cache_seconds:
                    _CACHE[cache_key] = (time.monotonic() + cache_seconds, data)
                return data
            except httpx.HTTPStatusError as exc:
                raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text[:500] or "Front API request failed.") from exc
            except httpx.RequestError as exc:
                raise HTTPException(status_code=502, detail=f"Front API request failed: {exc}") from exc
    raise HTTPException(status_code=503, detail="Front API is rate limited. Please retry shortly.")


async def _front_download(url: str) -> httpx.Response:
    """Download an attachment through the same shared Front request lane."""
    global _last_request_at
    token, base = _front_settings()
    _decode_cursor(_encode_cursor(url) or "", base)
    async with _request_lock:
        for attempt in range(_MAX_RETRIES):
            delay = _MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request_at)
            if _last_request_at and delay > 0:
                await asyncio.sleep(delay)
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.get(url, headers={"Authorization": f"Bearer {token}", "Accept": "*/*"})
                _last_request_at = time.monotonic()
                if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                    await asyncio.sleep(min(max(float(response.headers.get("Retry-After", "10")), _MIN_REQUEST_INTERVAL), 60.0))
                    continue
                response.raise_for_status()
                return response
            except ValueError:
                await asyncio.sleep(10.0)
            except httpx.HTTPStatusError as exc:
                raise HTTPException(status_code=exc.response.status_code, detail="Front attachment download failed.") from exc
            except httpx.RequestError as exc:
                raise HTTPException(status_code=502, detail=f"Front attachment download failed: {exc}") from exc
    raise HTTPException(status_code=503, detail="Front API is rate limited. Please retry shortly.")


def _timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    return str(value)


def _recipient_label(value: dict[str, Any] | None) -> str:
    return (value or {}).get("name") or (value or {}).get("handle") or ""


def _recipients(values: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{"name": value.get("name") or "", "handle": value.get("handle") or "", "role": value.get("role") or ""} for value in values]


def _conversation(row: dict[str, Any]) -> dict[str, Any]:
    conversation_id = row.get("id") or ""
    recipient = row.get("recipient") or {}
    return {
        "id": conversation_id, "subject": row.get("subject") or "(No subject)", "status": row.get("status") or "",
        "status_category": row.get("status_category") or "", "assignee_name": _recipient_label(row.get("assignee")),
        "recipient_name": _recipient_label(recipient), "recipient_handle": recipient.get("handle") or "",
        "tags": [{"id": tag.get("id") or "", "name": tag.get("name") or "", "highlight": tag.get("highlight") or ""} for tag in row.get("tags") or []],
        "created_at": _timestamp(row.get("created_at")), "updated_at": _timestamp(row.get("updated_at")),
        "front_url": f"https://app.frontapp.com/open/{conversation_id}",
    }


def _message(row: dict[str, Any]) -> dict[str, Any]:
    recipients = _recipients(row.get("recipients") or [])
    sender = next((entry for entry in recipients if entry["role"] == "from"), {})
    author = row.get("author") or {}
    return {
        "id": row.get("id") or "", "is_inbound": bool(row.get("is_inbound")), "created_at": _timestamp(row.get("created_at")),
        "subject": row.get("subject") or "", "author_name": author.get("name") or sender.get("name") or "",
        "author_handle": author.get("email") or author.get("handle") or sender.get("handle") or "",
        "recipients": recipients, "text": row.get("text") or "", "body": row.get("body") or "", "blurb": row.get("blurb") or "",
        "attachments": [{"id": item.get("id") or "", "filename": item.get("filename") or item.get("name") or "", "content_type": item.get("content_type") or "", "size": item.get("size")} for item in row.get("attachments") or []],
    }


def _attachment_url(attachment: dict[str, Any], base: str) -> str | None:
    candidate = attachment.get("url")
    if not candidate:
        links = attachment.get("_links") or {}
        related = links.get("related") or {}
        candidate = related.get("download") or links.get("download") or related.get("self") or links.get("self")
    if not candidate:
        return None
    return candidate if candidate.startswith("https://") else f"{base}/{candidate.lstrip('/')}"


def _safe_filename(value: str, fallback: str) -> str:
    return (re.sub(r"[^A-Za-z0-9._-]+", "_", value or "").strip("._")[:160] or fallback)


def _parse_export_dates(date_from: str, date_to: str) -> tuple[datetime, datetime]:
    try:
        start = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(date_to, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Dates must use YYYY-MM-DD.") from exc
    if end < start:
        raise HTTPException(status_code=400, detail="date_to must be on or after date_from.")
    if (end - start).days + 1 > _MAX_EXPORT_DAYS:
        raise HTTPException(status_code=400, detail=f"Export range is capped at {_MAX_EXPORT_DAYS} days.")
    return start, end + timedelta(days=1)


def _update_export(export_id: str, **updates: Any) -> None:
    _EXPORT_JOBS.setdefault(export_id, {}).update(updates)
    _EXPORT_JOBS[export_id]["updated_at"] = datetime.now(timezone.utc).isoformat()


async def _export_conversation_ids(inbox_id: str, start: datetime, end: datetime) -> list[str]:
    _, base = _front_settings()
    url = f"{base}/events"
    params: dict[str, Any] | None = {"q[types]": "inbound", "q[after]": int(start.timestamp()), "q[before]": int(end.timestamp())}
    ids: list[str] = []
    seen: set[str] = set()
    for _ in range(100):
        data = await _front_get(url, params=params)
        params = None
        for event in data.get("_results") or []:
            source = (event.get("source") or {}).get("data") or []
            source = [source] if isinstance(source, dict) else source
            if not any((entry or {}).get("id") == inbox_id for entry in source):
                continue
            conversation_id = ((event.get("conversation") or {}).get("id") or "").strip()
            if conversation_id and conversation_id not in seen:
                seen.add(conversation_id)
                ids.append(conversation_id)
                if len(ids) > _MAX_EXPORT_CONVERSATIONS:
                    raise RuntimeError(f"Export found more than {_MAX_EXPORT_CONVERSATIONS} conversations. Choose a smaller date range.")
        url = (data.get("_pagination") or {}).get("next")
        if not url:
            return ids
    raise RuntimeError("Export pagination limit reached. Choose a smaller date range.")


async def _run_export(export_id: str, request: InboxExportRequest) -> None:
    async with _export_lock:
        try:
            start, end = _parse_export_dates(request.date_from, request.date_to)
            _update_export(export_id, status="running", message="Finding Front conversations...")
            conversation_ids = await _export_conversation_ids(request.inbox_id, start, end)
            _update_export(export_id, total_conversations=len(conversation_ids), processed_conversations=0, message=f"Exporting {len(conversation_ids)} conversations...")
            _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            zip_path = _EXPORT_DIR / f"{export_id}.zip"
            manifest: dict[str, Any] = {"export_id": export_id, "inbox_id": request.inbox_id, "inbox_name": request.inbox_name, "date_from": request.date_from, "date_to": request.date_to, "created_at": datetime.now(timezone.utc).isoformat(), "conversations": []}
            _, base = _front_settings()
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for index, conversation_id in enumerate(conversation_ids, start=1):
                    _update_export(export_id, processed_conversations=index - 1, message=f"Exporting conversation {index}/{len(conversation_ids)}...")
                    conversation = await _front_get(f"/conversations/{conversation_id}")
                    messages_data = await _front_get(f"/conversations/{conversation_id}/messages")
                    messages = list(reversed(messages_data.get("_results") or []))
                    folder = f"conversations/{_safe_filename(conversation_id, 'conversation')}"
                    archive.writestr(f"{folder}/conversation.json", json.dumps(conversation, indent=2, default=str))
                    archive.writestr(f"{folder}/messages.json", json.dumps(messages, indent=2, default=str))
                    attachment_count = 0
                    for message in messages:
                        for attachment in message.get("attachments") or []:
                            attachment_url = _attachment_url(attachment, base)
                            if not attachment_url:
                                continue
                            download = await _front_download(attachment_url)
                            filename = _safe_filename(attachment.get("filename") or attachment.get("name") or attachment.get("id") or "attachment", "attachment")
                            archive.writestr(f"{folder}/attachments/{_safe_filename(message.get('id') or 'message', 'message')}/{filename}", download.content)
                            attachment_count += 1
                    manifest["conversations"].append({"id": conversation_id, "subject": conversation.get("subject"), "message_count": len(messages), "attachment_count": attachment_count, "front_url": f"https://app.frontapp.com/open/{conversation_id}"})
                    _update_export(export_id, processed_conversations=index)
                archive.writestr("manifest.json", json.dumps(manifest, indent=2, default=str))
            _update_export(export_id, status="completed", message="Export completed.", download_url=f"/api/front-ui/exports/{export_id}/download", file_size=zip_path.stat().st_size)
        except Exception as exc:  # noqa: BLE001
            _update_export(export_id, status="failed", message=str(exc)[:500])


@router.get("/inboxes")
async def list_inboxes(refresh: bool = False) -> dict[str, Any]:
    data = await _front_get("/inboxes", cache_seconds=300, force=refresh)
    items = [{"id": row.get("id") or "", "name": row.get("name") or "", "address": row.get("address") or row.get("send_as") or "", "type": row.get("type") or "", "is_private": bool(row.get("is_private"))} for row in data.get("_results") or []]
    return {"items": sorted(items, key=lambda item: item["name"].lower()), "total": len(items)}


@router.get("/inboxes/{inbox_id}/conversations")
async def list_conversations(inbox_id: str, limit: int = Query(15, ge=1, le=30), cursor: str | None = None, refresh: bool = False) -> dict[str, Any]:
    _, base = _front_settings()
    data = await _front_get(_decode_cursor(cursor, base) if cursor else f"/inboxes/{inbox_id}/conversations", params=None if cursor else {"limit": limit}, cache_seconds=60, force=refresh)
    return {"items": [_conversation(row) for row in data.get("_results") or []], "next_cursor": _encode_cursor((data.get("_pagination") or {}).get("next"))}


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, refresh: bool = False) -> dict[str, Any]:
    conversation = await _front_get(f"/conversations/{conversation_id}", cache_seconds=60, force=refresh)
    messages = await _front_get(f"/conversations/{conversation_id}/messages", cache_seconds=60, force=refresh)
    normalized_messages = [_message(row) for row in messages.get("_results") or []]
    normalized_messages.reverse()
    return {"conversation": _conversation(conversation), "messages": normalized_messages, "message_count": len(normalized_messages)}


@router.post("/exports")
async def start_export(request: InboxExportRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    _parse_export_dates(request.date_from, request.date_to)
    export_id = uuid.uuid4().hex
    _update_export(export_id, status="queued", message="Export queued.", inbox_id=request.inbox_id, inbox_name=request.inbox_name, date_from=request.date_from, date_to=request.date_to, total_conversations=0, processed_conversations=0, download_url=None, file_size=None, created_at=datetime.now(timezone.utc).isoformat())
    background_tasks.add_task(_run_export, export_id, request)
    return {"export_id": export_id, "status": "queued", "message": "Export queued."}


@router.get("/exports/{export_id}")
async def get_export_status(export_id: str) -> dict[str, Any]:
    job = _EXPORT_JOBS.get(export_id)
    if not job:
        raise HTTPException(status_code=404, detail="Export not found.")
    return job


@router.get("/exports/{export_id}/download")
async def download_export(export_id: str) -> FileResponse:
    job = _EXPORT_JOBS.get(export_id)
    if not job:
        raise HTTPException(status_code=404, detail="Export not found.")
    if job.get("status") != "completed":
        raise HTTPException(status_code=409, detail="Export is not completed yet.")
    path = _EXPORT_DIR / f"{export_id}.zip"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Export file not found.")
    return FileResponse(path, media_type="application/zip", filename=_safe_filename(f"{job.get('inbox_name') or job.get('inbox_id')}_{job.get('date_from')}_{job.get('date_to')}.zip", f"{export_id}.zip"))


@router.get("/messages/{message_id}/attachments/{attachment_id}/download")
async def download_attachment(message_id: str, attachment_id: str) -> Response:
    message = await _front_get(f"/messages/{message_id}", cache_seconds=60)
    attachment = next((item for item in message.get("attachments") or [] if item.get("id") == attachment_id), None)
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found on message.")
    _, base = _front_settings()
    attachment_url = _attachment_url(attachment, base)
    if not attachment_url:
        raise HTTPException(status_code=404, detail="Attachment has no downloadable URL.")
    download = await _front_download(attachment_url)
    filename = attachment.get("filename") or attachment.get("name") or attachment_id
    return Response(content=download.content, media_type=attachment.get("content_type") or download.headers.get("Content-Type") or "application/octet-stream", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}", "Content-Length": str(len(download.content))})
