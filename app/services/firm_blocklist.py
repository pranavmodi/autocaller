"""Firms we MUST NEVER cold-call.

Precise Imaging is our partner — calling them as a "lead" would be
embarrassing. Other imaging vendors (Advantage MRI, Nationwide,
etc.) are NOT blocked — they're legitimate firms that could be
prospects.

Blocklist semantics:
  * Pif-ID match → block (most precise; immune to firm-name typos)
  * Firm-name substring match (case-insensitive) → block (defensive
    fallback for new rows we don't yet have a pif_id for)

Both are checked. is_blocked() returns True if EITHER fires.

Adding new entries:
  * Permanent vendor: append to the constants below + commit.
  * Operator-driven, per-deployment: set CALL_FIRM_BLOCKLIST in .env
    as a comma-separated mix of pif-ids and firm-name fragments.
"""
from __future__ import annotations

import os
from typing import Iterable, Optional


# Built-in pif_ids — verified against our PIF Stats data. Adding here
# requires a code edit; safer than relying on env vars for partner
# protection.
_BUILTIN_BLOCKED_PIF_IDS = frozenset({
    "ca3dae0e-f252-489a-b093-9032eae6bdeb",   # Precise Imaging (our partner)
    "96fcaf0a-1997-4700-83aa-128cb6f5eb85",   # Precise MRI (related entity)
})


# Built-in firm-name substrings, lowercased. Any cadence/lead row whose
# firm_name (case-insensitive) contains one of these is blocked.
# Only Precise Imaging variants — other imaging vendors are NOT blocked.
_BUILTIN_BLOCKED_FIRM_SUBSTRS = (
    "precise imaging",
    "precise mri",
)


def _env_blocklist() -> tuple[frozenset[str], tuple[str, ...]]:
    """Parse the optional CALL_FIRM_BLOCKLIST env var.

    Format: comma-separated tokens. A token that looks like a UUID is
    treated as a pif_id; anything else as a case-insensitive
    firm-name substring.
    """
    raw = os.getenv("CALL_FIRM_BLOCKLIST", "").strip()
    if not raw:
        return frozenset(), ()
    tokens = [t.strip() for t in raw.split(",") if t.strip()]
    pif_ids: set[str] = set()
    substrs: list[str] = []
    for t in tokens:
        # Crude UUID heuristic — 36 chars with hyphens at fixed
        # offsets. Good enough; nobody's named a firm "8-4-4-4-12".
        if (
            len(t) == 36
            and t[8] == "-" and t[13] == "-"
            and t[18] == "-" and t[23] == "-"
        ):
            pif_ids.add(t)
        else:
            substrs.append(t.lower())
    return frozenset(pif_ids), tuple(substrs)


def is_blocked(pif_id: Optional[str], firm_name: Optional[str]) -> bool:
    """True if the firm should never appear in any call queue."""
    pid = (pif_id or "").strip().lower()
    name = (firm_name or "").strip().lower()
    if pid and pid in _BUILTIN_BLOCKED_PIF_IDS:
        return True
    if name:
        for sub in _BUILTIN_BLOCKED_FIRM_SUBSTRS:
            if sub in name:
                return True
    env_pif_ids, env_substrs = _env_blocklist()
    if pid and pid in env_pif_ids:
        return True
    for sub in env_substrs:
        if sub and sub in name:
            return True
    return False


def filter_blocked(rows: Iterable[dict]) -> list[dict]:
    """Drop blocked rows. Each row should be a dict with at least
    `pif_id` and `firm_name`. Used by the queue API to filter."""
    return [
        r for r in rows
        if not is_blocked(r.get("pif_id"), r.get("firm_name"))
    ]
