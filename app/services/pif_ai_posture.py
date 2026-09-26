"""Validate and preserve source-backed AI adoption observations."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, ValidationError


class AIStatement(BaseModel):
    speaker_name: str | None = None
    speaker_title: str | None = None
    source_url: HttpUrl
    source_type: str
    published_at: date | None = None
    quote: str | None = Field(None, max_length=500)
    summary: str = Field(min_length=1, max_length=2000)
    scope: Literal["firm_adoption", "personal_opinion", "industry_commentary"]
    tools: list[str] = Field(default_factory=list)
    use_cases: list[str] = Field(default_factory=list)


class AIPosture(BaseModel):
    adoption_stage: Literal["unknown", "exploring", "piloting", "adopted", "scaling", "restricted"] = "unknown"
    leadership_stance: Literal["unknown", "supportive", "cautious", "opposed", "mixed"] = "unknown"
    summary: str = Field(default="No public evidence found.", max_length=3000)
    confidence: float = Field(default=0, ge=0, le=1)
    statements: list[AIStatement] = Field(default_factory=list, max_length=15)
    searched_sources: list[HttpUrl] = Field(default_factory=list, max_length=30)


def normalize_ai_posture(value: object) -> dict | None:
    if value is None:
        return None
    try:
        posture = AIPosture.model_validate(value)
    except ValidationError as exc:
        raise ValueError("invalid_ai_adoption_research") from exc
    # Evidence is required for a claimed posture; missing evidence is unknown.
    if not posture.statements:
        posture.adoption_stage = "unknown"
        posture.leadership_stance = "unknown"
        posture.confidence = 0
        posture.summary = "No public evidence found."
    return posture.model_dump(mode="json")


def store_ai_posture(data: dict, result: dict | None, checked_at: datetime) -> None:
    if result is None:
        return
    previous = data.get("ai_adoption")
    history = list(data.get("ai_adoption_history") or [])
    if isinstance(previous, dict):
        previous_content = {key: value for key, value in previous.items() if key != "checked_at"}
        if previous_content != result:
            history.append(previous)
    data["ai_adoption_history"] = history
    data["ai_adoption"] = {**result, "checked_at": checked_at.isoformat()}
