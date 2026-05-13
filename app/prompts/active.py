"""Prompt-style selector.

Chooses which prompt module the orchestrator loads per call.
Resolution order (first non-empty wins):

  1. `system_settings.prompt_style` (DB) — operator-set via CLI/UI,
     hot-reload friendly (cached 5s).
  2. `PROMPT_STYLE` env var — boot-time fallback / dev override.
  3. `"current"` — hardcoded default if neither is set.

Valid values: `"current"` (long Sobczak-style prompt) or `"minimal"`
(trimmed-down variant). Anything else falls back to `"current"` so an
accidental misconfigure can never leave calls with no prompt.

Lookup happens per-call (with a 5s in-process cache) so an operator
flip via `autocaller prompts set <style>` or the /system UI takes
effect on the next call without a daemon restart. Runtime hot-swap
mid-call isn't supported — the voice backend caches the system prompt
on WS setup.

Public surface matches both underlying modules:
  - render_system_prompt(lead, **kwargs) -> str
  - prompt_language_for(lead) -> str
  - get_prompt_version() -> str
  - get_tools() -> list[dict]
  - get_active_style() -> "current" | "minimal"

`_default_timezone_for_state` is re-exported from the canonical module
since it doesn't vary by style.
"""
from __future__ import annotations

import asyncio
import os
import time
from types import ModuleType
from typing import Optional

# Timezone helper lives on the canonical module only — never varies.
from app.prompts.attorney_cold_call import (  # noqa: F401
    _default_timezone_for_state,
)


VALID_STYLES = ("current", "minimal")

# Tiny in-process cache for the DB lookup. The voice path can ask
# many times per call — once on render, once for tools, once for
# version — so we don't want a Postgres round-trip for each.
_DB_CACHE_TTL = 5.0
_db_cache: dict = {"value": None, "at": 0.0}


def _normalize(style: str) -> str:
    s = (style or "").strip().lower()
    if s in VALID_STYLES:
        return s
    print(
        f"[prompts.active] prompt_style={style!r} is unknown; "
        f"falling back to 'current'. Valid: {VALID_STYLES}"
    )
    return "current"


async def _read_db_style() -> Optional[str]:
    """Read prompt_style from system_settings. None on miss / error."""
    try:
        from sqlalchemy import select
        from app.db import AsyncSessionLocal
        from app.db.models import SystemSettingsRow
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(SystemSettingsRow.prompt_style).where(
                    SystemSettingsRow.id == 1
                )
            )
            value = result.scalar_one_or_none()
        return value or None
    except Exception:
        return None


def _db_style_blocking() -> Optional[str]:
    """Sync wrapper around the async DB read.

    `get_active_style` is called from synchronous code paths (CLI
    commands, `prompts show`) that don't have an event loop. Spin a
    fresh loop just for this read.
    """
    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_read_db_style())
        finally:
            loop.close()
    except Exception:
        return None


def get_active_style() -> str:
    """Return the active prompt style. DB > env > 'current'."""
    now = time.monotonic()
    if _db_cache["value"] and (now - _db_cache["at"]) < _DB_CACHE_TTL:
        return _db_cache["value"]

    db_value: Optional[str] = None
    try:
        # If we're already inside a running loop, schedule the read
        # via run_coroutine_threadsafe-equivalent: fall back to env
        # for this tick and let the next call (when cache is being
        # populated from elsewhere) pick up the DB value.
        loop = asyncio.get_running_loop()
        # We're inside an async context (FastAPI / dispatcher) — try a
        # blocking read in a thread to avoid nested-loop errors.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as ex:
            db_value = ex.submit(_db_style_blocking).result(timeout=2.0)
        _ = loop  # silence linter
    except RuntimeError:
        # No running loop — synchronous caller (CLI). Read directly.
        db_value = _db_style_blocking()
    except Exception:
        db_value = None

    if db_value:
        style = _normalize(db_value)
    else:
        env = os.getenv("PROMPT_STYLE", "").strip().lower()
        style = _normalize(env) if env else "current"

    _db_cache["value"] = style
    _db_cache["at"] = now
    return style


def invalidate_cache() -> None:
    """Drop the in-process cache. Call after an operator flip so the
    next request reads fresh DB state immediately."""
    _db_cache["value"] = None
    _db_cache["at"] = 0.0


async def set_active_style(style: str) -> str:
    """Persist a new prompt style to system_settings. Returns the
    normalized value that was actually written."""
    normalized = _normalize(style)
    from sqlalchemy import update
    from app.db import AsyncSessionLocal
    from app.db.models import SystemSettingsRow
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(SystemSettingsRow)
            .where(SystemSettingsRow.id == 1)
            .values(prompt_style=normalized)
        )
        await session.commit()
    # Write through, not just invalidate. The thread-pool DB read in
    # get_active_style() can't reuse the asyncpg engine bound to the
    # FastAPI loop, so without write-through the next sync call would
    # see stale data and quietly fall through to the env-var path.
    _db_cache["value"] = normalized
    _db_cache["at"] = time.monotonic()
    return normalized


async def get_active_style_async() -> str:
    """Async-safe version. Reads DB via the existing AsyncSessionLocal
    engine; populates the in-process cache so subsequent sync callers
    in the same process see the same value."""
    now = time.monotonic()
    if _db_cache["value"] and (now - _db_cache["at"]) < _DB_CACHE_TTL:
        return _db_cache["value"]
    db_value = await _read_db_style()
    if db_value:
        style = _normalize(db_value)
    else:
        env = os.getenv("PROMPT_STYLE", "").strip().lower()
        style = _normalize(env) if env else "current"
    _db_cache["value"] = style
    _db_cache["at"] = now
    return style


def _active_module() -> ModuleType:
    style = get_active_style()
    if style == "minimal":
        from app.prompts import attorney_cold_call_minimal as mod
        return mod
    from app.prompts import attorney_cold_call as mod
    return mod


def render_system_prompt(*args, **kwargs) -> str:
    return _active_module().render_system_prompt(*args, **kwargs)


def prompt_language_for(lead) -> str:
    return _active_module().prompt_language_for(lead)


def get_prompt_version() -> str:
    return _active_module().PROMPT_VERSION


def get_tools() -> list[dict]:
    return _active_module().TOOLS
