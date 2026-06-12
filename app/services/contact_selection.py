"""Explainable contact-selection scoring for lead generation.

The selector is intentionally deterministic. LLMs may propose policy changes,
but the active score is computed from explicit features and policy weights so
every daily-plan contact can carry an auditable selection trace.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


DEFAULT_CONTACT_SELECTION_WEIGHTS: dict[str, Any] = {
    "selection_policy": {
        "name": "contact-selection-v1",
        "objective": "booked_qualified_conversations",
    },
    "persona": {
        "founder_owner": 100,
        "coo": 98,
        "managing_partner": 94,
        "operations_leader": 88,
        "partner": 82,
        "known_decision_maker": 70,
    },
    "firm_fit": {
        "personal_injury_marker": 18,
        "legal_marker": 10,
        "california_state": 4,
        "known_state": 2,
    },
    "relationship": {
        "pif_leadership_source": 8,
        "patients_dm_source": 6,
    },
    "email_quality": {
        "direct_named_email": 12,
        "role_inbox": -12,
        "generic_inbox": -30,
    },
    "history": {
        "no_prior_comms": 10,
        "no_existing_sequence": 8,
    },
    "risk": {
        "missing_persona": -1000,
        "non_law_firm": -1000,
        "unusable_email": -1000,
    },
}

TARGET_LEAD_PERSONA_KEYS = {
    "founder_owner",
    "coo",
    "managing_partner",
    "operations_leader",
    "partner",
}

GENERIC_LOCAL_PARTS = {
    "admin",
    "contact",
    "hello",
    "help",
    "info",
    "inquiries",
    "intake",
    "mail",
    "office",
    "support",
}
ROLE_LOCAL_PARTS = {
    "case",
    "cases",
    "claims",
    "legal",
    "records",
    "referrals",
}


@dataclass(frozen=True)
class ContactSelectionInput:
    contact_id: str
    pif_id: str
    firm_name: str
    contact_name: str
    contact_email: str
    contact_title: str
    contact_source: str
    state: str | None = None
    has_prior_comms: bool = False
    has_existing_sequence: bool = False
    front_warm_score: int = 0


@dataclass(frozen=True)
class ContactSelectionScore:
    score: int
    persona: str
    reason: str
    score_breakdown: dict[str, int]
    features: dict[str, Any]
    signals: list[str]
    suppressions: list[str]


def deep_merge_policy(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    """Return a recursive merge that preserves unknown policy keys."""
    merged = deepcopy(base)
    if not override:
        return merged
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge_policy(merged[key], value)
        else:
            merged[key] = value
    return merged


def contact_selection_weights(policy_weights: dict[str, Any] | None = None) -> dict[str, Any]:
    return deep_merge_policy(DEFAULT_CONTACT_SELECTION_WEIGHTS, policy_weights or {})


def has_usable_email(email: str | None) -> bool:
    value = (email or "").strip().lower()
    if not value or value in {"null", "none", "n/a", "na"}:
        return False
    if "email protected" in value or "[email" in value:
        return False
    return "@" in value and "." in value.rsplit("@", 1)[-1]


def classify_persona(title: str | None, source: str | None) -> tuple[str, str]:
    t = (title or "").lower()
    if any(x in t for x in (
        "founder",
        "co-founder",
        "owner",
        "chief executive",
        "ceo",
        "president",
    )):
        return "founder_owner", "founder/owner"
    if "chief operating" in t or "coo" in t:
        return "coo", "COO"
    if any(x in t for x in (
        "managing partner",
        "principal",
        "managing attorney",
        "shareholder",
    )):
        return "managing_partner", "managing partner"
    if "operations" in t or "office manager" in t:
        return "operations_leader", "operations leader"
    if "partner" in t:
        return "partner", "partner"
    if source == "patients_dm":
        return "known_decision_maker", "known decision-maker contact"
    return "missing_persona", ""


def is_target_lead_persona(title: str | None, source: str | None = None) -> bool:
    persona_key, _ = classify_persona(title, source)
    return persona_key in TARGET_LEAD_PERSONA_KEYS


def classify_email_quality(email: str | None, contact_name: str | None) -> str:
    value = (email or "").strip().lower()
    if "@" not in value:
        return "unusable_email"
    local = value.split("@", 1)[0].replace(".", " ").replace("_", " ").replace("-", " ")
    compact_local = value.split("@", 1)[0].replace(".", "").replace("_", "").replace("-", "")
    if compact_local in GENERIC_LOCAL_PARTS:
        return "generic_inbox"
    if compact_local in ROLE_LOCAL_PARTS:
        return "role_inbox"
    name_tokens = [
        token.lower()
        for token in (contact_name or "").replace(".", " ").replace("-", " ").split()
        if len(token) >= 3
    ]
    if any(token in local for token in name_tokens):
        return "direct_named_email"
    return "direct_named_email"


def firm_fit_signals(firm_name: str, title: str | None, state: str | None) -> list[str]:
    name = (firm_name or "").lower()
    title_text = (title or "").lower()
    signals: list[str] = []
    if any(marker in name or marker in title_text for marker in ("injury", "accident", "trial")):
        signals.append("personal_injury_marker")
    if any(marker in name or marker in title_text for marker in (
        "law",
        "legal",
        "attorney",
        "trial",
        "injury",
        "llp",
        "aplc",
        "plc",
        "p.c.",
        " pc",
    )):
        signals.append("legal_marker")
    if (state or "").upper() == "CA":
        signals.append("california_state")
    elif state:
        signals.append("known_state")
    return signals


def looks_like_non_law_firm(firm_name: str, title: str | None) -> bool:
    name = firm_name.lower()
    title_text = (title or "").lower()
    strong_non_law_markers = (
        "attorney service",
        "chiropractor",
        "chiropractic",
        "doctor of chiropractic",
        "lien services",
        "mri",
        "radiologist",
        "releasepoint",
        "synergy",
    )
    if any(marker in name or marker in title_text for marker in strong_non_law_markers):
        return True
    if any(signal in firm_fit_signals(firm_name, title, None) for signal in ("legal_marker", "personal_injury_marker")):
        return False
    non_law_markers = (
        "chiro",
        "clinic",
        "diagnostic",
        "financial",
        "health",
        "hospital",
        "imaging",
        "insurance",
        "medical",
        "radiology",
        "registry",
        "spine",
        "wellness",
    )
    return any(marker in name or marker in title_text for marker in non_law_markers)


def score_contact_selection(
    candidate: ContactSelectionInput,
    *,
    policy_weights: dict[str, Any] | None = None,
) -> ContactSelectionScore:
    policy = contact_selection_weights(policy_weights)
    score_breakdown: dict[str, int] = {}
    signals: list[str] = []
    suppressions: list[str] = []

    if not has_usable_email(candidate.contact_email):
        suppressions.append("unusable_email")
    if looks_like_non_law_firm(candidate.firm_name, candidate.contact_title):
        suppressions.append("non_law_firm")

    persona_key, persona_label = classify_persona(
        candidate.contact_title,
        candidate.contact_source,
    )
    if not persona_label:
        suppressions.append("missing_persona")
    else:
        score_breakdown[f"persona:{persona_key}"] = int(policy["persona"].get(persona_key, 0))
        signals.append(f"persona:{persona_key}")

    email_quality = classify_email_quality(candidate.contact_email, candidate.contact_name)
    score_breakdown[f"email_quality:{email_quality}"] = int(
        policy["email_quality"].get(email_quality, 0)
    )
    signals.append(f"email_quality:{email_quality}")

    firm_signals = firm_fit_signals(
        candidate.firm_name,
        candidate.contact_title,
        candidate.state,
    )
    for signal in firm_signals:
        score_breakdown[f"firm_fit:{signal}"] = int(policy["firm_fit"].get(signal, 0))
        signals.append(f"firm_fit:{signal}")

    if candidate.contact_source == "pif_leadership":
        score_breakdown["relationship:pif_leadership_source"] = int(
            policy["relationship"].get("pif_leadership_source", 0)
        )
        signals.append("relationship:pif_leadership_source")
    if candidate.contact_source == "patients_dm":
        score_breakdown["relationship:patients_dm_source"] = int(
            policy["relationship"].get("patients_dm_source", 0)
        )
        signals.append("relationship:patients_dm_source")

    if not candidate.has_prior_comms:
        score_breakdown["history:no_prior_comms"] = int(
            policy["history"].get("no_prior_comms", 0)
        )
        signals.append("history:no_prior_comms")
    if not candidate.has_existing_sequence:
        score_breakdown["history:no_existing_sequence"] = int(
            policy["history"].get("no_existing_sequence", 0)
        )
        signals.append("history:no_existing_sequence")

    front_policy = policy.get("front_warmth") if isinstance(policy.get("front_warmth"), dict) else {}
    front_weight = int(front_policy.get("weight") or 0)
    if front_weight and candidate.front_warm_score > 0:
        max_bonus = int(front_policy.get("max_bonus") or 75)
        bonus = min(max_bonus, int(candidate.front_warm_score) * front_weight)
        score_breakdown["front_warmth:warm_score"] = bonus
        signals.append("front_warmth:warm_score")

    if suppressions:
        for suppression in suppressions:
            score_breakdown[f"risk:{suppression}"] = int(policy["risk"].get(suppression, -1000))

    score = sum(score_breakdown.values())
    features = {
        "persona_key": persona_key,
        "persona": persona_label,
        "is_target_lead_persona": persona_key in TARGET_LEAD_PERSONA_KEYS,
        "email_quality": email_quality,
        "firm_fit_signals": firm_signals,
        "contact_source": candidate.contact_source,
        "state": candidate.state,
        "has_prior_comms": candidate.has_prior_comms,
        "has_existing_sequence": candidate.has_existing_sequence,
        "front_warm_score": candidate.front_warm_score,
    }
    reason_bits = [persona_label] if persona_label else []
    if email_quality == "direct_named_email":
        reason_bits.append("direct named email")
    elif email_quality == "generic_inbox":
        reason_bits.append("generic inbox risk")
    elif email_quality == "role_inbox":
        reason_bits.append("role inbox")
    if "personal_injury_marker" in firm_signals:
        reason_bits.append("PI/legal firm signal")
    elif "legal_marker" in firm_signals:
        reason_bits.append("legal firm signal")
    if candidate.contact_source:
        reason_bits.append(f"source {candidate.contact_source}")
    reason_bits.append("no comms history found" if not candidate.has_prior_comms else "prior comms found")
    reason_bits.append(
        "no existing sequence" if not candidate.has_existing_sequence else "existing sequence found"
    )
    if candidate.front_warm_score > 0:
        reason_bits.append(f"Front warm score {candidate.front_warm_score}")
    reason = "; ".join(reason_bits)

    return ContactSelectionScore(
        score=score,
        persona=persona_label,
        reason=reason,
        score_breakdown=score_breakdown,
        features=features,
        signals=signals,
        suppressions=suppressions,
    )
