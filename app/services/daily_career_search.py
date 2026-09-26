"""Evidence-backed legal technology career search, operated by CLI or timer."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert

from app.db import AsyncSessionLocal, async_engine
from app.db.models import CareerSearchRunRow, CareerSearchStateRow, FirmContactRow, PifFirmRow
from app.services.career_job_store import PROVIDER, job_id, merge_career_postings, source_identity, same_job
from app.services.career_search_web import fetch_page, public_url
from app.services.llm_gateway import (
    LLMGatewayResponseError,
    call_skill_json,
    invoke_openclaw_tool,
    prompt_cache_metrics,
)
from app.services.pif_firm_crud import get_pif_firm_for_crud, upsert_pif_firm
from app.services.pif_job_posting_research import classify_job_posting

SKILL = Path(__file__).resolve().parents[1] / "skills/daily-pi-career-search/SKILL.md"
SEEDS = SKILL.with_name("seeds.json")
LOCK_ID = 734985210
SCHEMA_LOCK_ID = 734985216
RUN_TIMEOUT_SECONDS = 1800
RUN_CLEANUP_RESERVE_SECONDS = 60
MIN_LLM_CALL_SECONDS = 30
LLM_TIMEOUT_SECONDS = 420
# Shared recruiting platforms are evidence sources, never employer identities.
SHARED_RECRUITING_DOMAINS = frozenset({
    "jobvite.com", "greenhouse.io", "lever.co", "ashbyhq.com", "smartrecruiters.com",
    "rippling.com", "myworkdayjobs.com", "workdayjobs.com", "applytojob.com",
    "bamboohr.com", "icims.com", "recruitee.com", "workable.com", "paylocity.com",
    "adp.com", "indeed.com", "linkedin.com", "ziprecruiter.com", "glassdoor.com",
})
PI_QUERIES = [
    '"personal injury" "software engineer" remote OR "Latin America"',
    '"personal injury law firm" "AI" automation engineer remote',
    '"personal injury" "data engineer" OR "analytics" careers',
    '"personal injury" "voice" OR "contact center platforms" careers remote',
    '"personal injury law firm" "workflow" technology developer Colombia LATAM',
]
LEGAL_AI_QUERIES = [
    '"legal tech" ("AI agent" OR "agentic AI") engineer remote Latin America',
    '("law firm" OR legal) ("AI engineer" OR "LLM engineer") remote Colombia LATAM',
    '("contract management" OR e-discovery OR litigation) ("applied AI" OR "automation engineer") remote',
    '(legal OR law) ("agent developer" OR "AI automation") careers remote Americas',
    '(Filevine OR Clio OR legal operations) ("AI engineer" OR "workflow automation") remote',
]
# Backwards-compatible name used by older tests and operators.
QUERIES = PI_QUERIES
_schema_ready = False
_schema_lock = asyncio.Lock()


class CareerSearchBudgetExceeded(TimeoutError):
    """The bounded run lacks enough time for another model call."""


def deadline_kwargs(deadline: float | None) -> dict:
    return {"deadline": deadline} if deadline is not None else {}


class SearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)
    enabled: bool = False
    timezone: str = "America/Bogota"
    local_time: str = "08:00"
    max_candidates: int = Field(10, ge=1, le=20)
    max_rechecks: int = Field(8, ge=0, le=20)
    max_sources: int = Field(6, ge=1, le=12)
    max_attempts: int = Field(3, ge=1, le=4)
    source_urls: list[HttpUrl] = Field(default_factory=lambda: [
        "https://www.ciglaw.com/", "https://jobs.jobvite.com/jacobyandmeyerscareers/jobs",
        "https://topdoglaw.com/careers/all",
    ], max_length=100)

    @model_validator(mode="after")
    def schedule_valid(self):
        ZoneInfo(self.timezone)
        time.fromisoformat(self.local_time)
        if len(self.local_time) != 5:
            raise ValueError("local_time must be HH:MM")
        return self


class SearchProfile(BaseModel):
    """Operator intent for a manual Job Agent search; never grants application authority."""
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field("Job Agent target-job search", min_length=1, max_length=120)
    target_roles: str = Field(min_length=1, max_length=2000)
    preferred_industries: str = Field(min_length=1, max_length=2000)
    location_preferences: str = Field(min_length=1, max_length=2000)
    prefer_overseas_employers: bool = True
    source_ids: list[str] = Field(default_factory=list, max_length=30)
    source_urls: list[HttpUrl] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def configured_lists_not_empty(self):
        if not any(value.strip() for value in re.split(r"[,;\n]+", self.target_roles)):
            raise ValueError("target_roles must include at least one role")
        if not any(value.strip() for value in re.split(r"[,;\n]+", self.preferred_industries)):
            raise ValueError("preferred_industries must include at least one industry")
        return self


class CandidateFields(BaseModel):
    firm_name: str = Field(min_length=1, max_length=255)
    canonical_domain: str = Field(min_length=3, max_length=255)
    source_url: HttpUrl
    employer_evidence_url: HttpUrl
    title: str = Field(min_length=1, max_length=300)
    contact_urls: list[HttpUrl] = Field(default_factory=list, max_length=5)


class UrlImportIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    firm_name: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=300)
    source_url: HttpUrl


class Candidate(CandidateFields):
    @model_validator(mode="after")
    def domain_valid(self):
        from app.services.front_sync import normalize_domain, is_consumer_domain
        domain = normalize_domain(self.canonical_domain)
        evidence_domain = normalize_domain(str(self.employer_evidence_url))
        if not domain or domain != evidence_domain or is_consumer_domain(domain):
            raise ValueError("official domain must match employer identity evidence")
        if any(domain == host or domain.endswith("." + host) for host in SHARED_RECRUITING_DOMAINS):
            raise ValueError("shared recruiting platform cannot be the canonical employer domain")
        for url in self.contact_urls:
            contact_domain = normalize_domain(str(url))
            if contact_domain != domain and not contact_domain.endswith("." + domain):
                raise ValueError("contact source must use the official employer domain")
        self.canonical_domain = domain
        return self


def shared_recruiting_source(url: str) -> bool:
    """Return whether a URL is mechanically hosted by a known shared platform."""
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    return any(host == domain or host.endswith("." + domain)
               for domain in SHARED_RECRUITING_DOMAINS)


def official_page_transport_fallbacks(url: str) -> list[str]:
    """Return same-origin machine-readable transports for a blocked public page.

    This is a mechanical fetch fallback, not employer-identity evidence by
    itself. The resulting content must still pass the structured verifier and
    exact excerpt checks before storage.
    """
    parts = urlsplit(url)
    path_parts = [segment for segment in parts.path.split("/") if segment]
    if parts.scheme != "https" or not parts.hostname or not path_parts:
        return []
    slug = path_parts[-1]
    query = urlencode({"slug": slug, "_fields": "link,title,content"}, quote_via=quote)
    return [urlunsplit(("https", parts.netloc, "/wp-json/wp/v2/pages", query, ""))]


async def fetch_direct_import_employer_page(
    candidate: Candidate,
    cache: dict[str, dict],
    audit: dict,
) -> tuple[Candidate, dict]:
    """Fetch official identity evidence, recovering blocked WordPress pages."""
    employer_url = str(candidate.employer_evidence_url)
    try:
        if employer_url not in cache:
            cache[employer_url] = await fetch_page(employer_url)
        return candidate, cache[employer_url]
    except Exception as original_error:
        fallback_errors = []
        for fallback_url in official_page_transport_fallbacks(employer_url):
            try:
                if fallback_url not in cache:
                    cache[fallback_url] = await fetch_page(fallback_url)
                page = cache[fallback_url]
                if page["http_status"] != 200:
                    raise ValueError(f"HTTP {page['http_status']}")
                replacement = Candidate.model_validate({
                    **candidate.model_dump(mode="json"),
                    "employer_evidence_url": fallback_url,
                })
                audit.setdefault("official_evidence_fetch_fallbacks", []).append({
                    "blocked_url": employer_url,
                    "blocked_error": str(original_error)[:1000],
                    "evidence_url": fallback_url,
                    "transport": "wordpress_rest_api",
                })
                return replacement, page
            except Exception as exc:
                fallback_errors.append({"source_url": fallback_url, "error": str(exc)[:1000]})
        if fallback_errors:
            audit.setdefault("official_evidence_fetch_errors", []).extend(fallback_errors)
        raise original_error


class Excerpt(BaseModel):
    source_url: HttpUrl
    text: str = Field(min_length=1, max_length=1200)


class ApplicationContact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(pattern=r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", max_length=320)
    name: str = Field("", max_length=255)
    title: str = Field("", max_length=255)
    kind: Literal["recruiting", "routing"]
    evidence: Excerpt

    @field_validator("name", "title", mode="before")
    @classmethod
    def optional_labels(cls, value):
        return "" if value is None else value


class Decision(BaseModel):
    candidate_id: str
    status: Literal["active", "closed", "unverified"]
    reason: str
    direct_pi_employer: bool = False
    legal_domain_employer: bool = False
    legal_domain_kind: Literal["law_firm", "legal_tech", "legal_services", "unclear"] = "unclear"
    preferred_industry_employer: bool = False
    matched_preferred_industry: str | None = None
    target_role_match: bool = False
    matched_target_role: str | None = None
    technology_role: bool = False
    title: str
    requisition_id: str | None = None
    ats_provider: str | None = None
    posted_date: date | None = None
    ats_created_at: datetime | None = None
    ats_updated_at: datetime | None = None
    description_summary: str = ""
    location: str = ""
    employment_type: str = ""
    work_arrangement: Literal["remote", "hybrid", "onsite", "unclear"] = "unclear"
    remote_scope: Literal["global", "country_restricted", "location_restricted", "not_remote", "unclear"] = "unclear"
    colombia_eligibility: Literal["explicit", "conditional_latam", "restricted", "unknown"] = "unknown"
    geography_note: str = ""
    role_category: Literal["technology_data", "legal_operations", "legal_support", "other"] = "other"
    trigger_tags: list[str] = Field(default_factory=list)
    technology_mentions: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)
    employer_evidence: Excerpt | None = None
    role_evidence: Excerpt | None = None
    status_evidence: Excerpt | None = None
    geography_evidence: Excerpt | None = None
    date_evidence: Excerpt | None = None
    application_contacts: list[ApplicationContact] = Field(default_factory=list, max_length=12)


def now_utc():
    return datetime.now(timezone.utc)


def preferred_industry_labels(profile: SearchProfile) -> list[str]:
    """Parse the operator's configurable employer industries without inventing taxonomy."""
    labels = []
    seen = set()
    for value in re.split(r"[,;\n]+", profile.preferred_industries):
        label = " ".join(value.split())
        key = label.casefold()
        if label and key not in seen:
            labels.append(label)
            seen.add(key)
    return labels


def target_role_labels(profile: SearchProfile) -> list[str]:
    """Parse the saved target-role field using the same visible delimiters as industries."""
    labels = []
    seen = set()
    for value in re.split(r"[,;\n]+", profile.target_roles):
        label = " ".join(value.split())
        key = label.casefold()
        if label and key not in seen:
            labels.append(label)
            seen.add(key)
    return labels


def profile_queries(profile: SearchProfile, day_number: int) -> list[str]:
    """Build one bounded discovery query per configured employer industry."""
    industries = preferred_industry_labels(profile)
    roles = target_role_labels(profile)
    role_clause = " OR ".join(f'"{role}"' for role in roles)
    return [f'"{industry}" ({role_clause}) jobs careers remote' for industry in industries]


async def configured_job_agent_profile() -> SearchProfile:
    """Load the one search profile shared by the daily timer and Search now."""
    from app.services import job_agent
    settings = await job_agent.configuration()
    config = job_agent.JobAgentConfig.model_validate(settings["config"])
    return SearchProfile.model_validate(job_agent.search_profile(config))


def configured_legacy_legal_match(decision: Decision, profile: SearchProfile) -> bool:
    """Honor older legal-domain decisions only when settings still allow that domain."""
    labels = [" ".join(label.split()).casefold() for label in preferred_industry_labels(profile)]
    terms = {
        "law_firm": ("law firm", "personal injury", "legal services"),
        "legal_tech": ("legal tech", "legal technology"),
        "legal_services": ("legal service",),
        "unclear": (),
    }[decision.legal_domain_kind]
    if decision.direct_pi_employer:
        terms = (*terms, "personal injury")
    return decision.legal_domain_employer and any(term in label for label in labels for term in terms)


async def ensure_tables():
    """Additive fallback for installations where the migration has not run yet."""
    global _schema_ready
    if _schema_ready:
        return
    async with _schema_lock:
        if _schema_ready:
            return
        async with async_engine.begin() as connection:
            await connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SCHEMA_LOCK_ID})
            for model in (CareerSearchStateRow, CareerSearchRunRow):
                await connection.run_sync(model.__table__.create, checkfirst=True)
        _schema_ready = True


def next_due(config: SearchConfig, completed_days: set[str], *, now: datetime) -> datetime:
    local = now.astimezone(ZoneInfo(config.timezone))
    day = local.date()
    if day.isoformat() in completed_days:
        day += timedelta(days=1)
    return datetime.combine(day, time.fromisoformat(config.local_time), tzinfo=ZoneInfo(config.timezone)).astimezone(timezone.utc)


def run_consumes_daily_slot(run) -> bool:
    """A bounded scheduled run is once daily even when some work was partial."""
    result = run.result or {}
    return (run.status in {"completed", "partial"}
            and not result.get("retry_of")
            and not result.get("manual_search")
            and result.get("search_trigger") in {None, "scheduled"})


async def configuration(changes: dict | None = None) -> SearchConfig:
    await ensure_tables()
    async with AsyncSessionLocal() as session:
        await session.execute(insert(CareerSearchStateRow).values(
            id="daily_pi_tech", config=SearchConfig().model_dump(mode="json"), updated_at=now_utc(),
        ).on_conflict_do_nothing(index_elements=["id"]))
        state = await session.get(CareerSearchStateRow, "daily_pi_tech", with_for_update=True)
        config = SearchConfig.model_validate({**state.config, **(changes or {})})
        if changes:
            state.config = config.model_dump(mode="json")
            state.updated_at = now_utc()
        await session.commit()
        return config


def serialize_run(row: CareerSearchRunRow) -> dict:
    result = json.loads(json.dumps(row.result or {}))
    # Older runs recorded a final, evidence-backed `unverified` decision as an
    # operational error. Reconstruct those candidate exclusions from the
    # persisted decision so status remains truthful without changing history.
    rejected_pairs = {
        (str(entry.get("candidate", {}).get("source_url") or ""),
         str(entry.get("decision", {}).get("reason") or ""))
        for entry in result.get("decisions", [])
        if entry.get("decision", {}).get("status") == "unverified"
    }
    errors = []
    exclusions = list(result.get("candidate_rejections") or [])
    known_exclusions = {(str(item.get("source_url") or ""), str(item.get("reason") or ""))
                        for item in exclusions}
    for error in result.get("errors", []):
        pair = (str(error.get("source_url") or ""), str(error.get("error") or ""))
        if pair in rejected_pairs:
            if pair not in known_exclusions:
                exclusions.append({"source_url": pair[0], "reason": pair[1]})
                known_exclusions.add(pair)
        else:
            errors.append(error)
    result["errors"] = errors
    result["candidate_rejections"] = exclusions
    display_status = "completed" if row.status == "partial" and not errors else row.status
    return {"id": row.id, "scheduled_day": row.scheduled_day, "status": display_status,
            "started_at": row.started_at.isoformat(),
            "completed_at": row.completed_at.isoformat() if row.completed_at else None, "result": result}


async def status() -> dict:
    config = await configuration()
    async with AsyncSessionLocal() as session:
        runs = list((await session.scalars(select(CareerSearchRunRow).order_by(CareerSearchRunRow.started_at.desc()).limit(10))).all())
    completed = {r.scheduled_day for r in runs if run_consumes_daily_slot(r)}
    return {"config": config.model_dump(mode="json"), "next_due_at": next_due(config, completed, now=now_utc()).isoformat() if config.enabled else None,
            "schedule_enabled": config.enabled, "timer_installation": "external; verify systemctl timers",
            "runs": [serialize_run(r) for r in runs]}


async def checkpoint(run_id: str, result: dict, final_status: str | None = None):
    async with AsyncSessionLocal() as session:
        run = await session.get(CareerSearchRunRow, run_id, with_for_update=True)
        run.result = json.loads(json.dumps(result))
        if final_status:
            run.status = final_status
            run.completed_at = now_utc()
        await session.commit()


async def reconcile_interrupted_manual_runs() -> int:
    """Close manual searches whose worker disappeared during a backend restart.

    Every real search holds the career-search advisory lock for its full run.
    Acquiring it here proves that no search worker remains, including one in a
    different process.
    """
    await ensure_tables()
    async with async_engine.connect() as connection:
        locked = await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_ID})
        await connection.commit()
        if not locked:
            return 0
        try:
            completed_at = now_utc()
            async with AsyncSessionLocal() as session:
                rows = (await session.scalars(
                    select(CareerSearchRunRow).where(CareerSearchRunRow.status == "running")
                )).all()
                recovered = 0
                for row in rows:
                    result = dict(row.result or {})
                    if not result.get("manual_search"):
                        continue
                    errors = list(result.get("errors") or [])
                    errors.append({
                        "phase": "run",
                        "error": "Search worker stopped during a backend restart. No automatic retry was started.",
                    })
                    result.update({"errors": errors, "interrupted_reason": "backend_restart"})
                    row.result = result
                    row.status = "interrupted"
                    row.completed_at = completed_at
                    recovered += 1
                if recovered:
                    await session.commit()
                return recovered
        finally:
            await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_ID})
            await connection.commit()


async def llm(payload: dict, required: str, config: SearchConfig, audit: dict, run_id: str,
              *, deadline: float | None = None, lane: str | None = None,
              allow_tools: bool | None = None):
    verification = required == "decisions"
    attempts = 1 if payload["mode"] in {
        "verification_repair", "candidate_repair", "url_import", "url_import_identity",
        "url_import_enrichment",
    } else config.max_attempts
    for attempt in range(attempts):
        structured_failure = None

        async def observe_attempt(event: dict):
            nonlocal structured_failure
            if event.get("phase") != "failed":
                return
            # The gateway includes parsed_response only for JSON/shape failures;
            # transport failures may also have raw_response (e.g. a 502 body).
            if "parsed_response" in event:
                structured_failure = dict(event)
            audit.setdefault("gateway_failures", []).append({
                **event, "mode": payload["mode"], "runner_attempt": attempt + 1,
                "raw_response": audit_value(event.get("raw_response")),
                "parsed_response": audit_value(event.get("parsed_response")),
                "usage": event.get("usage"),
                "prompt_cache_metrics": prompt_cache_metrics(event.get("usage")),
            })
            if isinstance(event.get("usage"), dict):
                audit["usage"].append(event["usage"])
                audit.setdefault("prompt_cache_metrics", []).append(prompt_cache_metrics(event["usage"]))
            await checkpoint(run_id, audit)

        try:
            call_timeout = float(LLM_TIMEOUT_SECONDS)
            if deadline is not None:
                call_timeout = min(call_timeout, deadline - asyncio.get_running_loop().time())
                if call_timeout < MIN_LLM_CALL_SECONDS:
                    raise CareerSearchBudgetExceeded(
                        f"{payload['mode']} skipped because the run time budget was exhausted")
            audit["llm_calls"] += 1
            await checkpoint(run_id, audit)
            tool_access = (
                payload["mode"] in {"discovery", "retry_discovery"}
                if allow_tools is None else allow_tools
            )
            request = call_skill_json(skill_path=SKILL, payload=payload, required_fields=[required],
                model="openclaw/main", timeout_s=max(1, int(call_timeout)), max_tokens=9000, retries=1,
                schema_repair_retries=0 if verification or payload["mode"] == "candidate_repair" else 1,
                attempt_observer=observe_attempt,
                prompt_cache_key="possibleos:career-search:v4",
                allow_tools=tool_access,
                lane=lane or os.getenv("OPENCLAW_RPC_BATCH_LANE", "possibleos-batch"))
            task = asyncio.create_task(request)
            done, _ = await asyncio.wait({task}, timeout=call_timeout)
            if not done:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise CareerSearchBudgetExceeded(
                    f"{payload['mode']} exceeded its remaining {call_timeout:.0f}-second run budget")
            response = task.result()
            audit["usage"].append(response.usage or {})
            audit.setdefault("prompt_cache_metrics", []).append(prompt_cache_metrics(response.usage))
            if verification:
                # Candidate-level validation owns the single explicit repair budget.
                return response.parsed
            if not isinstance(response.parsed[required], list):
                raise ValueError(f"{required} must be an array")
            return response.parsed
        except CareerSearchBudgetExceeded:
            raise
        except Exception as exc:
            if verification and structured_failure is not None:
                failure = {"invalid_response": audit_value(structured_failure.get("raw_response")),
                           "parsed_response": audit_value(structured_failure.get("parsed_response")),
                           "validation_error": structured_failure.get("error") or str(exc),
                           "gateway_error": str(exc)}
                await checkpoint(run_id, audit)
                return failure
            if verification and isinstance(exc, LLMGatewayResponseError):
                return {"invalid_response": audit_value(exc.raw_response), "validation_error": str(exc),
                        "parsed_response": exc.parsed_response}
            audit["attempt_errors"].append({"phase": payload["mode"], "attempt": attempt + 1, "error": str(exc)[:1000]})
            await checkpoint(run_id, audit)
            if attempt + 1 == attempts:
                raise
            await asyncio.sleep(min(60, 5 * 2 ** attempt) + random.random())


def audit_value(value):
    encoded = json.dumps(value, ensure_ascii=True, default=str)
    if len(encoded) <= 60000:
        return value
    return {"truncated": True, "sha256": hashlib.sha256(encoded.encode()).hexdigest(), "preview": encoded[:60000]}


def page_audit(pages: list[dict]) -> list[dict]:
    return [{"requested_url": page["requested_url"], "final_url": page.get("final_url"),
             "http_status": page.get("http_status"), "characters": len(page["content"]),
             "sha256": hashlib.sha256(page["content"].encode()).hexdigest(),
             "excerpt": page["content"][:500]} for page in pages]


def evidence_source_matches(original, pages: list[dict]) -> dict:
    """Diagnose exact quotes on the wrong page, without accepting or rewriting them."""
    matches = {}
    if not isinstance(original, dict):
        return matches
    for field, evidence in original.items():
        if not field.endswith("_evidence") or not isinstance(evidence, dict):
            continue
        quote = evidence.get("text")
        if not isinstance(quote, str) or not quote.strip():
            continue
        quote = " ".join(quote.split()).casefold()
        matches[field] = [p["requested_url"] for p in pages
                          if quote in " ".join(p["content"].split()).casefold()]
    return matches


def evidence_excerpt_matches(evidence: Excerpt | None, pages: list[dict]) -> bool:
    if evidence is None:
        return True
    page = next((item for item in pages
                 if source_identity(item["requested_url"]) == source_identity(str(evidence.source_url))), None)
    if page is None:
        return False
    quote = " ".join(evidence.text.split()).casefold()
    content = " ".join(page["content"].split()).casefold()
    return quote in content


def downgrade_unverified_optional_evidence(decision: Decision, pages: list[dict]) -> Decision:
    """Fail optional date/location claims closed without losing a verified role."""
    updates = {}
    if decision.direct_pi_employer and (
        not decision.legal_domain_employer or decision.legal_domain_kind != "law_firm"
    ):
        updates["direct_pi_employer"] = False
    if not evidence_excerpt_matches(decision.geography_evidence, pages):
        updates.update({
            "work_arrangement": "unclear",
            "remote_scope": "unclear",
            "colombia_eligibility": "unknown",
            "geography_note": "Location eligibility was not verified from the supplied source.",
            "geography_evidence": None,
        })
    if not evidence_excerpt_matches(decision.date_evidence, pages):
        updates.update({"posted_date": None, "date_evidence": None})
    return decision.model_copy(update=updates) if updates else decision


def inspect_verification(batch: list[dict], response, *, today: date, phase: str, audit: dict,
                         search_profile: SearchProfile | None = None,
                         direct_import: bool = False):
    accepted, failed = [], []
    rows = response.get("decisions") if isinstance(response, dict) else None
    expected = {item["candidate_id"] for item in batch}
    if isinstance(rows, list):
        unexpected = [row for row in rows if not isinstance(row, dict)
                      or not isinstance(row.get("candidate_id"), str) or row["candidate_id"] not in expected]
        if unexpected:
            audit.setdefault("verification_rejections", []).append({"phase": phase,
                "validation_error": "unknown or missing candidate ID", "original_decision": audit_value(unexpected)})
    for item in batch:
        matches = [row for row in rows if isinstance(row, dict) and row.get("candidate_id") == item["candidate_id"]] if isinstance(rows, list) else []
        original = matches[0] if len(matches) == 1 else matches if matches else response
        try:
            if not isinstance(rows, list):
                raise ValueError("verification decisions must be an array: " + str(response.get("validation_error", "invalid response") if isinstance(response, dict) else "invalid response"))
            if len(matches) != 1:
                raise ValueError(f"expected exactly one decision for {item['candidate_id']}; got {len(matches)}")
            decision = Decision.model_validate(original)
            if direct_import:
                decision = downgrade_unverified_optional_evidence(decision, item["pages"])
            validate_decision(decision, item["pages"], today=today,
                              search_profile=search_profile, direct_import=direct_import)
            accepted.append((item, decision))
        except ValueError as exc:
            error = str(exc)[:4000]
            rejected = {"phase": phase, "candidate_id": item["candidate_id"],
                "candidate": item["candidate"].model_dump(mode="json"),
                "original_decision": audit_value(original), "validation_error": error,
                "evidence_source_matches": evidence_source_matches(original, item["pages"]),
                "pages": page_audit(item["pages"])}
            audit.setdefault("verification_rejections", []).append(rejected)
            failed.append((item, rejected))
    return accepted, failed


async def verified_decisions(batch: list[dict], config: SearchConfig, audit: dict, run_id: str, *, today: date,
                             search_profile: SearchProfile | None = None, deadline: float | None = None,
                             direct_import: bool = False):
    profile = search_profile.model_dump(mode="json") if search_profile else None
    lane = (os.getenv("OPENCLAW_RPC_INTERACTIVE_LANE", "possibleos-interactive")
            if direct_import else None)
    payload = {"mode": "verification", "as_of": today.isoformat(), "search_profile": profile,
               "direct_import": direct_import, "candidates": [
        {"candidate_id": item["candidate_id"], **item["candidate"].model_dump(mode="json"), "pages": item["pages"]} for item in batch
    ]}
    try:
        response = await llm(payload, "decisions", config, audit, run_id,
                             lane=lane, **deadline_kwargs(deadline))
    except Exception as exc:
        error = str(exc)[:1000] or type(exc).__name__
        audit.setdefault("verification_rejections", []).append({
            "phase": "initial_transport", "validation_error": error,
            "candidate_ids": [item["candidate_id"] for item in batch],
        })
        for item in batch:
            audit["errors"].append({"candidate_id": item["candidate_id"],
                "source_url": str(item["candidate"].source_url), "phase": "verification",
                "status": "unverified", "error": error})
            if item.get("tracked"):
                await mark_checked(item, closed=False, reason=error)
        await checkpoint(run_id, audit)
        return
    accepted, failed = inspect_verification(batch, response, today=today, phase="initial", audit=audit,
                                            search_profile=search_profile, direct_import=direct_import)
    await checkpoint(run_id, audit)
    # Yield valid rows before a repair can time out, so their ingests are durable.
    for pair in accepted:
        yield pair
    if not failed:
        return
    audit["repair_calls"] = audit.get("repair_calls", 0) + 1
    repair_payload = {"mode": "verification_repair", "as_of": today.isoformat(),
                      "search_profile": profile, "direct_import": direct_import, "candidates": [
        {"candidate_id": item["candidate_id"], **item["candidate"].model_dump(mode="json"),
         "pages": item["pages"], "original_decision": rejection["original_decision"],
         "evidence_source_matches": rejection["evidence_source_matches"],
         "validation_error": rejection["validation_error"]} for item, rejection in failed
    ]}
    await checkpoint(run_id, audit)
    try:
        repaired = await llm(repair_payload, "decisions", config, audit, run_id,
                             lane=lane, **deadline_kwargs(deadline))
        accepted, remaining = inspect_verification([item for item, _ in failed], repaired, today=today,
                                                   phase="repair", audit=audit,
                                                   search_profile=search_profile,
                                                   direct_import=direct_import)
    except Exception as exc:
        accepted = []
        remaining = [(item, {"validation_error": f"repair call failed: {str(exc)[:1000] or type(exc).__name__}"}) for item, _ in failed]
        audit.setdefault("verification_rejections", []).append({"phase": "repair_transport", "validation_error": str(exc)[:1000]})
    await checkpoint(run_id, audit)
    for pair in accepted:
        yield pair
    for item, rejection in remaining:
        audit["errors"].append({"candidate_id": item["candidate_id"], "source_url": str(item["candidate"].source_url),
            "phase": "verification_repair", "status": "unverified", "error": rejection["validation_error"]})
        if item.get("tracked"):
            await mark_checked(item, closed=False, reason=rejection["validation_error"][:1000])
    await checkpoint(run_id, audit)


def validate_decision(decision: Decision, pages: list[dict], *, today: date,
                      search_profile: SearchProfile | None = None,
                      direct_import: bool = False) -> None:
    content = {p["requested_url"]: " ".join(p["content"].split()).casefold() for p in pages}
    for field in ("employer_evidence", "role_evidence", "status_evidence", "geography_evidence", "date_evidence"):
        evidence = getattr(decision, field)
        if evidence and " ".join(evidence.text.split()).casefold() not in content.get(str(evidence.source_url), ""):
            raise ValueError(f"{field} excerpt not found in fetched source")
    if decision.status == "active":
        if search_profile and decision.preferred_industry_employer:
            configured = {" ".join(label.split()).casefold() for label in preferred_industry_labels(search_profile)}
            matched = " ".join((decision.matched_preferred_industry or "").split()).casefold()
            if not matched or matched not in configured:
                raise ValueError("matched preferred industry is not present in the saved search profile")
        elif decision.matched_preferred_industry:
            raise ValueError("matched preferred industry requires preferred_industry_employer")
        if search_profile and decision.target_role_match:
            configured_roles = {" ".join(label.split()).casefold() for label in target_role_labels(search_profile)}
            matched_role = " ".join((decision.matched_target_role or "").split()).casefold()
            if not matched_role or matched_role not in configured_roles:
                raise ValueError("matched target role is not present in the saved search profile")
        elif search_profile and decision.matched_target_role:
            raise ValueError("matched target role requires target_role_match")
        employer_matches = ((decision.preferred_industry_employer
                             or configured_legacy_legal_match(decision, search_profile))
                            if search_profile else decision.direct_pi_employer)
        role_matches = decision.target_role_match if search_profile else decision.technology_role
        if not direct_import:
            if search_profile and not employer_matches:
                raise ValueError("employer is not in a verified configured industry")
            if search_profile and not role_matches:
                raise ValueError("role does not match a configured target role")
            if not search_profile and (not employer_matches or not role_matches):
                raise ValueError("not a direct PI technology role")
        if not all((decision.employer_evidence, decision.role_evidence, decision.status_evidence)):
            raise ValueError("active job lacks required live evidence")
        if decision.posted_date and (not decision.date_evidence or decision.posted_date > today):
            raise ValueError("publication date lacks evidence or is in the future")
        if (decision.remote_scope != "unclear" or decision.colombia_eligibility != "unknown") and not decision.geography_evidence:
            raise ValueError("geographic classification lacks evidence")
        if decision.remote_scope == "global" and decision.colombia_eligibility == "restricted":
            raise ValueError("contradictory global and restricted geography")
        from app.services.job_agent_research import _possibleos_contact_kind, organization_domain_matches
        official_host = urlsplit(str(decision.employer_evidence.source_url)).hostname or ""
        for contact in decision.application_contacts:
            page = next((item for item in pages
                         if source_identity(item["requested_url"])
                         == source_identity(str(contact.evidence.source_url))), None)
            content = page["content"] if page and page.get("http_status", 200) == 200 else ""
            if contact.email.casefold() not in content.casefold():
                raise ValueError("application contact email not found in fetched source")
            if " ".join(contact.evidence.text.split()).casefold() not in " ".join(content.split()).casefold():
                raise ValueError("application contact evidence excerpt not found in fetched source")
            if not organization_domain_matches(contact.email, official_host):
                raise ValueError("application contact email must use the verified employer domain")
            kind = _possibleos_contact_kind({
                "email": contact.email, "title": contact.title, "research_title": contact.title,
            })
            if not kind or kind[0] != contact.kind:
                raise ValueError("application contact is not a suitable recruiting or routing contact")


def to_posting(candidate: Candidate, decision: Decision, *, checked_at: datetime) -> dict:
    payload = decision.model_dump(mode="json", exclude={"candidate_id", "application_contacts"})
    payload.update({"source_url": str(candidate.source_url), "source_name": "Verified employer / ATS",
        "employer_posted_date": payload["posted_date"], "first_seen_at": checked_at.isoformat(),
        "last_checked_at": checked_at.isoformat(), "last_verified_at": checked_at.isoformat(),
        "discovery_provider": PROVIDER, "employer_evidence_url": str(candidate.employer_evidence_url),
        "remote_eligibility": decision.geography_note,
        "recency_label": "confirmed_last_30_days" if decision.posted_date and decision.posted_date >= checked_at.date() - timedelta(days=30) else "publication_date_unknown" if not decision.posted_date else "older_tracked_job"})
    classified = classify_job_posting(payload, classified_at=checked_at)
    classified.update({key: payload[key] for key in ("work_arrangement", "remote_scope", "role_category", "trigger_tags", "technology_mentions")})
    classified.update({"global_remote": decision.remote_scope == "global", "global_remote_evidence": [decision.geography_evidence.text] if decision.geography_evidence else [],
        "classification_provider": PROVIDER, "classification_version": "daily-career-v1", "gtm_relevance": "high"})
    classified["id"] = job_id(candidate.canonical_domain, classified)
    return classified


async def ingest(candidate: Candidate, posting: dict) -> dict:
    existing = await get_pif_firm_for_crud(candidate.canonical_domain)
    if existing:
        firm_id = existing["id"]
    else:
        # Canonical upsert resolves aliases; never attach to an employer name alone.
        entity_type = "pi_law_firm" if posting.get("direct_pi_employer") else {
            "law_firm": "law_firm", "legal_tech": "legal_tech_company",
            "legal_services": "legal_services",
        }.get(posting.get("legal_domain_kind"))
        if not entity_type:
            entity_type = re.sub(r"[^a-z0-9]+", "_", str(
                posting.get("matched_preferred_industry") or "company"
            ).casefold()).strip("_")[:64] or "company"
        created = await upsert_pif_firm({"firm_name": candidate.firm_name, "canonical_website": candidate.canonical_domain,
            "entity_type": entity_type})
        firm_id = created["firm_id"]
    async with AsyncSessionLocal() as session:
        firm = await session.get(PifFirmRow, firm_id, with_for_update=True)
        data = dict(firm.research_data or {})
        jobs = dict(data.get("job_postings") or {})
        merged, added = merge_career_postings(jobs.get("postings") or [], [posting])
        jobs.update({"postings": merged, "has_recent_openings": any(p.get("status") != "closed" for p in merged)})
        data["job_postings"] = jobs
        firm.research_data = data
        firm.updated_at = now_utc()
        await session.commit()
    stored = next(p for p in merged if same_job(p, posting))
    return {"firm_id": firm_id, "job_id": stored.get("id"), "added": added, "source_url": posting["source_url"]}


async def ingest_application_contacts(firm_id: str, contacts: list[ApplicationContact]) -> dict:
    """Upsert source-verified firm contacts once so every role can reuse them."""
    counts = {"verified": len(contacts), "inserted": 0, "updated": 0, "existing": 0}
    if not contacts:
        return counts
    observed_at = now_utc()
    async with AsyncSessionLocal() as session:
        for contact in contacts:
            email = contact.email.strip().casefold()
            row = await session.scalar(select(FirmContactRow).where(
                FirmContactRow.pif_id == firm_id,
                func.lower(FirmContactRow.email) == email,
            ).limit(1))
            signal = {
                "kind": contact.kind,
                "source_url": str(contact.evidence.source_url),
                "evidence": contact.evidence.text,
                "observed_at": observed_at.isoformat(),
            }
            if row:
                changed = False
                if not row.full_name and contact.name:
                    row.full_name = contact.name; changed = True
                if not row.first_name and contact.name:
                    row.first_name = contact.name.split()[0]; changed = True
                if not row.title and contact.title:
                    row.title = contact.title; changed = True
                if not row.research_title and contact.title:
                    row.research_title = contact.title; changed = True
                signals = dict(row.tech_signals or {})
                if signals.get("job_search_contact") != signal:
                    signals["job_search_contact"] = signal
                    row.tech_signals = signals
                    changed = True
                counts["updated" if changed else "existing"] += 1
                continue
            display_name = contact.name.strip() or ("Recruiting" if contact.kind == "recruiting" else "Office")
            session.add(FirmContactRow(
                id=uuid.uuid4().hex,
                pif_id=firm_id,
                full_name=display_name,
                first_name=display_name.split()[0],
                email=email,
                title=contact.title or None,
                research_title=contact.title or None,
                source="job_search",
                tech_signals={"job_search_contact": signal},
            ))
            counts["inserted"] += 1
        await session.commit()
    return counts


async def replay_url_import_evidence(source_url: str, previous_runs: list[tuple[str, dict]],
                                     *, checked_at: datetime) -> dict | None:
    """Reuse a prior model decision only after fresh exact-evidence validation."""
    for previous_run_id, result in previous_runs:
        rejections = result.get("verification_rejections") if isinstance(result, dict) else None
        for rejection in reversed(rejections or []):
            try:
                candidate = Candidate.model_validate(rejection["candidate"])
                if source_identity(str(candidate.source_url)) != source_identity(source_url):
                    continue
                decision = Decision.model_validate(rejection["original_decision"])
                urls = list(dict.fromkeys([
                    str(candidate.source_url), str(candidate.employer_evidence_url),
                    *(str(url) for url in candidate.contact_urls),
                ]))
                pages = [await fetch_page(url) for url in urls]
                if any(page["http_status"] != 200 for page in pages[:2]):
                    continue
                decision = downgrade_unverified_optional_evidence(decision, pages)
                validate_decision(decision, pages, today=checked_at.date(), direct_import=True)
                if decision.status != "active":
                    continue
                posting = to_posting(candidate, decision, checked_at=checked_at)
                posting["source_urls"] = list(dict.fromkeys(filter(None, [
                    str(candidate.source_url), pages[0]["final_url"], source_url,
                ])))
                from app.services.job_contract_classification import classify_extracted_postings
                classified_postings, _ = await classify_extracted_postings([posting])
                posting = classified_postings[0]
                stored = await ingest(candidate, posting)
                contacts = await ingest_application_contacts(stored["firm_id"], decision.application_contacts)
                stored["contacts"] = contacts
                return {
                    "candidate": candidate.model_dump(mode="json"),
                    "decision": decision.model_dump(mode="json"),
                    "stored": stored,
                    "replayed_from_run": previous_run_id,
                }
            except (KeyError, TypeError, ValueError, RuntimeError):
                continue
    return None


async def previous_url_import_runs(source_url: str, *, limit: int = 10) -> list[tuple[str, dict]]:
    async with AsyncSessionLocal() as session:
        rows = (await session.scalars(
            select(CareerSearchRunRow).where(
                CareerSearchRunRow.status != "running",
                CareerSearchRunRow.result["url_import"].astext == "true",
                CareerSearchRunRow.result["source_url"].astext == source_url,
            ).order_by(CareerSearchRunRow.started_at.desc()).limit(limit)
        )).all()
    return [(row.id, row.result or {}) for row in rows]


async def tracked_candidates(limit: int, source_urls: list[str] | None = None) -> list[dict]:
    if not limit:
        return []
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(text("""
            SELECT f.id, f.firm_name, COALESCE(f.canonical_website,f.website) AS domain, p.value
            FROM pif_directory_firms f CROSS JOIN LATERAL
            jsonb_array_elements(COALESCE(f.research_data->'job_postings'->'postings','[]'::jsonb)) p(value)
            WHERE p.value->>'discovery_provider' = :provider
              AND COALESCE(f.source_json->>'merged_into','') = ''
              AND COALESCE(p.value->>'status','active') != 'closed'
              AND (:all_sources OR p.value->>'source_url' = ANY(CAST(:sources AS text[])))
            ORDER BY p.value->>'last_checked_at' ASC NULLS FIRST LIMIT :limit
        """), {"provider": PROVIDER, "limit": limit, "all_sources": source_urls is None,
               "sources": source_urls or []})).all()
    return [{"candidate": Candidate(firm_name=r.firm_name, canonical_domain=r.domain,
                source_url=r.value["source_url"], employer_evidence_url=r.value["employer_evidence_url"], title=r.value["title"]),
             "tracked": r.value, "firm_id": r.id} for r in rows]


async def known_source_identities() -> set[str]:
    """Exact jobs already discovered by this workflow, including closed jobs."""
    async with AsyncSessionLocal() as session:
        urls = (await session.scalars(text("""
            SELECT DISTINCT p.value->>'source_url'
            FROM pif_directory_firms f CROSS JOIN LATERAL
            jsonb_array_elements(COALESCE(f.research_data->'job_postings'->'postings','[]'::jsonb)) p(value)
            WHERE p.value->>'discovery_provider' = :provider
              AND COALESCE(p.value->>'source_url','') != ''
        """), {"provider": PROVIDER})).all()
    return {source_identity(url) for url in urls}


async def mark_checked(item: dict, *, closed: bool, reason: str):
    async with AsyncSessionLocal() as session:
        firm = await session.get(PifFirmRow, item["firm_id"], with_for_update=True)
        data = dict(firm.research_data or {})
        jobs = dict(data.get("job_postings") or {})
        postings = [dict(p) for p in jobs.get("postings", [])]
        for posting in postings:
            if posting.get("id") == item["tracked"].get("id"):
                posting.update({"last_checked_at": now_utc().isoformat(), "last_check_result": reason})
                if closed:
                    posting.update({"status": "closed", "closed_at": now_utc().isoformat()})
        jobs["postings"] = postings
        jobs["has_recent_openings"] = any(p.get("status") != "closed" for p in postings)
        data["job_postings"] = jobs
        firm.research_data = data
        await session.commit()


async def recover_candidates(discovered: list, config: SearchConfig, audit: dict, run_id: str,
                             *, deadline: float | None = None) -> list[Candidate]:
    accepted, failed = [], []
    for index, raw in enumerate(discovered):
        try:
            accepted.append(Candidate.model_validate(raw))
        except ValueError as exc:
            rejection = {"candidate_id": str(index), "original_candidate": audit_value(raw),
                         "validation_error": str(exc)[:4000], "phase": "initial"}
            audit.setdefault("candidate_rejections", []).append(rejection)
            failed.append((raw, rejection))
    await checkpoint(run_id, audit)
    if not failed:
        return accepted
    cache, repair_items = {}, []
    for raw, rejection in failed:
        try:
            fields = CandidateFields.model_validate(raw)
            from app.services.front_sync import normalize_domain
            urls = list(dict.fromkeys([str(fields.source_url), str(fields.employer_evidence_url),
                                      "https://" + normalize_domain(fields.canonical_domain) + "/"]))
            pages = []
            for url in urls:
                try:
                    if url not in cache:
                        cache[url] = await fetch_page(url)
                    pages.append(cache[url])
                except Exception as exc:
                    rejection.setdefault("fetch_errors", []).append({"source_url": url, "error": str(exc)[:1000]})
            rejection["pages"] = page_audit(pages)
            if not any(p["http_status"] == 200 for p in pages):
                raise ValueError("no live pages for candidate repair")
            repair_items.append({**rejection, "pages": pages})
        except ValueError as exc:
            audit["errors"].append({**rejection, "phase": "candidate_validation", "error": str(exc)[:1000]})
    await checkpoint(run_id, audit)
    if not repair_items:
        return accepted
    audit["candidate_repair_calls"] = audit.get("candidate_repair_calls", 0) + 1
    try:
        response = await llm({"mode": "candidate_repair", "candidates": repair_items}, "candidates", config,
                             audit, run_id, **deadline_kwargs(deadline))
        audit.setdefault("candidate_repair_responses", []).append(audit_value(response))
        rows = response.get("candidates")
        if not isinstance(rows, list):
            raise ValueError("candidate repair must return candidates array")
    except Exception as exc:
        rows = []
        audit.setdefault("candidate_repair_failures", []).append(str(exc)[:4000])
    for item in repair_items:
        original = item["original_candidate"]
        try:
            matches = [r for r in rows if isinstance(r, dict) and r.get("candidate_id") == item["candidate_id"]]
            if len(matches) != 1:
                raise ValueError("expected exactly one candidate repair")
            repaired = Candidate.model_validate(matches[0])
            if (source_identity(str(repaired.source_url)) != source_identity(
                    str(CandidateFields.model_validate(original).source_url))
                    or repaired.firm_name != original["firm_name"]):
                raise ValueError("candidate repair changed job or employer identity")
            from app.services.front_sync import normalize_domain
            if not any(source_identity(p["requested_url"]) == source_identity(
                           str(repaired.employer_evidence_url)) and p["http_status"] == 200
                       and normalize_domain(p["final_url"]) == repaired.canonical_domain for p in item["pages"]):
                raise ValueError("corrected canonical identity lacks a matching fetched official page")
            accepted.append(repaired)
        except ValueError as exc:
            error = {"phase": "candidate_validation", "candidate_id": item["candidate_id"],
                     "original_candidate": original, "error": str(exc)[:4000]}
            audit["errors"].append(error)
            audit.setdefault("candidate_rejections", []).append({**error, "phase": "repair", "response": audit_value(rows)})
    await checkpoint(run_id, audit)
    return accepted


async def recover_direct_import_candidate(
    discovered: list,
    *,
    source_url: str,
    direct_page: dict,
    search_profile: SearchProfile | None,
    config: SearchConfig,
    audit: dict,
    run_id: str,
    deadline: float | None = None,
) -> list[Candidate]:
    """Resolve one supplied job, researching official identity only when needed."""
    original = discovered[0] if len(discovered) == 1 else None
    failure = None
    if original is not None:
        try:
            return [Candidate.model_validate(original)]
        except ValueError as exc:
            failure = str(exc)[:4000]
    elif not discovered:
        failure = "The supplied page did not expose an official employer identity."
    else:
        failure = f"The supplied page produced {len(discovered)} candidate identities instead of one."
    rejection = {
        "candidate_id": "0",
        "original_candidate": audit_value(original),
        "validation_error": failure,
        "phase": "url_import_identity",
    }
    audit.setdefault("candidate_rejections", []).append(rejection)
    await checkpoint(run_id, audit)

    identity = None
    if isinstance(original, dict):
        try:
            identity = UrlImportIdentity.model_validate({
                "firm_name": original.get("firm_name"),
                "title": original.get("title"),
                "source_url": original.get("source_url") or source_url,
            })
        except ValueError:
            identity = None
    if identity is None:
        identity_result = await llm({
            "mode": "url_import_identity",
            "source_url": source_url,
            "final_url": direct_page["final_url"],
            "job_page": direct_page,
        }, "identities", config, audit, run_id,
           lane=os.getenv("OPENCLAW_RPC_INTERACTIVE_LANE", "possibleos-interactive"),
           **deadline_kwargs(deadline))
        identities = identity_result.get("identities")
        if not isinstance(identities, list) or len(identities) != 1:
            raise ValueError("The supplied page did not produce one job and employer identity")
        identity = UrlImportIdentity.model_validate(identities[0])

    search_result = None
    search_error = None
    try:
        search_result = await invoke_openclaw_tool(
            "web_search",
            {
                "objective": (
                    f"Find the official company website and an official about or company page for "
                    f"{identity.firm_name}. The selected job is {identity.title}."
                ),
                "search_queries": [
                    f"{identity.firm_name} official website",
                    f"{identity.firm_name} company about",
                ],
                "count": 6,
                "client_model": "gpt-5.6-luna",
            },
            timeout_s=90,
        )
        audit.setdefault("url_import_search", []).append({
            "transport": "native_tool_rpc",
            "result": audit_value(search_result),
        })
    except Exception as exc:
        # A generic OpenClaw web-search provider is optional. The gateway's
        # existing model can still expose provider-native search inside one
        # bounded agent turn, so preserve the failed lightweight attempt and
        # fall back without weakening any evidence checks.
        search_error = str(exc)[:2000] or type(exc).__name__
        audit.setdefault("url_import_search", []).append({
            "transport": "native_tool_rpc",
            "error": search_error,
            "fallback": "provider_native_agent_search",
        })
    await checkpoint(run_id, audit)

    enrichment_payload = {
        "mode": "url_import_enrichment",
        "source_url": source_url,
        "final_url": direct_page["final_url"],
        "job_page": direct_page,
        "original_candidate": original,
        "job_identity": identity.model_dump(mode="json"),
        "web_search_results": search_result,
        "research_transport": (
            "native_tool_rpc" if search_result is not None else "provider_native_agent_search"
        ),
        "native_tool_error": search_error,
        "validation_error": rejection["validation_error"],
        "search_profile": search_profile.model_dump(mode="json") if search_profile else None,
    }
    result = await llm(enrichment_payload, "candidates", config, audit, run_id,
       lane=os.getenv("OPENCLAW_RPC_INTERACTIVE_LANE", "possibleos-interactive"),
       allow_tools=search_result is None,
       **deadline_kwargs(deadline))
    audit.setdefault("url_import_enrichment", []).append(audit_value(result))
    candidates = result.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise ValueError("Official employer identity research did not return exactly one candidate")
    return await recover_candidates(candidates, config, audit, run_id, deadline=deadline)


def retry_inputs(previous: dict) -> dict:
    errors = previous.get("errors") or []
    failed_sources = {e.get("source_url") for e in errors if e.get("source_url")}
    raws = [e["original_candidate"] for e in errors if isinstance(e.get("original_candidate"), dict)]
    for entry in previous.get("verification_rejections", []):
        candidate = entry.get("candidate")
        if isinstance(candidate, dict) and candidate.get("source_url") in failed_sources:
            raws.append(candidate)
    unique = {json.dumps(raw, sort_keys=True): raw for raw in raws}
    legacy = [e for e in errors if e.get("phase") == "candidate_validation" and not e.get("original_candidate")]
    sources = list(dict.fromkeys(raw["employer_evidence_url"] for raw in unique.values() if raw.get("employer_evidence_url")))
    return {"candidates": list(unique.values()), "legacy_errors": legacy, "career_sources": sources}


async def execute(run_id: str, config: SearchConfig, *, seed_only: bool, audit: dict, retry_result: dict | None = None,
                  retry_candidates: list | None = None, search_profile: SearchProfile | None = None,
                  deadline: float | None = None, direct_source_url: str | None = None):
    now = now_utc()
    day_number = now.date().toordinal()
    direct_page = None
    if direct_source_url:
        direct_page = await fetch_page(direct_source_url)
        if direct_page["http_status"] != 200:
            raise ValueError(f"The supplied job URL returned HTTP {direct_page['http_status']}")
        if shared_recruiting_source(direct_source_url) or shared_recruiting_source(direct_page["final_url"]):
            # A shared board can prove the role, but it can never be the
            # canonical employer identity. Go directly to the bounded research
            # fallback instead of paying for a raw pass that cannot satisfy the
            # identity invariant.
            discovered = []
        else:
            result = await llm({
                "mode": "url_import",
                "source_url": direct_source_url,
                "final_url": direct_page["final_url"],
                "job_page": direct_page,
                "search_profile": search_profile.model_dump(mode="json") if search_profile else None,
            }, "candidates", config, audit, run_id,
               lane=os.getenv("OPENCLAW_RPC_INTERACTIVE_LANE", "possibleos-interactive"),
               **deadline_kwargs(deadline))
            if not isinstance(result.get("candidates"), list):
                raise ValueError("URL import extraction did not return a candidates array")
            discovered = result["candidates"]
        candidates = []
    elif retry_result is not None:
        retry = retry_inputs(retry_result)
        discovered = retry["candidates"][:config.max_candidates]
        if retry_candidates is not None:
            discovered += retry_candidates[:max(0, config.max_candidates - len(discovered))]
            audit["operator_retry_candidates"] = audit_value(retry_candidates)
        elif retry["legacy_errors"]:
            if not retry["career_sources"]:
                raise ValueError("historical candidates missing; no affected employer sources for bounded rediscovery")
            result = await llm({"mode": "retry_discovery", "window_start": (now.date() - timedelta(days=30)).isoformat(),
                "window_end": now.date().isoformat(), "career_sources": retry["career_sources"][:config.max_sources],
                "previous_errors": retry["legacy_errors"], "max_candidates": config.max_candidates - len(discovered),
                "max_sources": config.max_sources}, "candidates", config, audit, run_id,
                **deadline_kwargs(deadline))
            recovered = result["candidates"][:max(0, config.max_candidates - len(discovered))]
            audit["legacy_rediscovery"] = {"errors": retry["legacy_errors"], "response": audit_value(result)}
            if not recovered:
                audit["errors"].append({"phase": "retry_discovery", "error": "historical candidate inputs unavailable; rediscovery found no candidates"})
            discovered += recovered
        candidates = await tracked_candidates(config.max_candidates, source_urls=[r["source_url"] for r in discovered if isinstance(r, dict) and r.get("source_url")])
    elif seed_only:
        candidates = await tracked_candidates(config.max_rechecks)
        discovered = json.loads(SEEDS.read_text())["candidates"][:config.max_candidates]
    else:
        # All ordinary daily and operator searches receive the same Job Agent profile.
        # The null-profile branch remains only for legacy maintenance callers.
        candidates = [] if search_profile else await tracked_candidates(config.max_rechecks)
        sources = list(search_profile.source_urls) if search_profile else list(config.source_urls)
        offset = day_number % max(1, len(sources))
        sources = (sources[offset:] + sources[:offset])[:config.max_sources] if sources else []
        if search_profile:
            audit["search_source_ids"] = list(search_profile.source_ids)
            audit["search_sources_consulted"] = [str(source) for source in sources]
        queries = profile_queries(search_profile, day_number) if search_profile else [
            PI_QUERIES[(day_number + i) % len(PI_QUERIES)] for i in range(3)
        ]
        result = await llm({"mode": "discovery", "window_start": (now.date() - timedelta(days=30)).isoformat(),
            "window_end": now.date().isoformat(), "search_profile": search_profile.model_dump(mode="json") if search_profile else None,
            "queries": queries,
            "career_sources": [str(s) for s in sources], "max_candidates": config.max_candidates,
            "max_sources": config.max_sources}, "candidates", config, audit, run_id,
            **deadline_kwargs(deadline))
        if not isinstance(result["candidates"], list):
            raise ValueError("discovery candidates must be an array")
        discovered = result["candidates"][:config.max_candidates]
    audit["discovery_candidates"] = audit_value(discovered)
    if direct_source_url:
        recovered = await recover_direct_import_candidate(
            discovered,
            source_url=direct_source_url,
            direct_page=direct_page,
            search_profile=search_profile,
            config=config,
            audit=audit,
            run_id=run_id,
            deadline=deadline,
        )
    else:
        recovered = await recover_candidates(discovered, config, audit, run_id, deadline=deadline)
    if direct_source_url:
        if len(recovered) != 1:
            raise ValueError("The supplied URL did not produce one valid employer and job identity")
        candidate = recovered[0]
        allowed_sources = {
            source_identity(direct_source_url), source_identity(str(direct_page["final_url"])),
        }
        if source_identity(str(candidate.source_url)) not in allowed_sources:
            raise ValueError("The importer returned a different job URL than the one supplied")
        candidates.append({"candidate": candidate, "prefetched_job_page": direct_page,
                           "input_source_url": direct_source_url})
    else:
        seen = await known_source_identities() if search_profile else {
            source_identity(str(i["candidate"].source_url)) for i in candidates
        }
        for candidate in recovered:
            key = source_identity(str(candidate.source_url))
            if key not in seen:
                candidates.append({"candidate": candidate})
                seen.add(key)
            else:
                audit["duplicates_skipped"] = audit.get("duplicates_skipped", 0) + 1
    audit["candidates"] = len(candidates)
    await checkpoint(run_id, audit)
    cache = {}
    for start in range(0, len(candidates), 3):
        if deadline is not None and deadline - asyncio.get_running_loop().time() < MIN_LLM_CALL_SECONDS:
            audit["errors"].append({"phase": "run_budget",
                "error": "Stopped before the next verification batch because the run time budget was exhausted."})
            await checkpoint(run_id, audit)
            break
        batch = []
        for index, item in enumerate(candidates[start:start + 3], start=start):
            candidate = item["candidate"]
            try:
                job_page = item.get("prefetched_job_page") or await fetch_page(str(candidate.source_url))
                if job_page["http_status"] in {404, 410}:
                    if item.get("tracked") and source_identity(job_page["final_url"]) == source_identity(
                            str(candidate.source_url)):
                        await mark_checked(item, closed=True, reason=f"HTTP {job_page['http_status']}")
                        audit["closed"] += 1
                    else:
                        audit["rejected"] += 1
                    continue
                if direct_source_url:
                    candidate, employer_page = await fetch_direct_import_employer_page(
                        candidate, cache, audit,
                    )
                    item["candidate"] = candidate
                else:
                    employer_url = str(candidate.employer_evidence_url)
                    if employer_url not in cache:
                        cache[employer_url] = await fetch_page(employer_url)
                    employer_page = cache[employer_url]
                if employer_page["http_status"] != 200:
                    raise ValueError("employer identity page unavailable")
                contact_pages = []
                for contact_url in candidate.contact_urls:
                    url = str(contact_url)
                    try:
                        if url not in cache:
                            cache[url] = await fetch_page(url)
                        if cache[url]["http_status"] == 200:
                            contact_pages.append(cache[url])
                        else:
                            audit.setdefault("contact_errors", []).append({
                                "source_url": url, "error": f"HTTP {cache[url]['http_status']}",
                            })
                    except Exception as exc:
                        audit.setdefault("contact_errors", []).append({
                            "source_url": url, "error": str(exc)[:1000],
                        })
                batch.append({**item, "candidate_id": str(index),
                              "pages": [job_page, employer_page, *contact_pages]})
            except Exception as exc:
                audit["errors"].append({"source_url": str(candidate.source_url), "error": str(exc)[:1000]})
                if item.get("tracked"):
                    await mark_checked(item, closed=False, reason=str(exc)[:1000])
        if not batch:
            await checkpoint(run_id, audit)
            continue
        verified_batch = []
        async for item, decision in verified_decisions(batch, config, audit, run_id, today=now.date(),
                                                       search_profile=search_profile, deadline=deadline,
                                                       direct_import=bool(direct_source_url)):
            candidate = item["candidate"]
            audit["decisions"].append({"candidate": candidate.model_dump(mode="json"), "decision": decision.model_dump(mode="json")})
            verified_batch.append((item, decision))
            await checkpoint(run_id, audit)

        prepared: dict[int, dict] = {}
        for index, (item, decision) in enumerate(verified_batch):
            candidate = item["candidate"]
            if decision.status != "active":
                continue
            if (decision.posted_date and decision.posted_date < now.date() - timedelta(days=30)
                    and not item.get("tracked") and not direct_source_url):
                continue
            try:
                posting = to_posting(candidate, decision, checked_at=now_utc())
                posting["source_urls"] = list(dict.fromkeys(filter(None, [
                    str(candidate.source_url), item["pages"][0]["final_url"], item.get("input_source_url"),
                ])))
                prepared[index] = posting
            except Exception as exc:
                audit["errors"].append({"source_url": str(candidate.source_url), "error": str(exc)[:1000]})

        if prepared:
            from app.services.job_contract_classification import classify_extracted_postings
            positions = list(prepared)
            classified_postings, contract_error = await classify_extracted_postings(
                [prepared[position] for position in positions]
            )
            prepared.update(dict(zip(positions, classified_postings)))
            if contract_error:
                audit.setdefault("contract_classification_errors", []).append({
                    "candidate_ids": [verified_batch[position][0]["candidate_id"] for position in positions],
                    "error": contract_error,
                })

        for index, (item, decision) in enumerate(verified_batch):
            candidate = item["candidate"]
            try:
                if decision.status == "active":
                    if (decision.posted_date and decision.posted_date < now.date() - timedelta(days=30)
                            and not item.get("tracked") and not direct_source_url):
                        audit["rejected"] += 1
                        continue
                    posting = prepared.get(index)
                    if posting is None:
                        continue
                    stored = await ingest(candidate, posting)
                    contact_counts = await ingest_application_contacts(stored["firm_id"], decision.application_contacts)
                    stored["contacts"] = contact_counts
                    audit["new_jobs"] += stored["added"]
                    audit["verified"] += 1
                    audit["contacts_found"] = audit.get("contacts_found", 0) + contact_counts["verified"]
                    audit["contacts_inserted"] = audit.get("contacts_inserted", 0) + contact_counts["inserted"]
                    audit["stored"].append(stored)
                    # Revisit newly learned employer sources on subsequent rotating runs.
                    async with AsyncSessionLocal() as session:
                        state = await session.get(CareerSearchStateRow, "daily_pi_tech", with_for_update=True)
                        saved = dict(state.config)
                        sources = list(saved.get("source_urls") or [])
                        source = str(candidate.employer_evidence_url)
                        if source not in sources and len(sources) < 100:
                            saved["source_urls"] = sources + [source]
                            state.config = saved
                            state.updated_at = now_utc()
                            await session.commit()
                elif (decision.status == "closed" and item.get("tracked") and decision.status_evidence
                      and source_identity(str(decision.status_evidence.source_url))
                      == source_identity(str(candidate.source_url))):
                    await mark_checked(item, closed=True, reason=decision.reason)
                    audit["closed"] += 1
                else:
                    audit["rejected"] += 1
                    if decision.status == "unverified":
                        audit.setdefault("candidate_rejections", []).append({
                            "source_url": str(candidate.source_url), "reason": decision.reason,
                        })
                    if item.get("tracked"):
                        await mark_checked(item, closed=False, reason=decision.reason)
            except Exception as exc:
                audit["errors"].append({"source_url": str(candidate.source_url), "error": str(exc)[:1000]})
            await checkpoint(run_id, audit)


def direct_import_lock_id(source_url: str) -> int:
    """Use a stable per-URL PostgreSQL lock without blocking scheduled searches."""
    digest = hashlib.sha256(source_identity(source_url).encode()).digest()[:8]
    return int.from_bytes(digest, byteorder="big", signed=True)


async def import_url(source_url: str, *, search_profile: SearchProfile | dict | None = None) -> dict:
    """Verify and store one operator-supplied job URL without applying to it."""
    await public_url(source_url)
    await ensure_tables()
    profile = (SearchProfile.model_validate(search_profile) if search_profile is not None
               else await configured_job_agent_profile())
    config = await configuration()
    run_id = uuid.uuid4().hex
    now = now_utc()
    day = now.astimezone(ZoneInfo(config.timezone)).date().isoformat()
    audit = {
        "new_jobs": 0, "verified": 0, "closed": 0, "rejected": 0, "candidates": 0,
        "duplicates_skipped": 0, "contacts_found": 0, "contacts_inserted": 0,
        "llm_calls": 0, "errors": [], "candidate_rejections": [], "attempt_errors": [],
        "stored": [], "decisions": [], "usage": [], "prompt_cache_metrics": [],
        "seed_only": False, "job_agent_search": True, "search_trigger": "url_import",
        "manual_search": True, "url_import": True, "source_url": source_url,
        "search_profile": profile.model_dump(mode="json"),
    }
    lock_id = direct_import_lock_id(source_url)
    async with async_engine.connect() as connection:
        locked = await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_id})
        await connection.commit()
        if not locked:
            return {"status": "busy", "source_url": source_url,
                    "message": "This job URL is already being imported."}
        try:
            async with AsyncSessionLocal() as session:
                session.add(CareerSearchRunRow(
                    id=run_id, scheduled_day=day, status="running", started_at=now, result=audit,
                ))
                await session.commit()
            try:
                replayed = await replay_url_import_evidence(
                    source_url, await previous_url_import_runs(source_url), checked_at=now_utc(),
                )
                if replayed:
                    stored = replayed["stored"]
                    contacts = stored.get("contacts") or {}
                    audit.update({
                        "candidates": 1,
                        "verified": 1,
                        "new_jobs": int(bool(stored.get("added"))),
                        "contacts_found": contacts.get("verified", 0),
                        "contacts_inserted": contacts.get("inserted", 0),
                        "stored": [stored],
                        "decisions": [{
                            "candidate": replayed["candidate"],
                            "decision": replayed["decision"],
                        }],
                        "replayed_from_run": replayed["replayed_from_run"],
                    })
                    await checkpoint(run_id, audit, "completed")
                    return {"id": run_id, "status": "completed", "result": audit}
                loop = asyncio.get_running_loop()
                deadline = loop.time() + RUN_TIMEOUT_SECONDS - RUN_CLEANUP_RESERVE_SECONDS
                await asyncio.wait_for(execute(
                    run_id, config, seed_only=False, audit=audit, search_profile=profile,
                    deadline=deadline, direct_source_url=source_url,
                ), timeout=RUN_TIMEOUT_SECONDS)
                final = "partial" if audit["errors"] else "completed"
            except CareerSearchBudgetExceeded as exc:
                audit["errors"].append({
                    "phase": "url_import", "error": str(exc)[:1000],
                })
                final = "partial" if audit["stored"] or audit["decisions"] else "failed"
            except TimeoutError:
                audit["errors"].append({
                    "phase": "url_import",
                    "error": "URL import exceeded the 30-minute safety limit; completed results were preserved.",
                })
                final = "partial" if audit["stored"] or audit["decisions"] else "failed"
            except Exception as exc:
                audit["errors"].append({
                    "phase": "url_import", "error": str(exc)[:1000] or type(exc).__name__,
                })
                final = "failed"
            await checkpoint(run_id, audit, final)
            return {"id": run_id, "status": final, "result": audit}
        finally:
            await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_id})
            await connection.commit()


async def run(*, due_only: bool = False, seed_only: bool = False, retry_run: str | None = None,
              retry_candidates: list | None = None, search_profile: SearchProfile | dict | None = None) -> dict:
    explicit_search_profile = search_profile is not None
    if search_profile is not None:
        search_profile = SearchProfile.model_validate(search_profile)
    if search_profile is not None and (due_only or seed_only or retry_run or retry_candidates is not None):
        raise ValueError("a Job Agent search profile cannot be combined with due, seed or retry modes")
    if retry_run and (due_only or seed_only):
        raise ValueError("--retry-run cannot be combined with --due or --seed-only")
    if retry_candidates is not None and (not retry_run or not isinstance(retry_candidates, list)):
        raise ValueError("candidate input must be an array and requires --retry-run")
    retry_result = None
    if retry_run:
        async with AsyncSessionLocal() as session:
            previous = await session.get(CareerSearchRunRow, retry_run)
            if previous is None or previous.status == "running":
                raise ValueError("retry requires an existing finished run")
            retry_result = json.loads(json.dumps(previous.result))
    config = await configuration()
    async with async_engine.connect() as connection:
        locked = await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_ID})
        await connection.commit()
        if not locked:
            return {"status": "busy"}
        try:
            current = await status()
            now = now_utc()
            day = now.astimezone(ZoneInfo(config.timezone)).date().isoformat()
            today_runs = [r for r in current["runs"] if r["scheduled_day"] == day
                          and not (r.get("result") or {}).get("retry_of")
                          and not (r.get("result") or {}).get("manual_search")
                          and (r.get("result") or {}).get("search_trigger") in {None, "scheduled"}]
            if due_only:
                finished_days = {r["scheduled_day"] for r in today_runs
                                 if r["status"] in {"completed", "partial"}}
                if not config.enabled or next_due(config, finished_days, now=now) > now:
                    return {"status": "not_due"}
                if len(today_runs) >= config.max_attempts:
                    return {"status": "retry_limit", "error": "daily attempt limit reached; inspect status"}
                if today_runs and datetime.fromisoformat(today_runs[0]["started_at"]) > now - timedelta(minutes=30):
                    return {"status": "backoff"}
            if search_profile is None and not seed_only and not retry_run:
                search_profile = await configured_job_agent_profile()
            audit = {"new_jobs": 0, "verified": 0, "closed": 0, "rejected": 0, "candidates": 0,
                     "duplicates_skipped": 0,
                     "contacts_found": 0, "contacts_inserted": 0,
                     "llm_calls": 0, "errors": [], "candidate_rejections": [], "attempt_errors": [],
                     "stored": [], "decisions": [], "usage": [], "prompt_cache_metrics": [], "seed_only": seed_only}
            if search_profile:
                trigger = "manual" if explicit_search_profile else "scheduled" if due_only else "operator"
                audit.update({"job_agent_search": True, "search_trigger": trigger,
                              "search_profile": search_profile.model_dump(mode="json")})
                if explicit_search_profile:
                    audit["manual_search"] = True
            if retry_run:
                audit["retry_of"] = retry_run
            run_id = uuid.uuid4().hex
            async with AsyncSessionLocal() as session:
                # Holding the advisory lock proves earlier running processes are gone.
                stale = (await session.scalars(select(CareerSearchRunRow).where(CareerSearchRunRow.status == "running"))).all()
                for row in stale:
                    row.status = "interrupted"
                    row.completed_at = now
                session.add(CareerSearchRunRow(id=run_id, scheduled_day=day, status="running", started_at=now, result=audit))
                await session.commit()
            try:
                loop = asyncio.get_running_loop()
                deadline = loop.time() + RUN_TIMEOUT_SECONDS - RUN_CLEANUP_RESERVE_SECONDS
                await asyncio.wait_for(execute(run_id, config, seed_only=seed_only, audit=audit,
                    retry_result=retry_result, retry_candidates=retry_candidates,
                    search_profile=search_profile, deadline=deadline), timeout=RUN_TIMEOUT_SECONDS)
                final = "partial" if audit["errors"] else "completed"
            except CareerSearchBudgetExceeded as exc:
                audit["errors"].append({
                    "phase": "run_budget", "error": str(exc)[:1000],
                })
                final = "partial" if audit["stored"] or audit["decisions"] else "failed"
            except TimeoutError:
                audit["errors"].append({"phase": "run",
                    "error": "Run exceeded the 30-minute safety limit; completed results were preserved."})
                final = "partial" if audit["stored"] or audit["decisions"] else "failed"
            except Exception as exc:
                audit["errors"].append({"phase": "run", "error": str(exc)[:1000] or type(exc).__name__})
                final = "failed"
            await checkpoint(run_id, audit, final)
            return {"id": run_id, "status": final, "result": audit}
        finally:
            await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_ID})
            await connection.commit()
