"""PHI egress guard for rendered outbound outreach."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from app.services.llm_gateway import LLMGatewayError, call_skill_json


PHI_GUARD_CHECK_NAME = "no_patient_data_in_outreach"
_SKILL_PATH = Path(__file__).resolve().parents[1] / "skills" / "outreach-phi-egress-guard" / "SKILL.md"

_DATE = r"(?:0?[1-9]|1[0-2])[\-/\.](?:0?[1-9]|[12]\d|3[01])[\-/\.](?:19|20)\d{2}"
_DOB_NEAR_DATE_RE = re.compile(rf"\b(?:dob|d\.o\.b\.|date of birth)\b[\s:#-]{{0,24}}{_DATE}", re.I)
_DOL_RE = re.compile(rf"\b(?:dol|d\.o\.l\.|date of loss)\b[\s:#-]{{0,24}}{_DATE}", re.I)
_MRN_RE = re.compile(r"\b(?:mrn|m\.r\.n\.|medical record(?: number)?|record #)\b[\s:#-]{0,12}[A-Z0-9][A-Z0-9-]{4,}\b", re.I)
_CASE_NUMBER_RE = re.compile(r"\b(?:case|claim|matter|file)\s*(?:no\.?|number|#)\s*[:#-]?\s*[A-Z0-9][A-Z0-9-]{5,}\b", re.I)
_PATIENT_CONTEXT_RE = re.compile(
    r"\b(?:patient|claimant)\s+(?:name\s*)?[:#-]?\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b"
    r"|\b(?:patient|claimant)\b.{0,80}\b(?:MRI|CT|x-ray|diagnosis|diagnosed|surgery|treatment|injury|lumbar|cervical)\b",
    re.I | re.S,
)


def outreach_body_hash(subject: str, body: str) -> str:
    rendered = f"Subject: {subject.strip()}\n\n{body.strip()}"
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def deterministic_phi_findings(subject: str, body: str) -> list[str]:
    text = f"{subject}\n{body}"
    findings: list[str] = []
    patterns = [
        ("dob_pattern", _DOB_NEAR_DATE_RE),
        ("date_of_loss_pattern", _DOL_RE),
        ("medical_record_number_pattern", _MRN_RE),
        ("case_number_pattern", _CASE_NUMBER_RE),
        ("patient_context_phrase", _PATIENT_CONTEXT_RE),
    ]
    for name, pattern in patterns:
        if pattern.search(text):
            findings.append(name)
    return findings


def _cached_guard_result(cache: dict[str, Any], digest: str) -> dict[str, Any] | None:
    cached = cache.get(digest)
    if isinstance(cached, dict) and "passed" in cached:
        return cached
    return None


async def check_no_patient_data_in_outreach(
    *,
    subject: str,
    body: str,
    cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a policy-check result for rendered subject/body.

    Deterministic hits fail immediately. Clean deterministic text must also pass
    one LLM classifier call; gateway errors fail closed.
    """
    digest = outreach_body_hash(subject, body)
    cache_obj = cache if isinstance(cache, dict) else {}
    cached = _cached_guard_result(cache_obj, digest)
    if cached:
        return {**cached, "cached": True, "body_hash": digest}

    findings = deterministic_phi_findings(subject, body)
    if findings:
        result = {
            "passed": False,
            "detail": f"deterministic_phi:{','.join(findings)}",
            "reason": "Deterministic PHI pattern matched.",
            "deterministic_findings": findings,
            "llm_checked": False,
            "body_hash": digest,
        }
        cache_obj[digest] = result
        return result

    try:
        llm = await call_skill_json(
            skill_path=_SKILL_PATH,
            model="openclaw",
            payload={"subject": subject, "body": body},
            required_fields=["contains_phi", "reason"],
            timeout_s=150,
            max_tokens=300,
            retries=2,
            prompt_cache_key=f"outreach-phi-guard:{digest}",
            prompt_cache_retention="24h",
        )
        contains_phi = bool(llm.parsed.get("contains_phi"))
        reason = str(llm.parsed.get("reason") or "").strip()[:500]
        result = {
            "passed": not contains_phi,
            "detail": reason or ("llm_contains_phi" if contains_phi else "llm_clean"),
            "reason": reason,
            "deterministic_findings": [],
            "llm_checked": True,
            "llm_model": llm.model,
            "body_hash": digest,
        }
    except (LLMGatewayError, TimeoutError, Exception) as exc:
        # Fail closed for THIS attempt, but never cache transport errors —
        # a wedged gateway must not become a permanent verdict on the body.
        return {
            "passed": False,
            "detail": f"llm_error:{type(exc).__name__}: {str(exc)[:180]}",
            "reason": "LLM PHI classifier failed; failing closed.",
            "deterministic_findings": [],
            "llm_checked": False,
            "body_hash": digest,
        }
    cache_obj[digest] = result
    return result
