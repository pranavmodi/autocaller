"""High-confidence AI Audit pre-answer mapping for outbound links."""
from __future__ import annotations

from typing import Any


# Canonical AIAudit question IDs:
# case_system, field_quality, system_modernity, phone_docs, intake_repeatability,
# case_workflows, funnel_metrics, case_metrics, shadow_ai, vendor_diligence,
# leadership, adoption_history, target_problem, budget_expectations.
MODERN_CASE_MANAGEMENT_SYSTEMS = {
    "casepeer",
    "filevine",
    "litify",
    "meruscase",
    "mycase",
    "neos",
    "smartadvocate",
}


def _clean_system(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def audit_preanswer_params(
    *,
    contact_tech_signals: dict[str, Any] | None = None,
    activity_tech_signals: dict[str, Any] | None = None,
    behavioral_json: dict[str, Any] | None = None,
    pif_directory_firm: Any | None = None,
) -> dict[str, str]:
    """Return pa.<question_id> params when the signal is strong enough.

    The current only-safe mapping is a detected modern PI case-management
    system, which supports the AIAudit data-foundation answer
    pa.case_system=3. behavioral_json and pif_directory_firm are accepted as
    explicit extension points; they are intentionally unused until a similarly
    high-confidence signal is available.
    """
    del behavioral_json, pif_directory_firm

    for signals in (contact_tech_signals, activity_tech_signals):
        if not isinstance(signals, dict):
            continue
        case_mgmt = _clean_system(signals.get("case_mgmt"))
        if case_mgmt in MODERN_CASE_MANAGEMENT_SYSTEMS:
            return {"pa.case_system": "3"}
    return {}
