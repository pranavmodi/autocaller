"""Prompt-style selector.

Chooses which prompt module the orchestrator loads per call. Driven by
the `PROMPT_STYLE` env var:

    PROMPT_STYLE=current   → app.prompts.attorney_cold_call  (default, v1.61)
    PROMPT_STYLE=minimal   → app.prompts.attorney_cold_call_minimal (v2.0-minimal)

Anything else (unset, empty, typo) → falls back to `current` so an
accidental misconfigure can never leave calls with no prompt at all.

Lookup happens per-call (not cached at module import) so a
PROMPT_STYLE change plus backend restart is all that's needed to flip
styles. Runtime hot-swap mid-call isn't supported — the voice backend
caches the system prompt on WS setup.

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

import os
from types import ModuleType

# Timezone helper lives on the canonical module only — never varies.
from app.prompts.attorney_cold_call import (  # noqa: F401
    _default_timezone_for_state,
)


VALID_STYLES = ("current", "minimal")


def get_active_style() -> str:
    style = (os.getenv("PROMPT_STYLE", "current") or "current").strip().lower()
    if style not in VALID_STYLES:
        # Misconfig or typo — fall back to current and log once.
        print(
            f"[prompts.active] PROMPT_STYLE={style!r} is unknown; "
            f"falling back to 'current'. Valid: {VALID_STYLES}"
        )
        return "current"
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
