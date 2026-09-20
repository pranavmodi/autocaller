"""Evidence-backed legal technology career search, operated by CLI or timer."""
from __future__ import annotations

import asyncio
import hashlib
import json
import random
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from app.db import AsyncSessionLocal, async_engine
from app.db.models import CareerSearchRunRow, CareerSearchStateRow, PifFirmRow
from app.services.career_job_store import PROVIDER, job_id, merge_career_postings, source_identity, same_job
from app.services.career_search_web import fetch_page
from app.services.llm_gateway import call_skill_json, prompt_cache_metrics, LLMGatewayResponseError
from app.services.pif_firm_crud import get_pif_firm_for_crud, upsert_pif_firm
from app.services.pif_job_posting_research import classify_job_posting

SKILL = Path(__file__).resolve().parents[1] / "skills/daily-pi-career-search/SKILL.md"
SEEDS = SKILL.with_name("seeds.json")
LOCK_ID = 734985210
SCHEMA_LOCK_ID = 734985216
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
    name: str = Field("Job Agent legal AI search", min_length=1, max_length=120)
    target_roles: str = Field(min_length=1, max_length=2000)
    preferred_industries: str = Field(min_length=1, max_length=2000)
    location_preferences: str = Field(min_length=1, max_length=2000)
    prefer_overseas_employers: bool = True


class CandidateFields(BaseModel):
    firm_name: str = Field(min_length=1, max_length=255)
    canonical_domain: str = Field(min_length=3, max_length=255)
    source_url: HttpUrl
    employer_evidence_url: HttpUrl
    title: str = Field(min_length=1, max_length=300)


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
        self.canonical_domain = domain
        return self


class Excerpt(BaseModel):
    source_url: HttpUrl
    text: str = Field(min_length=1, max_length=1200)


class Decision(BaseModel):
    candidate_id: str
    status: Literal["active", "closed", "unverified"]
    reason: str
    direct_pi_employer: bool = False
    legal_domain_employer: bool = False
    legal_domain_kind: Literal["law_firm", "legal_tech", "legal_services", "unclear"] = "unclear"
    technology_role: bool
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
    role_category: Literal["technology_data"] = "technology_data"
    trigger_tags: list[str] = Field(default_factory=list)
    technology_mentions: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)
    employer_evidence: Excerpt | None = None
    role_evidence: Excerpt | None = None
    status_evidence: Excerpt | None = None
    geography_evidence: Excerpt | None = None
    date_evidence: Excerpt | None = None


def now_utc():
    return datetime.now(timezone.utc)


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
    return {"id": row.id, "scheduled_day": row.scheduled_day, "status": row.status,
            "started_at": row.started_at.isoformat(),
            "completed_at": row.completed_at.isoformat() if row.completed_at else None, "result": row.result}


async def status() -> dict:
    config = await configuration()
    async with AsyncSessionLocal() as session:
        runs = list((await session.scalars(select(CareerSearchRunRow).order_by(CareerSearchRunRow.started_at.desc()).limit(10))).all())
    completed = {r.scheduled_day for r in runs if r.status == "completed"
                 and not (r.result or {}).get("retry_of") and not (r.result or {}).get("manual_search")}
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


async def llm(payload: dict, required: str, config: SearchConfig, audit: dict, run_id: str):
    verification = required == "decisions"
    attempts = 1 if payload["mode"] in {"verification_repair", "candidate_repair"} else config.max_attempts
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
            audit["llm_calls"] += 1
            await checkpoint(run_id, audit)
            response = await call_skill_json(skill_path=SKILL, payload=payload, required_fields=[required],
                model="openclaw/main", timeout_s=420, max_tokens=9000, retries=1,
                schema_repair_retries=0 if verification or payload["mode"] == "candidate_repair" else 1,
                attempt_observer=observe_attempt,
                prompt_cache_key="possibleos:legal-career-search:v2")
            audit["usage"].append(response.usage or {})
            audit.setdefault("prompt_cache_metrics", []).append(prompt_cache_metrics(response.usage))
            if verification:
                # Candidate-level validation owns the single explicit repair budget.
                return response.parsed
            if not isinstance(response.parsed[required], list):
                raise ValueError(f"{required} must be an array")
            return response.parsed
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


def inspect_verification(batch: list[dict], response, *, today: date, phase: str, audit: dict,
                         search_profile: SearchProfile | None = None):
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
            validate_decision(decision, item["pages"], today=today, search_profile=search_profile)
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
                             search_profile: SearchProfile | None = None):
    profile = search_profile.model_dump(mode="json") if search_profile else None
    payload = {"mode": "verification", "as_of": today.isoformat(), "search_profile": profile, "candidates": [
        {"candidate_id": item["candidate_id"], **item["candidate"].model_dump(mode="json"), "pages": item["pages"]} for item in batch
    ]}
    response = await llm(payload, "decisions", config, audit, run_id)
    accepted, failed = inspect_verification(batch, response, today=today, phase="initial", audit=audit,
                                            search_profile=search_profile)
    await checkpoint(run_id, audit)
    # Yield valid rows before a repair can time out, so their ingests are durable.
    for pair in accepted:
        yield pair
    if not failed:
        return
    audit["repair_calls"] = audit.get("repair_calls", 0) + 1
    repair_payload = {"mode": "verification_repair", "as_of": today.isoformat(), "search_profile": profile, "candidates": [
        {"candidate_id": item["candidate_id"], **item["candidate"].model_dump(mode="json"),
         "pages": item["pages"], "original_decision": rejection["original_decision"],
         "evidence_source_matches": rejection["evidence_source_matches"],
         "validation_error": rejection["validation_error"]} for item, rejection in failed
    ]}
    await checkpoint(run_id, audit)
    try:
        repaired = await llm(repair_payload, "decisions", config, audit, run_id)
        accepted, remaining = inspect_verification([item for item, _ in failed], repaired, today=today,
                                                   phase="repair", audit=audit, search_profile=search_profile)
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
                      search_profile: SearchProfile | None = None) -> None:
    content = {p["requested_url"]: " ".join(p["content"].split()).casefold() for p in pages}
    for field in ("employer_evidence", "role_evidence", "status_evidence", "geography_evidence", "date_evidence"):
        evidence = getattr(decision, field)
        if evidence and " ".join(evidence.text.split()).casefold() not in content.get(str(evidence.source_url), ""):
            raise ValueError(f"{field} excerpt not found in fetched source")
    if decision.status == "active":
        employer_matches = decision.legal_domain_employer if search_profile else decision.direct_pi_employer
        if not employer_matches or not decision.technology_role:
            raise ValueError("not a verified legal-domain technology role" if search_profile
                             else "not a direct PI technology role")
        if not all((decision.employer_evidence, decision.role_evidence, decision.status_evidence)):
            raise ValueError("active job lacks required live evidence")
        if decision.posted_date and (not decision.date_evidence or decision.posted_date > today):
            raise ValueError("publication date lacks evidence or is in the future")
        if (decision.remote_scope != "unclear" or decision.colombia_eligibility != "unknown") and not decision.geography_evidence:
            raise ValueError("geographic classification lacks evidence")
        if decision.remote_scope == "global" and decision.colombia_eligibility == "restricted":
            raise ValueError("contradictory global and restricted geography")


def to_posting(candidate: Candidate, decision: Decision, *, checked_at: datetime) -> dict:
    payload = decision.model_dump(mode="json", exclude={"candidate_id"})
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
        }.get(posting.get("legal_domain_kind"), "legal_employer")
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


async def recover_candidates(discovered: list, config: SearchConfig, audit: dict, run_id: str) -> list[Candidate]:
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
        response = await llm({"mode": "candidate_repair", "candidates": repair_items}, "candidates", config, audit, run_id)
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
            if (str(repaired.source_url) != str(CandidateFields.model_validate(original).source_url)
                    or repaired.firm_name != original["firm_name"]):
                raise ValueError("candidate repair changed job or employer identity")
            from app.services.front_sync import normalize_domain
            if not any(p["requested_url"] == str(repaired.employer_evidence_url) and p["http_status"] == 200
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
                  retry_candidates: list | None = None, search_profile: SearchProfile | None = None):
    now = now_utc()
    day_number = now.date().toordinal()
    if retry_result is not None:
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
                "max_sources": config.max_sources}, "candidates", config, audit, run_id)
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
        # Manual Job Agent searches look for new roles matching the current profile.
        # Scheduled PI runs continue to recheck their previously verified jobs.
        candidates = [] if search_profile else await tracked_candidates(config.max_rechecks)
        sources = [] if search_profile else list(config.source_urls)
        offset = day_number % max(1, len(sources))
        sources = (sources[offset:] + sources[:offset])[:config.max_sources] if sources else []
        queries = LEGAL_AI_QUERIES if search_profile else PI_QUERIES
        result = await llm({"mode": "discovery", "window_start": (now.date() - timedelta(days=30)).isoformat(),
            "window_end": now.date().isoformat(), "search_profile": search_profile.model_dump(mode="json") if search_profile else None,
            "queries": [queries[(day_number + i) % len(queries)] for i in range(3)],
            "career_sources": [str(s) for s in sources], "max_candidates": config.max_candidates,
            "max_sources": config.max_sources}, "candidates", config, audit, run_id)
        if not isinstance(result["candidates"], list):
            raise ValueError("discovery candidates must be an array")
        discovered = result["candidates"][:config.max_candidates]
    seen = await known_source_identities() if search_profile else {
        source_identity(str(i["candidate"].source_url)) for i in candidates
    }
    audit["discovery_candidates"] = audit_value(discovered)
    for candidate in await recover_candidates(discovered, config, audit, run_id):
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
        batch = []
        for index, item in enumerate(candidates[start:start + 3], start=start):
            candidate = item["candidate"]
            try:
                job_page = await fetch_page(str(candidate.source_url))
                if job_page["http_status"] in {404, 410}:
                    if item.get("tracked") and job_page["final_url"] == str(candidate.source_url):
                        await mark_checked(item, closed=True, reason=f"HTTP {job_page['http_status']}")
                        audit["closed"] += 1
                    else:
                        audit["rejected"] += 1
                    continue
                employer_url = str(candidate.employer_evidence_url)
                if employer_url not in cache:
                    cache[employer_url] = await fetch_page(employer_url)
                employer_page = cache[employer_url]
                if employer_page["http_status"] != 200:
                    raise ValueError("employer identity page unavailable")
                batch.append({**item, "candidate_id": str(index), "pages": [job_page, employer_page]})
            except Exception as exc:
                audit["errors"].append({"source_url": str(candidate.source_url), "error": str(exc)[:1000]})
                if item.get("tracked"):
                    await mark_checked(item, closed=False, reason=str(exc)[:1000])
        if not batch:
            await checkpoint(run_id, audit)
            continue
        async for item, decision in verified_decisions(batch, config, audit, run_id, today=now.date(),
                                                       search_profile=search_profile):
            candidate = item["candidate"]
            try:
                audit["decisions"].append({"candidate": candidate.model_dump(mode="json"), "decision": decision.model_dump(mode="json")})
                await checkpoint(run_id, audit)
                if decision.status == "active":
                    if decision.posted_date and decision.posted_date < now.date() - timedelta(days=30) and not item.get("tracked"):
                        audit["rejected"] += 1
                        continue
                    posting = to_posting(candidate, decision, checked_at=now_utc())
                    posting["source_urls"] = list(dict.fromkeys([str(candidate.source_url), item["pages"][0]["final_url"]]))
                    stored = await ingest(candidate, posting)
                    audit["new_jobs"] += stored["added"]
                    audit["verified"] += 1
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
                      and str(decision.status_evidence.source_url) == str(candidate.source_url)):
                    await mark_checked(item, closed=True, reason=decision.reason)
                    audit["closed"] += 1
                else:
                    audit["rejected"] += 1
                    if decision.status == "unverified":
                        audit["errors"].append({"source_url": str(candidate.source_url), "error": decision.reason})
                    if item.get("tracked"):
                        await mark_checked(item, closed=False, reason=decision.reason)
            except Exception as exc:
                audit["errors"].append({"source_url": str(candidate.source_url), "error": str(exc)[:1000]})
            await checkpoint(run_id, audit)


async def run(*, due_only: bool = False, seed_only: bool = False, retry_run: str | None = None,
              retry_candidates: list | None = None, search_profile: SearchProfile | dict | None = None) -> dict:
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
            today_runs = [r for r in current["runs"] if r["scheduled_day"] == day and not (r.get("result") or {}).get("retry_of")
                          and not (r.get("result") or {}).get("manual_search")]
            if due_only:
                if not config.enabled or next_due(config, {r["scheduled_day"] for r in today_runs if r["status"] == "completed"}, now=now) > now:
                    return {"status": "not_due"}
                if len(today_runs) >= config.max_attempts:
                    return {"status": "retry_limit", "error": "daily attempt limit reached; inspect status"}
                if today_runs and datetime.fromisoformat(today_runs[0]["started_at"]) > now - timedelta(minutes=30):
                    return {"status": "backoff"}
            audit = {"new_jobs": 0, "verified": 0, "closed": 0, "rejected": 0, "candidates": 0,
                     "duplicates_skipped": 0,
                     "llm_calls": 0, "errors": [], "attempt_errors": [], "stored": [], "decisions": [], "usage": [], "prompt_cache_metrics": [], "seed_only": seed_only}
            if search_profile:
                audit.update({"manual_search": True, "search_profile": search_profile.model_dump(mode="json")})
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
                await asyncio.wait_for(execute(run_id, config, seed_only=seed_only, audit=audit,
                    retry_result=retry_result, retry_candidates=retry_candidates,
                    search_profile=search_profile), timeout=1800)
                final = "partial" if audit["errors"] else "completed"
            except Exception as exc:
                audit["errors"].append({"phase": "run", "error": str(exc)[:1000] or type(exc).__name__})
                final = "failed"
            await checkpoint(run_id, audit, final)
            return {"id": run_id, "status": final, "result": audit}
        finally:
            await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_ID})
            await connection.commit()
