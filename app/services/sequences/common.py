"""Shared sequence rendering types."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Ctx:
    """All personalization a sequence renderer can see."""
    first_name: str
    firm_name: str
    rep_name: str
    pain_quote: Optional[str] = None
    reviewer_name: Optional[str] = None
    review_date: Optional[str] = None


@dataclass
class RenderedStep:
    subject: str
    body: str
    message_type: str
