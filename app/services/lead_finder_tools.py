"""Validated Lead Finder tools across Mission Control, web, and run results."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.services.lead_finder_web_research import research_person
from app.services.mission_control_search import (
    LEAD_FINDER_TOOL_DEFINITIONS as MISSION_CONTROL_TOOL_DEFINITIONS,
    MissionControlToolError,
    execute_lead_finder_tool as execute_mission_control_tool,
)


WEB_RESEARCH_TOOL = {
    "name": "web.research_person",
    "description": (
        "After a named person is supported by Mission Control evidence, verify identity, current "
        "role, relevant recent public signals, source URLs, and possible outreach angles using "
        "live web search. Research one person per call."
    ),
    "arguments": {
        "person_name": "string, 2-160 characters",
        "organization": "optional string, at most 240 characters",
        "role": "optional string, at most 240 characters",
        "research_focus": "optional string, at most 1000 characters",
        "mission_control_evidence": (
            "array of 1-5 objects with chunk_id, episode_title, and optional excerpt"
        ),
    },
}

ADD_RESULT_TOOL = {
    "name": "lead_finder.add_researched_lead",
    "description": (
        "Add one completed web.research_person result to this run's Found Leads list. The "
        "research_tool_call_id must reference a completed web research call in recent tool history."
    ),
    "arguments": {
        "research_tool_call_id": "completed web.research_person tool-call ID",
        "selected_angle_indexes": "optional array of 0-4 integer indexes",
        "notes": "optional concise user-facing note, at most 1000 characters",
    },
}

LEAD_FINDER_TOOL_DEFINITIONS = [
    *MISSION_CONTROL_TOOL_DEFINITIONS,
    WEB_RESEARCH_TOOL,
    ADD_RESULT_TOOL,
]


class LeadFinderToolError(RuntimeError):
    pass


def _short_optional(arguments: dict[str, Any], key: str, maximum: int) -> str | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or len(value.strip()) > maximum:
        raise LeadFinderToolError(f"{key}_must_be_a_string_at_most_{maximum}_characters")
    return value.strip() or None


def _validate_web_research(arguments: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "person_name", "organization", "role", "research_focus", "mission_control_evidence"
    }
    unknown = set(arguments) - allowed
    if unknown:
        raise LeadFinderToolError(f"unsupported_tool_arguments:{','.join(sorted(unknown))}")
    person_name = arguments.get("person_name")
    if not isinstance(person_name, str) or not 2 <= len(person_name.strip()) <= 160:
        raise LeadFinderToolError("person_name_must_be_2_to_160_characters")
    raw_evidence = arguments.get("mission_control_evidence")
    if not isinstance(raw_evidence, list) or not 1 <= len(raw_evidence) <= 5:
        raise LeadFinderToolError("mission_control_evidence_must_contain_1_to_5_items")
    evidence: list[dict[str, Any]] = []
    for item in raw_evidence:
        if not isinstance(item, dict):
            raise LeadFinderToolError("mission_control_evidence_items_must_be_objects")
        unknown_evidence = set(item) - {"chunk_id", "episode_title", "excerpt", "source_url"}
        if unknown_evidence:
            raise LeadFinderToolError("unsupported_mission_control_evidence_fields")
        chunk_id = item.get("chunk_id")
        if isinstance(chunk_id, bool) or not isinstance(chunk_id, int) or chunk_id <= 0:
            raise LeadFinderToolError("mission_control_evidence_requires_positive_chunk_id")
        evidence.append({
            "chunk_id": chunk_id,
            "episode_title": str(item.get("episode_title") or "").strip()[:500],
            "excerpt": str(item.get("excerpt") or "").strip()[:4_000],
            "source_url": str(item.get("source_url") or "").strip()[:2_000] or None,
        })
    return {
        "person_name": person_name.strip(),
        "organization": _short_optional(arguments, "organization", 240),
        "role": _short_optional(arguments, "role", 240),
        "research_focus": _short_optional(arguments, "research_focus", 1_000),
        "mission_control_evidence": evidence,
    }


def _validate_add_result(arguments: dict[str, Any]) -> dict[str, Any]:
    allowed = {"research_tool_call_id", "selected_angle_indexes", "notes"}
    unknown = set(arguments) - allowed
    if unknown:
        raise LeadFinderToolError(f"unsupported_tool_arguments:{','.join(sorted(unknown))}")
    call_id = arguments.get("research_tool_call_id")
    if not isinstance(call_id, str) or not call_id.startswith("lft_") or len(call_id) > 80:
        raise LeadFinderToolError("research_tool_call_id_is_invalid")
    raw_indexes = arguments.get("selected_angle_indexes")
    indexes: list[int] | None = None
    if raw_indexes is not None:
        if (
            not isinstance(raw_indexes, list)
            or len(raw_indexes) > 5
            or any(isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 4 for item in raw_indexes)
        ):
            raise LeadFinderToolError("selected_angle_indexes_must_be_0_to_4")
        indexes = list(dict.fromkeys(raw_indexes))
    return {
        "research_tool_call_id": call_id,
        "selected_angle_indexes": indexes,
        "notes": _short_optional(arguments, "notes", 1_000),
    }


def validate_lead_finder_tool_call(tool_name: str, arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise LeadFinderToolError("tool_arguments_must_be_an_object")
    if tool_name == WEB_RESEARCH_TOOL["name"]:
        return _validate_web_research(arguments)
    if tool_name == ADD_RESULT_TOOL["name"]:
        return _validate_add_result(arguments)
    if tool_name.startswith("mission_control."):
        try:
            from app.services.mission_control_search import validate_lead_finder_tool_call as validate
            return validate(tool_name, arguments)
        except MissionControlToolError as exc:
            raise LeadFinderToolError(str(exc)) from exc
    raise LeadFinderToolError("lead_finder_tool_not_allowed")


def lead_finder_tool_catalog() -> list[dict[str, Any]]:
    return [dict(item) for item in LEAD_FINDER_TOOL_DEFINITIONS]


def _referenced_research(
    tool_history: list[dict[str, Any]], call_id: str
) -> dict[str, Any] | None:
    for item in reversed(tool_history):
        if (
            item.get("id") == call_id
            and item.get("tool_name") == WEB_RESEARCH_TOOL["name"]
            and item.get("status") == "completed"
            and isinstance(item.get("result"), dict)
        ):
            return item["result"]
    return None


def _build_found_lead(
    research: dict[str, Any], normalized: dict[str, Any]
) -> dict[str, Any]:
    angles = research.get("outreach_angles") if isinstance(research.get("outreach_angles"), list) else []
    selected = normalized.get("selected_angle_indexes")
    if selected is not None:
        angles = [angles[index] for index in selected if index < len(angles)]
    person = research.get("person") if isinstance(research.get("person"), dict) else {}
    return {
        "id": f"lflead_{uuid.uuid4().hex}",
        "status": "researched",
        "name": str(person.get("name") or "").strip(),
        "role": person.get("current_role"),
        "organization": person.get("organization"),
        "official_profile_url": person.get("official_profile_url"),
        "identity_confidence": person.get("identity_confidence"),
        "profile_summary": research.get("profile_summary") or "",
        "recent_signals": research.get("recent_signals") or [],
        "outreach_angles": angles,
        "sources": research.get("sources") or [],
        "contrary_evidence": research.get("contrary_evidence") or [],
        "mission_control_evidence": research.get("mission_control_evidence") or [],
        "research_tool_call_id": normalized["research_tool_call_id"],
        "notes": normalized.get("notes"),
        "researched_at": research.get("researched_at"),
        "added_at": datetime.now(timezone.utc).isoformat(),
    }


async def execute_lead_finder_tool(
    tool_name: str,
    arguments: Any,
    *,
    tool_history: list[dict[str, Any]] | None = None,
    web_research_provider: str = "openai",
) -> dict[str, Any]:
    normalized = validate_lead_finder_tool_call(tool_name, arguments)
    if tool_name == WEB_RESEARCH_TOOL["name"]:
        try:
            return await research_person(normalized, provider=web_research_provider)
        except Exception as exc:
            detail = str(exc)
            if detail.startswith("web_research_"):
                raise LeadFinderToolError(detail) from exc
            raise LeadFinderToolError(f"web_research_failed:{detail}") from exc
    if tool_name == ADD_RESULT_TOOL["name"]:
        research = _referenced_research(tool_history or [], normalized["research_tool_call_id"])
        if research is None:
            raise LeadFinderToolError("completed_web_research_not_found_in_recent_tool_history")
        lead = _build_found_lead(research, normalized)
        if not lead["name"] or not lead["sources"] or not lead["outreach_angles"]:
            raise LeadFinderToolError("researched_lead_requires_name_sources_and_outreach_angle")
        return {"lead": lead}
    try:
        return await execute_mission_control_tool(tool_name, normalized)
    except MissionControlToolError as exc:
        raise LeadFinderToolError(str(exc)) from exc
