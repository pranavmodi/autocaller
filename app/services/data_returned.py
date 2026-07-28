"""Persistence for payloads received through the public /datareturned endpoint."""
from __future__ import annotations

import shlex
import textwrap
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import delete, desc, func, select

from app.db import AsyncSessionLocal, async_engine
from app.db.models import DataReturnedRow, DataReturnedScriptRow


_tables_checked = False
_MAX_SCRIPT_LENGTH = 100_000
_DATA_RETURNED_RETENTION = 100
_NO_OP_SCRIPT_TEMPLATE = r"""
#!/usr/bin/env bash

# Disabled by the Possible OS operator. Send only an empty heartbeat so the
# receiver can confirm the fetch-and-run path without collecting any data.
exec curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data-binary '{}' \
  __CALLBACK_URL__
"""


_DIAGNOSTIC_SCRIPT_TEMPLATE = r"""
#!/usr/bin/env bash
set -u

# Fixed, read-only execution context. This script intentionally does not read
# environment variables, files, process arguments, or network configuration.
OUTPUT="$(
  {
    printf 'timestamp_utc='
    date -u '+%Y-%m-%dT%H:%M:%SZ'
    printf 'whoami='
    whoami
    printf 'identity='
    id
    printf 'hostname='
    hostname
    printf 'working_directory='
    pwd -P
    printf 'kernel='
    uname -a
  } 2>&1
)"

json_escape() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  value="${value//$'\r'/\\r}"
  value="${value//$'\t'/\\t}"
  printf '%s' "$value"
}

OUTPUT_JSON="$(json_escape "$OUTPUT")"

curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data-binary "{\"source\":\"possibleos-datareturned-script\",\"script_version\":1,\"output\":\"${OUTPUT_JSON}\"}" \
  __CALLBACK_URL__
"""


def build_data_returned_script(callback_url: str) -> str:
    """Return a fixed diagnostic script whose final command posts its output."""
    parsed = urlsplit(callback_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("callback_url must be an absolute HTTP(S) URL")
    safe_callback = shlex.quote(callback_url)
    return (
        textwrap.dedent(_DIAGNOSTIC_SCRIPT_TEMPLATE)
        .lstrip()
        .replace("__CALLBACK_URL__", safe_callback)
    )


def build_data_returned_noop_script(callback_url: str) -> str:
    """Return the empty-callback script served while the toggle is off."""
    parsed = urlsplit(callback_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("callback_url must be an absolute HTTP(S) URL")
    safe_callback = shlex.quote(callback_url)
    return (
        textwrap.dedent(_NO_OP_SCRIPT_TEMPLATE)
        .lstrip()
        .replace("__CALLBACK_URL__", safe_callback)
    )


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def data_returned_to_dict(row: DataReturnedRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "payload": row.payload_json,
        "headers": row.headers_json,
        "source_ip": row.source_ip,
        "user_agent": row.user_agent,
        "content_type": row.content_type,
        "received_at": _iso(row.received_at),
    }


async def _prune_data_returned_session(session) -> int:
    keep_ids = (
        select(DataReturnedRow.id)
        .order_by(desc(DataReturnedRow.received_at), desc(DataReturnedRow.id))
        .limit(_DATA_RETURNED_RETENTION)
    )
    result = await session.execute(
        delete(DataReturnedRow).where(DataReturnedRow.id.not_in(keep_ids))
    )
    return int(result.rowcount or 0)


async def ensure_data_returned_tables() -> None:
    """Create returned-data tables on demand if runtime is ahead of migrations."""
    global _tables_checked
    if _tables_checked:
        return
    async with async_engine.begin() as conn:
        await conn.run_sync(DataReturnedRow.__table__.create, checkfirst=True)
        await conn.run_sync(DataReturnedScriptRow.__table__.create, checkfirst=True)
    _tables_checked = True


async def get_data_returned_script(callback_url: str) -> dict[str, Any]:
    """Return the saved script, falling back to the generated diagnostic script."""
    await ensure_data_returned_tables()
    async with AsyncSessionLocal() as session:
        row = await session.get(DataReturnedScriptRow, 1)
        if row is None:
            return {
                "script": build_data_returned_script(callback_url),
                "enabled": True,
                "customized": False,
                "updated_at": None,
            }
        return {
            "script": row.script_text,
            "enabled": row.enabled,
            "customized": True,
            "updated_at": _iso(row.updated_at),
        }


async def save_data_returned_script(script: str) -> dict[str, Any]:
    """Persist the exact operator-provided script served by the public endpoint."""
    if not script.strip():
        raise ValueError("script cannot be empty")
    if len(script) > _MAX_SCRIPT_LENGTH:
        raise ValueError(f"script cannot exceed {_MAX_SCRIPT_LENGTH} characters")

    await ensure_data_returned_tables()
    async with AsyncSessionLocal() as session:
        row = await session.get(DataReturnedScriptRow, 1)
        if row is None:
            row = DataReturnedScriptRow(id=1, script_text=script, enabled=True)
            session.add(row)
        else:
            row.script_text = script
        await session.commit()
        await session.refresh(row)
        return {
            "script": row.script_text,
            "enabled": row.enabled,
            "customized": True,
            "updated_at": _iso(row.updated_at),
        }


async def set_data_returned_script_enabled(
    *, enabled: bool, callback_url: str,
) -> dict[str, Any]:
    """Toggle public script execution while preserving the operator's script."""
    await ensure_data_returned_tables()
    async with AsyncSessionLocal() as session:
        row = await session.get(DataReturnedScriptRow, 1)
        if row is None:
            row = DataReturnedScriptRow(
                id=1,
                script_text=build_data_returned_script(callback_url),
                enabled=enabled,
            )
            session.add(row)
        else:
            row.enabled = enabled
        await session.commit()
        await session.refresh(row)
        return {
            "script": row.script_text,
            "enabled": row.enabled,
            "customized": True,
            "updated_at": _iso(row.updated_at),
        }


async def record_data_returned(
    *,
    payload: dict[str, Any] | list[Any],
    headers: dict[str, str],
    source_ip: str | None,
    user_agent: str | None,
    content_type: str | None,
) -> dict[str, Any]:
    await ensure_data_returned_tables()
    row = DataReturnedRow(
        payload_json=payload,
        headers_json=headers,
        source_ip=(source_ip or "")[:64] or None,
        user_agent=(user_agent or "")[:512] or None,
        content_type=(content_type or "")[:255] or None,
    )
    async with AsyncSessionLocal() as session:
        session.add(row)
        await session.flush()
        await _prune_data_returned_session(session)
        await session.commit()
        await session.refresh(row)
        return data_returned_to_dict(row)


async def list_data_returned(*, limit: int = 100) -> list[dict[str, Any]]:
    await ensure_data_returned_tables()
    safe_limit = max(1, min(limit, _DATA_RETURNED_RETENTION))
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(DataReturnedRow)
                .order_by(desc(DataReturnedRow.received_at), desc(DataReturnedRow.id))
                .limit(safe_limit)
            )
        ).scalars().all()
        return [data_returned_to_dict(row) for row in rows]


async def prune_data_returned() -> dict[str, int]:
    """Delete all but the newest retained callback events."""
    await ensure_data_returned_tables()
    async with AsyncSessionLocal() as session:
        deleted = await _prune_data_returned_session(session)
        retained = int(
            await session.scalar(select(func.count()).select_from(DataReturnedRow)) or 0
        )
        await session.commit()
        return {"deleted": deleted, "retained": retained}
