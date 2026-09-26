# Daily PI Technology Career Search

## Live installation (2026-09-10)

The server timer and durable configuration are enabled for **08:00
America/Bogota (Medellin), 13:00 UTC**, every day. The next scheduled search
after today's initial import is September 11 at 13:00 UTC. See Possible OS
**Job Postings** for imported roles and the latest run status.

Migration `c9d0e1f2g3h4` is applied. Backend and frontend are running the new
workflow. The first completed seed verification saved all five priority jobs
(three TopDog roles, California Injury Group, and Jacoby & Meyers); rechecking
the three previously stored TopDog jobs added zero duplicates. Existing Jacoby
jobs were preserved. Prompt instructions are traced through version v1.68.

The normal discovery run `f7e791d924cc453492daad07b8963e91` then completed:
seven candidates checked, five saved roles reverified, two candidates rejected,
zero duplicates added, and zero final errors. The California Injury Group row
retains its August 28 publication date and conditional LATAM eligibility;
Jacoby's Applied AI row retains August 27 and unknown Colombia eligibility.
The systemd timer's automatic tick was observed at 11:55 UTC with the timer
active and enabled; the jobs page returned HTTP 200.

The initial live verification reported a 16.7% cached-input fraction on one
call. This is an observed sample, not a guaranteed cache rate.

## Scope and architecture

This is a separate, opt-in server-side workflow. It does not change the existing
7/30-day firm research cadence, daily firm cap, outreach, calls, or Mission
Control India jobs schedule. Nothing sends email or submits applications.

- Default schedule: **08:00 America/Bogota, 13:00 UTC**, disabled until enabled.
- The staged systemd timer checks every five minutes. The CLI checks the durable
  timezone/time configuration, so changing time does not require editing units.
- One discovery call searches three rotating query variants and up to six known
  sources. It can discover employers absent from the firm directory.
- Defaults: at most 10 discovered candidates and 8 oldest-checked tracked jobs.
  Employer sources learned from verified roles join the bounded rotating list.
- Fetch specific jobs and employer identity pages over public HTTPS, with a
  2MB limit, redirect checks, request timeouts, retry/backoff, and per-run cache.
- Verify up to three related candidates per structured OpenClaw/main call.
  Require exact excerpts from fetched pages for PI identity, genuine technical
  duties and active application status. HTTP200 or a search snippet is not
  active-job proof. Inaccessible/JS-only sources may remain unverified.
- Keep US-only remote, conditional LATAM, global and unclear eligibility
  separate. Geographic matching never promises work authorization.
- Original employer posting dates are not ATS-created/updated timestamps.
  Date-unknown live jobs are labeled and excluded by explicit posted-date filters.
  New jobs with known original dates older than 30 days are rejected; existing
  tracked jobs continue to be rechecked beyond that discovery window.

### Job Agent manual search

The Job Agent exposes **Search now** and `bin/possibleos job-agent search`.
This mode uses the Job Agent's saved target roles, preferred industries, location
preferences and overseas-employer preference. It searches law firms, legal-tech
product companies and legal-service providers for AI-agent, applied-AI, workflow
automation and related technical roles. It does not apply, email, classify a
resume category, or submit forms. Each verified extraction does make one batched
TypeSafe Jev contract-status judgment and stores that result for later filtering.

Manual searches are durable `career_search_runs` with `manual_search` and a
snapshot of `search_profile` in the audit. They do not recheck the scheduled PI
search's unrelated tracked jobs, consume a scheduled daily attempt, or satisfy
that day's scheduled slot. Successful and partial runs wake the existing durable
Job Agent collection worker so verified rows enter the review queue. A paused
collector leaves results safely stored for the next sync.

Deduplication is mechanical. Discovery collapses normalized URLs within a run;
manual runs skip normalized URLs already stored by this workflow; persistence
merges normalized source URLs or employer-scoped ATS provider plus requisition
ID; and Job Agent upserts its stable candidate ID. A repost with a distinct
requisition remains distinct. Different URLs without requisition evidence are
not merged on title alone because separate openings can share a title.

## Persistence and operations

`career_search_state` holds configuration. `career_search_runs` stores run
status, counters, errors, source-backed decisions, usage and persisted IDs.
The stable prompt-cache key is `possibleos:career-search:v4`; normalized
`prompt_cache_metrics` accompany raw provider usage. Unreported metrics are not
treated as cache hits.
Verified jobs remain in `pif_directory_firms.research_data.job_postings.postings`,
the existing UI store. No second user-facing job database is introduced.
The stored posting includes `contract_status` plus the Jev model, full
probabilities, confidence, input hash and timestamp. Application preparation
reads this value and does not reclassify it.

Canonical domain/alias resolution precedes minimal firm upsert. Jobs deduplicate
by normalized source URL (including Jobvite /apply variants), or employer-scoped
case-insensitive ATS provider plus requisition. Titles alone never identify jobs.
Rechecks preserve original publication/date evidence, first-seen and ATS creation;
last-checked and ATS update can advance. `found_at` prefers per-job first-seen.

Daily ingestion and ordinary job writers lock the firm row. Classification uses
the current collection when committing, so a daily row inserted after a
classifier started is preserved. Ordinary research and legacy EmailTag profile
refresh preserve daily-managed postings, including their closed status and
geographic evidence. Relevant local profile/sitemap JSON writers also lock on
read before saving. The normal full-research snapshot still replaces its own
non-daily jobs; this is not a redesign of historical jobs research.

Closed rows stay in firm JSON and run history; default Job Postings excludes
them. 404/410 on the same verified URL, or sourced semantic closure, can close a
tracked job. Timeouts, 403/429/5xx, generic redirects and incomplete evidence do
not turn a tracked job into a closed one. UI shows daily runner status/counts,
verification errors, publication unknown, ATS creation, checked time and
Colombia eligibility without changing the overall jobs layout.

A PostgreSQL advisory lock prevents overlapping processes. Each committed
ingest is independently idempotent. A killed process retains audit checkpoints;
the next lock holder marks its run interrupted. Default retries: 3 gateway
attempts with exponential delay/jitter; up to 3 daily run attempts, separated by
at least 30 minutes. Runs have a 30-minute wall timeout. A partial run records
successful IDs and failures rather than claiming complete success. Zero-new
successful runs are quiet with `--quiet`; matches/failures are visible in
status/UI/journal, without unsolicited external messages.

### Bounded verifier repair

Invalid verifier decisions are checkpointed under `verification_rejections`
before any repair: original structured output (including the bad quote and
source URL), precise validation error, candidate identity, and fetched-page
URLs/status/SHA256 plus 500-character excerpts. Malformed whole responses are
also retained; unusually large raw values are bounded to a 60,000-character
preview plus hash. Successful stored IDs are never removed from the audit.

Valid candidates are ingested first. Only failed candidates are grouped into
**one additional structured repair call per verification batch**, using their
original decisions, exact errors and the same freshly fetched pages. This
covers field/excerpt validation and missing/duplicate IDs or malformed response
schemas. Exact-source excerpt checks and all existing eligibility checks are
unchanged. No paraphrase/fuzzy acceptance or manual approval is permitted.

Gateway-internal schema repair is disabled for verification; the explicit
repair has one transport attempt and no recursive repair. Its invocation is
counted in `llm_calls` and `repair_calls`, and remains inside the existing
30-minute run wall timeout. Initial transport retries retain their bounded
backoff policy. Valid batches use no extra call. An unsuccessful repair leaves
the candidate unverified/error, retains both rejected decisions when available,
and preserves successful candidates' stored IDs. No new evidence is fetched
during repair. `verification_repair` adds prompt instructions requiring the
parent-controlled prompt trace/version deployment protocol.

### Candidate and citation recovery

Discovery saves `discovery_candidates` and rejected raw inputs before repair.
Invalid candidate identities get one batched `candidate_repair` call, with
bounded live job/employer/canonical-root fetches and exact validation errors.
The repaired identity must match a fetched official page's requested/final
domain, cannot change job URL or firm name, and cannot use a shared recruiting
platform (such as Jobvite) as its canonical employer domain. It still passes
the full live job verifier before ingestion. Unrecoverable candidates retain
their original input, repair response and errors; valid candidates continue.

`evidence_source_matches` records which supplied pages contain a rejected
quote exactly. This helps the LLM correct cross-page source misattribution,
without accepting a wrong citation automatically or allowing paraphrases.
PI evidence may be on the ATS role page; canonical identity remains separately
anchored to the employer's official website. No additional verifier-repair
calls or weaker evidence checks are introduced.

Retry only failed candidates without altering the historical run:

```bash
bin/possibleos pif career-search-run --retry-run RUN_ID
# For older runs that discarded invalid candidate inputs:
bin/possibleos pif career-search-run --retry-run RUN_ID --candidates-file candidates.json
```

The file contains a `candidates` array in the discovery schema. It supplies
discovery hints, never an approval: every row is freshly fetched and verified.
Without a file, legacy failures trigger bounded rediscovery restricted to
affected employer career sources available in the old audit. Missing source
context remains an explicit error. New runs retain `retry_of`, source inputs,
repair counters, validation errors and successful IDs. No unrelated tracked
jobs are rechecked. Recovery runs share the advisory lock and 30-minute wall
limit, but do not consume daily attempts or satisfy a normal daily discovery
slot. `--retry-run` cannot be combined with `--due` or `--seed-only`.

The recovery change does not modify the 08:00 America/Bogota schedule
(13:00 UTC, 18:30 Asia/Kolkata), install units, or run a migration. CLI processes
read current source directly; parent owns prompt-version/commit/push trace and
any safe backend restart for API status changes.

## Parent deployment and verification

The orchestrator completed installation and activation described above. For a
fresh installation or manual verification, use:

```bash
cd /home/pranav/possibleos
.venv/bin/alembic heads
.venv/bin/alembic upgrade c9d0e1f2g3h4
bin/possibleos pif career-search-config
bin/possibleos pif career-search-run --seed-only
bin/possibleos pif career-search-status
# Rerun to verify new_jobs=0 while verified/last_checked advance:
bin/possibleos pif career-search-run --seed-only
# Then a bounded real discovery pass:
bin/possibleos pif career-search-run
```

Check the five priority URLs against the existing `/api/pif/job-postings` view
and inspect returned firm/job IDs, original dates and Colombia restrictions.
Seeds are URLs/identity hints, not trusted active listings. Sources may have
closed or become inaccessible since the September 10 report.

After audit, the parent installs both unit files from `deploy/systemd/`, runs
`systemctl daemon-reload`, enables/starts `possibleos-career-search.timer`, and
uses `bin/possibleos pif career-search-config --enable`. Verify
`systemctl list-timers possibleos-career-search.timer` and the CLI next-due time.
The effective start is the first timer tick at/after 08:00 Bogota, normally
within five minutes. Enabling after that time allows a same-day catch-up run.

To change time/bounds, provide a JSON patch, for example:
`{"timezone":"America/Bogota","local_time":"08:00","max_candidates":10,"max_rechecks":8}`.
Use `career-search-config --disable` to pause due runs; explicit manual runs
remain available. No backend restart is needed for configuration changes.

The existing backend needs the parent-controlled restart to expose the new
read-only `/api/pif/career-search/status` API and load merge protections; restart
frontend after the build for status/metadata display. Observe active-call
safety rules. Complete the repository prompt-change protocol for the new
`app/skills/daily-pi-career-search/SKILL.md` (parent owns version/commit/push/restart;
implementer has not changed the attorney prompt version).

## Limits

Coverage is budgeted, not exhaustive: tracked rows rotate when more than eight
are present; known sources rotate when more than six are configured. No 4,510
firm daily crawl. LLM source interpretation can still be wrong despite exact
excerpt checks. Browser-only or access-blocked ATS pages require later retries
or a future provider adapter; unverified listings are not silently imported.
Current verification is HTTP + embedded structured data, not a browser capable
of proving every application form's interactive behavior. Configuration does
not prove timer installation; check the actual systemd timer when diagnosing
scheduling problems.
