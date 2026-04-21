"""Canonical phone-number normalizer.

Used by every ingestion path (CLI lead import, Cadence API, Mission Control
sync, SMS service) so messy multi-value phone fields like
"Primary: 818-784-8544; Additional: 424-283-5822, Fax: 818-784-5970"
all reduce to the same E.164 form (+18187848544). Previously each path had
its own implementation — the Cadence API's inline version concatenated
digits across *all* numbers in the field and then rejected because the
total length didn't match 10 or 11, silently dropping the lead.
"""
from __future__ import annotations

import re


def normalize_phone(raw: str) -> str:
    """Normalize a phone string to E.164 ("+1NNNNNNNNNN" for US).

    Strategy:
      1. Take the first value before any extension / separator / annotation
         marker (`;`, `,`, `x`, `ext`, `ext.`). Multi-value fields like
         "Primary: ...; Additional: ..." yield just the primary.
      2. Strip everything non-digit from the remainder.
      3. If 10 digits, prepend +1. If 11 and starts with 1, prepend +.
      4. Allow bare international E.164 if it starts with + and has 8-15
         total digits.
      5. Return "" if nothing parseable — caller decides how to handle.
    """
    s = (raw or "").strip()
    if not s:
        return ""
    # Split off extension markers + multi-value separators.
    s = re.split(r"(?i)\s*(?:x|ext\.?|,|;)\s*", s, maxsplit=1)[0]
    digits = re.sub(r"\D", "", s)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if s.startswith("+") and 8 <= len(digits) <= 15:
        return f"+{digits}"
    return ""
