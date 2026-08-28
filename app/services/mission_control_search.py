"""Bounded read-only Mission Control podcast-search tools for Lead Finder."""
from __future__ import annotations

import os
from typing import Any

import httpx


MISSION_CONTROL_API_BASE_URL = os.getenv(
    "MISSION_CONTROL_API_BASE_URL", "http://127.0.0.1:8001"
).rstrip("/")
MISSION_CONTROL_SEARCH_API_TOKEN = os.getenv("MISSION_CONTROL_SEARCH_API_TOKEN", "").strip()
MISSION_CONTROL_SEARCH_TIMEOUT_SECONDS = float(
    os.getenv("MISSION_CONTROL_SEARCH_TIMEOUT_SECONDS", "120")
)

LEAD_FINDER_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "mission_control.search",
        "description": (
            "Search indexed Mission Control podcast transcripts. Hybrid combines keyword and "
            "semantic retrieval; returned excerpts are evidence candidates, not verified claims."
        ),
        "arguments": {
            "query": "string, 2-1000 characters",
            "mode": "keyword | semantic | hybrid (default hybrid)",
            "limit": "integer, 1-10 (default 8)",
            "show_ids": "optional array of at most 50 positive integer show IDs",
            "published_after": "optional ISO date/datetime string",
            "published_before": "optional ISO date/datetime string",
        },
    },
    {
        "name": "mission_control.get_passages",
        "description": (
            "Fetch the complete indexed text and provenance for promising transcript chunk IDs "
            "returned by mission_control.search."
        ),
        "arguments": {
            "chunk_ids": "array of 1-10 positive integer chunk IDs",
        },
    },
    {
        "name": "mission_control.index_status",
        "description": (
            "Inspect transcript-index coverage and current backfill status. Use this when search "
            "coverage may affect confidence."
        ),
        "arguments": {},
    },
]

_TOOL_NAMES = {item["name"] for item in LEAD_FINDER_TOOL_DEFINITIONS}


class MissionControlToolError(RuntimeError):
    """A safe, operator-readable Mission Control tool failure."""


def _positive_int_list(value: Any, *, name: str, maximum: int) -> list[int]:
    if not isinstance(value, list) or not value or len(value) > maximum:
        raise MissionControlToolError(f"{name}_must_contain_1_to_{maximum}_ids")
    if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in value):
        raise MissionControlToolError(f"{name}_must_contain_positive_integer_ids")
    return value


def validate_lead_finder_tool_call(tool_name: str, arguments: Any) -> dict[str, Any]:
    """Validate and normalize the allowlisted tool call before any HTTP request."""
    if tool_name not in _TOOL_NAMES:
        raise MissionControlToolError("lead_finder_tool_not_allowed")
    if not isinstance(arguments, dict):
        raise MissionControlToolError("tool_arguments_must_be_an_object")

    if tool_name == "mission_control.index_status":
        if arguments:
            raise MissionControlToolError("index_status_accepts_no_arguments")
        return {}

    if tool_name == "mission_control.get_passages":
        unknown = set(arguments) - {"chunk_ids"}
        if unknown:
            raise MissionControlToolError(f"unsupported_tool_arguments:{','.join(sorted(unknown))}")
        return {
            "chunk_ids": _positive_int_list(
                arguments.get("chunk_ids"), name="chunk_ids", maximum=10
            )
        }

    allowed = {
        "query", "mode", "limit", "show_ids", "published_after", "published_before"
    }
    unknown = set(arguments) - allowed
    if unknown:
        raise MissionControlToolError(f"unsupported_tool_arguments:{','.join(sorted(unknown))}")
    query = arguments.get("query")
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 1_000:
        raise MissionControlToolError("query_must_be_2_to_1000_characters")
    mode = arguments.get("mode", "hybrid")
    if mode not in {"keyword", "semantic", "hybrid"}:
        raise MissionControlToolError("mode_must_be_keyword_semantic_or_hybrid")
    limit = arguments.get("limit", 8)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10:
        raise MissionControlToolError("limit_must_be_between_1_and_10")
    normalized: dict[str, Any] = {
        "query": query.strip(),
        "mode": mode,
        "limit": limit,
        "show_ids": [],
        "published_after": None,
        "published_before": None,
    }
    if "show_ids" in arguments:
        show_ids = arguments["show_ids"]
        if show_ids == []:
            normalized["show_ids"] = []
        else:
            normalized["show_ids"] = _positive_int_list(
                show_ids, name="show_ids", maximum=50
            )
    for key in ("published_after", "published_before"):
        value = arguments.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > 64):
            raise MissionControlToolError(f"{key}_must_be_a_short_date_string")
        normalized[key] = value
    return normalized


def lead_finder_tool_catalog() -> list[dict[str, Any]]:
    return [dict(item) for item in LEAD_FINDER_TOOL_DEFINITIONS]


async def execute_lead_finder_tool(tool_name: str, arguments: Any) -> dict[str, Any]:
    """Execute one allowlisted read-only tool against Mission Control's HTTP API."""
    normalized = validate_lead_finder_tool_call(tool_name, arguments)
    headers = {"accept": "application/json"}
    if MISSION_CONTROL_SEARCH_API_TOKEN:
        headers["authorization"] = f"Bearer {MISSION_CONTROL_SEARCH_API_TOKEN}"
    try:
        async with httpx.AsyncClient(
            timeout=MISSION_CONTROL_SEARCH_TIMEOUT_SECONDS,
            headers=headers,
        ) as client:
            if tool_name == "mission_control.search":
                response = await client.post(
                    f"{MISSION_CONTROL_API_BASE_URL}/api/pi-podcasts/search",
                    json=normalized,
                )
            elif tool_name == "mission_control.get_passages":
                response = await client.post(
                    f"{MISSION_CONTROL_API_BASE_URL}/api/pi-podcasts/search/passages",
                    json=normalized,
                )
            else:
                response = await client.get(
                    f"{MISSION_CONTROL_API_BASE_URL}/api/pi-podcasts/search/status"
                )
            response.raise_for_status()
            payload = response.json()
    except httpx.TimeoutException as exc:
        raise MissionControlToolError("mission_control_search_timed_out") from exc
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500]
        raise MissionControlToolError(
            f"mission_control_http_{exc.response.status_code}:{detail}"
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise MissionControlToolError(f"mission_control_unavailable:{exc}") from exc
    if not isinstance(payload, dict):
        raise MissionControlToolError("mission_control_returned_non_object_json")
    return payload
