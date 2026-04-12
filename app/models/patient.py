"""Lead data model (class name retained as `Patient` for historical reasons).

Represents an attorney lead to be cold-called. The class name and the DB
table name (`patients`) are retained from the original Precise Imaging
build; semantically this is now a sales lead. Medical fields are kept
optional so the old seed data and legacy call sites still import cleanly.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum


class Language(str, Enum):
    ENGLISH = "en"
    SPANISH = "es"
    CHINESE = "zh"


class IntakeStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


DECISION_MAKER_TITLES = {
    "partner", "managing partner", "senior partner", "founding partner",
    "principal", "owner", "of counsel", "managing attorney", "shareholder",
}


@dataclass
class Patient:
    """Attorney lead (legacy name)."""
    patient_id: str
    name: str
    phone: str

    # -- Attorney / lead fields --
    firm_name: Optional[str] = None
    state: Optional[str] = None           # 2-letter US state code
    practice_area: Optional[str] = None
    website: Optional[str] = None
    email: Optional[str] = None
    title: Optional[str] = None
    source: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    notes: Optional[str] = None

    # -- Legacy medical fields (unused; kept so legacy code paths don't break) --
    language: Language = Language.ENGLISH
    order_id: Optional[str] = None
    order_created: Optional[datetime] = None
    intake_status: IntakeStatus = IntakeStatus.COMPLETE
    has_called_in_before: bool = False
    has_abandoned_before: bool = False
    ai_called_before: bool = False

    # -- Attempt tracking --
    attempt_count: int = 0
    last_attempt_at: Optional[datetime] = None
    last_outcome: Optional[str] = None
    due_by: Optional[datetime] = None

    # Computed priority (1=highest, 4=lowest)
    priority_bucket: int = field(init=False)

    def __post_init__(self):
        self.priority_bucket = self._compute_priority()

    def _compute_priority(self) -> int:
        """Priority: never-called + decision-maker title → highest."""
        is_dm = self.is_decision_maker()
        if self.attempt_count == 0 and is_dm:
            return 1
        if self.attempt_count == 0:
            return 2
        if is_dm:
            return 3
        return 4

    def is_decision_maker(self) -> bool:
        if not self.title:
            return False
        return self.title.strip().lower() in DECISION_MAKER_TITLES

    def to_dict(self) -> dict:
        return {
            "patient_id": self.patient_id,
            "lead_id": self.patient_id,
            "name": self.name,
            "phone": self.phone,
            "firm_name": self.firm_name,
            "state": self.state,
            "practice_area": self.practice_area,
            "website": self.website,
            "email": self.email,
            "title": self.title,
            "source": self.source,
            "tags": list(self.tags or []),
            "notes": self.notes,
            "language": self.language.value,
            "order_id": self.order_id,
            "order_created": self.order_created.isoformat() if self.order_created else None,
            "intake_status": self.intake_status.value,
            "has_called_in_before": self.has_called_in_before,
            "has_abandoned_before": self.has_abandoned_before,
            "ai_called_before": self.ai_called_before,
            "attempt_count": self.attempt_count,
            "last_attempt_at": self.last_attempt_at.isoformat() if self.last_attempt_at else None,
            "last_outcome": self.last_outcome,
            "due_by": self.due_by.isoformat() if self.due_by else None,
            "priority_bucket": self.priority_bucket,
        }


# Alias so new code can import `Lead` and mean the same thing.
Lead = Patient
