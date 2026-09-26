# Job agent workspace

The `/job-agent` tab provides a persistent operator review queue, a separate
Applications section, CV library, preferences, and collection progress. The Activity tab is hidden for now. Audit
history remains available through the CLI/API.
Jobs can be classified on demand into configurable resume categories. Applications
are processed only after an explicit operator action. Email delivery uses the
official Zoho CLI.

## Applications section

Every job whose application workflow has started appears in the separate
**Applications** section. This includes source/contact research in progress,
stopped preparations, ready but unsent drafts, authorized sends, uncertain Sent
verification, and Sent-verified messages. It is newest-update first by default,
with firm/role/recipient search, status filtering, firm or role ordering,
pagination, source links, prepared-PDF links, and the shared application detail
modal. Opening or filtering this section is read-only and never prepares or sends.

The list is backed by the durable `job_agent_processing` record associated with
each canonical job, so the Review queue, Leads modal, CLI, and Applications section
show the same current workflow state. `ready` means prepared but not sent;
`sent_verified` means the exact message and attachment were found in Zoho Sent, not
recipient delivery or an ATS submission.

## Collection and ordering

- All matching **existing local** Possible OS listings are collected, with no total
  import ceiling. Text, remote-arrangement and posting-age filters remain explicit
  user choices; defaults include every listing. This does not run web research.
- A backend worker checks for changes every minute. `Sync now` / `job-agent collect`
  queues or resumes a durable run immediately. The response acknowledges the run;
  `job-agent status` reports completion, counts, remaining records and failures.
- Each run snapshots matching source records in one database statement. Research
  changes during the run enter the next snapshot. Transactions process 100 records
  at a time; this is an internal batch size, never a total limit. Candidate updates
  and the checkpoint commit together. Restarts continue from committed progress.
- Pause stops processing between transactions and retains the checkpoint. Changes
  to filters apply to the next snapshot; an active run retains its saved settings.
  Transient failures retry after a minute; invalid listings are counted and recorded
  with source details in the audit log. Finished snapshots are deleted, while run summaries
  and audit history persist. Unchanged successful syncs do not flood the activity log.
- Source closures propagate to existing jobs and show a closed badge. Collection does
  not delete jobs or overwrite operator notes/decisions. Missing-from-source jobs are
  retained; source disappearance alone is not evidence a role closed.
- The review queue defaults to **Most recently posted**, with unknown/invalid posting
  dates last and a stable identity tie-breaker. **Known contact email first**, oldest
  posted and recently added are alternative orders. Discovery/import time never substitutes for a posting
  date. Queue pages and audit API pages are 25 records; every page remains accessible.
- Roles that explicitly require a law degree, bar admission or attorney license are
  hidden from the queue by default. The legal-degree filter can show all roles or
  only those roles. When all roles are shown, flagged roles sort below otherwise
  equivalent jobs. The signal uses practitioner titles and explicit stored credential
  language; absence stays unknown. Legal AI, legal operations, paralegal and legal-
  assistant titles are not rejected merely for containing legal-domain words.
- Employer-scoped identities use stored job IDs, otherwise source URL/title/location.
  Legacy URL-only IDs and reviews are retained where the role and location match.
  Multiple source records can identify the same job, so source totals can exceed the
  number of unique jobs in the queue.
- Old saved `import_limit` values are ignored on read and removed on the next settings
  write; new requests containing that retired control fail validation.

## Search and daily schedule

**Search now** / `job-agent search` starts a background public-source search using
the saved target roles, preferred industries, location preferences and overseas-
employer preference. Comma-, semicolon-, or line-separated preferred industries
are the verifier's allowed employer industries; target roles use the same delimiter
rules and both fields generate the discovery queries. This supports technical,
legal-support and other configured roles across legal, healthcare, medical-imaging,
insurance or future industries without a code change. It then requires exact source
evidence for employer identity, target-role responsibilities, the live role and every
non-unknown geography claim. Results are added
to the existing local job store and the durable collection worker imports them into
this queue. Discovery may also supply official employer contact pages. Recruiting
or routing emails are accepted only when printed on a fetched official page, use
the employer domain and have evidence of a suitable purpose. They are stored once
in `firm_contacts`, so every role attached to that firm reuses the same contacts.
Existing eligible Possible OS contacts are exposed the same way. Searching never
classifies, prepares, sends, or submits an application.

Settings also contains a curated job-board source catalog derived from the operator's
remote-job list. The catalog normalizes duplicates (AngelList into Wellfound,
duplicate Remotees and Remote in Europe entries), corrects stale links and labels
each source as public API, public feed, public page, indexed-web discovery, or
unavailable. Account-only marketplaces, subscription-gated boards and sources whose
current listing surface cannot be verified remain visible but disabled with a reason.
LinkedIn and Wellfound are searched through public indexed pages; Possible OS does
not sign in or automate an account. Enabled sources rotate through the daily and
on-demand source budget, alongside the configured industry/role queries. A board is
only a discovery lead: employer identity, active status, role fit and geography still
require fresh source evidence. `job-agent sources` exposes the same catalog to
headless operators.

The daily timer invokes this same Job Agent search profile. There is no separate
PI-only discovery path: scheduled and **Search now** runs use the same configured
roles, industries, location preferences, verifier, contact discovery and deduplication.
The schedule retains its configured timezone and local time; the nightly firm-research
pipeline remains independent. An operator-triggered search does not consume the
scheduled daily slot. Exact normalized URLs already discovered are skipped before another
verification pass. Storage also merges canonical source URLs or an employer-scoped
ATS provider plus requisition ID, and the queue upserts stable candidate IDs. Titles
alone do not merge jobs. The UI reports verified, new, duplicate-skipped and error
counts, shows the latest scheduled or operator run, and continues to poll while a
run is active.

If the backend restarts during a manual search, startup reconciliation uses the
career-search advisory lock to prove that no worker remains, marks the run
`interrupted`, and leaves retrying to the operator. The UI explains the stop and
re-enables **Search now** instead of displaying a permanent running state.

## Categories and applications

Settings has seven initial categories: AI agents and automation, engineering
leadership, technical product and solutions, data/ML, personal-injury case
management, entry-level paralegal/legal assistant, and personal-injury intake.
Each maps to a reusable one-page PDF under `/home/pranav/resume/job-agent/resumes/`. These are unchanged
copies of previously prepared resumes or validated career-transition resumes, with
source paths and hashes in `provenance.json`.
Add/edit/remove categories, describe their responsibilities, select another PDF
from the local resume library, and preview it. Settings validates assigned PDFs
as readable and exactly one page, restricting paths to the resume library.

The separate **CVs** tab is the operator-facing file library. It puts company-specific
application PDFs first, shows the job, email recipient and application/Sent status,
and keeps reusable category CVs distinct from other saved PDFs. Selecting a CV opens
an inline preview and an explicit browser download using the original filename. The
download endpoint resolves every path beneath `/home/pranav/resume` and returns an
attachment response; arbitrary filesystem paths are rejected. Headless operators can
list the same catalog with `job-agent resumes` and copy one file with
`job-agent resume-download PATH --output FILE`.

A durable background worker classifies a job only after the operator requests it
from that job's detail view or with `job-agent classify ID`. It sends the job's
responsibilities and qualifications plus the complete configured taxonomy to
TypeSafe System One `jev-latest` as a Choice judgment. Possible OS stores the chosen
category, full probability distribution, confidence, exact returned model version
and usage. There is no OpenClaw classification fallback. It uses responsibilities,
not employer sector or keyword rules. The default
confidence threshold is 80%. Unmatched, ambiguous, missing-resume and failed
classifications need review. Operators can override the category or request
reclassification. Operator decisions are protected from late model results.
The detail view distinguishes queued, actively classifying and needs-review states;
an active classification has a bounded provider timeout and becomes needs review on
failure rather than remaining indefinitely active. A batch makes one System One
request with one independent Choice question per job.
Category-definition changes invalidate model classifications that have not entered
application processing. Bulk automatic classification remains an explicit Settings
option and is off by default. Pending jobs do not consume model calls while it is
off. Classification does not assess legal work eligibility or authorize
communication.

Contract status is a separate extraction-time judgment. After a source-backed job
has been extracted, Possible OS sends its employment type, description,
responsibilities and qualifications to TypeSafe Jev in one batched Choice request.
It stores `contract`, `non_contract`, or `unknown` together with all probabilities,
confidence, the exact model version, an input hash and timestamp. Manual and
scheduled Job Agent searches, direct URL imports, and firm job-posting research use
this same hook. Application preparation only reads the stored result and never
classifies it again. A provider failure remains visible as an error-state `unknown`
and does not discard an otherwise verified job. Use `job-agent
backfill-contract-status` for a resumable Jev backfill of older queue rows; it also
updates the matching Leads job-listing mirror. Both lists expose contract-status
filters, and missing legacy values appear under Unknown.

The three career-transition categories are deliberately narrow. Case-management
classification targets assistant, entry-level or trainable PI/pre-litigation work,
including property-damage claim support performed by a PI case-manager assistant.
Paralegal classification targets junior or explicitly trainable supervised work and
rejects postings whose mandatory certificate, jurisdiction qualification or direct-
experience requirements are outside the category. Intake classification targets
hands-on first-contact, screening, documentation, follow-up and new-client handoff
roles that accept transferable experience; it rejects attorney, manager, director,
supervisor, mandatory-language and direct-PI-experience requirements outside the
category. Classification is a resume-routing
decision, not proof that the applicant satisfies employment authorization or a
state's paralegal rules.

Each job detail offers:

- **Open from Leads / Job listings:** resolve the selected locally stored posting
  into its canonical Job Agent candidate and show the same application controls in
  place. The backend rereads the firm's stored posting by job ID, or by normalized
  source URL plus role and location. Opening never classifies, prepares or sends.

- **Import a URL:** `job-agent import-url URL` accepts a specific public job page
  that is not already in Possible OS. It fetches the supplied page, uses the
  evidence-backed career verifier to identify the official employer and exact live
  role, creates or reuses the firm and job records, stores any source-published
  recruiting contacts, and returns the normal Job Agent candidate. A per-URL lock
  makes concurrent retries idempotent without blocking the scheduled search lane.
  If a prior attempt reached a model decision but stopped on evidence validation,
  retrying refetches every cited page and revalidates that saved decision before
  reuse; it does not repeat model work merely because code or transport recovered.
  If the supplied job-board page identifies the exact employer and role but lacks
  the employer's official domain, one bounded public-web enrichment pass may find
  an official identity page for that same employer. It first tries a lightweight
  direct OpenClaw tool call and, when no generic search provider is configured,
  records that result and uses one provider-native search turn. Possible OS then freshly
  fetches and validates the job page and official page before storing anything;
  an ATS, LinkedIn or search-result page cannot become the employer identity.
  If the official page blocks ordinary verification fetches, a public same-origin
  WordPress REST representation of that exact page may be used, but it must still
  pass structured employer identity and exact quoted-evidence validation.
  Application preparation reuses this verified employer-evidence URL when a
  discovered or canonical homepage is blocked, allowing eligible Possible OS
  recruiting contacts for that canonical firm to reach drafting.
  Every attempt writes start and terminal activity events, with the career-search
  run ID and exact stop reason when verification fails. Importing never classifies,
  prepares or sends.

- **Prepare email:** research the company and role, check public pages and eligible
  Possible OS `firm_contacts`, compose and audit a concise founder-led email using
  the mapped resume, check duplicates, and save a company/role-named PDF and
  application packet. This never authorizes sending.
- **Apply via Zoho / Send via Zoho:** explicitly authorizes one application for that
  job. Research and preparation are automatic when needed. Recruiting contacts are
  preferred; a suitable company routing contact can be used with a routing request.
  Recipient evidence may be a freshly fetched official page or a Possible OS contact
  record that passes firm identity, official-domain and role-suitability filters.
  The application packet and UI retain its contact ID, source and observed timestamp.
  Stored patient/intake/records, privacy, security, press and unrelated-domain
  addresses are rejected. Public pages must still verify the employer and open role.
  The imported job page is retried and fetch failures are retained in the packet.
  If that page is inaccessible, a directly fetched employer page or established job
  platform may corroborate the role. TypeSafe Jev scores each fetched role source
  against the saved job using employer, function, specialty, seniority and role
  evidence, then records and uses the highest-probability match. There is no fixed
  confidence cutoff; semantic identity and exact evidence remain the safety gates.
  Alternate sources do not need to match a fixed host allowlist. They must still be freshly
  fetched, cited by the packet, and pass semantic employer/role identity and exact-quote checks.
  Equivalent URL presentations are normalized for fragments, tracking parameters and trailing slashes. Company
  evidence may cite any freshly fetched page on the verified employer domain rather
  than only the discovery step's exact page. If composition paraphrases a company or
  role excerpt, the agent may recover only by freshly rechecking the previously stored
  verified excerpt on its cited source; it does not accept the paraphrase itself.
  Closed/unverified jobs, uncertain
  recipients and unsupported claims stop for review.
- **Check Zoho Sent:** verifies an uncertain send without sending another email.

PDF contents are reused by category; the email is specific to the job. No speculative
resume claims or automatic per-job PDF rewriting. Application artifacts live under
`resume/applications/<company>/<role>_<candidate>/job-agent_<run>/`.

Before sending, check previous application handoffs, durable scheduled/pending/send
records, and Zoho Sent/draft/outbox folders for matching applications. Mailbox reads
are read-only. Upload the PDF using the existing authenticated Zoho attachment API,
then send through `/usr/local/bin/zmail-possibleos message send` (official CLI), with
no Resend fallback. Persist sending intent before the provider call. Repeated clicks
coalesce; ambiguous results and interrupted sends become `delivery_unconfirmed` and
are never automatically resent. When the initial Sent copy is delayed, the worker
performs up to three additional read-only IMAP checks after approximately 30 seconds,
2 minutes and 10 minutes. The operator can also request a read-only check at any time.
Successful status requires matching the recipient, subject/body and attachment hash
in Zoho Sent. Sent evidence is not proof of recipient
delivery or an ATS submission. Each attempted send is also mirrored idempotently into
the shared Communications email log with its company, recipient, complete body,
Zoho status and Job Agent source ID. Rechecking Zoho Sent updates that row instead of
creating another apparent email. No live recipient was emailed during build validation.

The job dialog shows category, reason/confidence, selected PDF, recipient source,
prepared email and gaps. Application observability is a persisted checkpoint flow:
resume selection, source/contact verification, draft audit, duplicate checking, PDF
creation, Zoho send, and Sent verification. Each checkpoint is rendered as pending,
active, completed, stopped or uncertain. Failures retain the phase and exact error.
Research now exposes public-web discovery, source fetching, Possible OS contact
checking, recipient selection and drafting as distinct phases. Preparation is capped
at four minutes by default (`JOB_AGENT_PREPARATION_TIMEOUT_S`); each gateway request
is capped at 150 seconds (`JOB_AGENT_GATEWAY_TIMEOUT_S`). A timeout becomes a stopped,
retryable preparation and never authorizes or sends email. If polling fails, the UI
replaces the activity spinner with a status-refresh error and a manual reload control
while continuing background status checks.

Structured OpenClaw work uses the native WebSocket RPC `agent` method. Job Agent
preparation is routed to `possibleos-interactive`; scheduled career search, firm
enrichment, job-opening research, review research and other maintenance work use
`possibleos-batch`. Each lane is serialized locally and by OpenClaw, while the two
lanes can run concurrently. A unique internal session is used for each call and
deleted after its JSON response is read. `OPENCLAW_GATEWAY_RPC_URL`,
`OPENCLAW_RPC_INTERACTIVE_LANE` and `OPENCLAW_RPC_BATCH_LANE` override the defaults.
Job Agent drafting and other supplied-evidence JSON judgments use OpenClaw's raw
model-run mode without tools or workspace bootstrap; public-source research keeps
the minimal tool-enabled runtime.
The retired `/v1/chat/completions` endpoint is not used by this shared client.

Preparation failures can start a new draft-only attempt; duplicate blocks require
manual review. Once a provider send starts, the UI never offers a preparation retry
or resend and shows the scheduled or operator-requested read-only Sent checks. `ready`
always means draft/PDF ready and not sent; `sent_verified` means an exact Sent copy
was found, not recipient delivery or ATS submission. Activity remains hidden.
Automatic inbox referral handling and portal submission are future work.
Manual review decisions remain separate from category and application statuses.
The separate daily discovery schedule is unaffected by these controls.

## Persistence and API

`app/services/job_agent.py` owns `job_agent_state`, `job_agent_candidates`,
`job_agent_events`, `job_agent_collection_runs`, `job_agent_collection_items` and
`job_agent_processing`. The processing worker holds a PostgreSQL advisory lock so
only one executor processes applications across daemon instances.
Tables initialize additively under a PostgreSQL advisory lock. A state-row lock
serializes run creation, processing chunks and preference changes across workers.
Failure rolls back the current chunk and records an error separately. Settings and
reviews use optimistic revisions (stale updates return HTTP 409). HTTP endpoints
inherit daemon authentication. UI overview and queue poll every 15 seconds; the hidden activity feed is not fetched.

| Endpoint | CLI |
| --- | --- |
| GET `/api/job-agent/overview` | `job-agent status` |
| GET `/api/job-agent/config` | `job-agent config` |
| GET `/api/job-agent/sources` | `job-agent sources` |
| POST `/api/job-agent/config` | `job-agent configure --file preferences.json` |
| POST `/api/job-agent/collect` | `job-agent collect` |
| POST `/api/job-agent/search` | `job-agent search` |
| POST `/api/job-agent/listings/open` | `job-agent open-listing --firm-id ID --source-url URL --title TITLE [...]` |
| POST `/api/job-agent/listings/import` | `job-agent import-url URL` |
| GET `/api/job-agent/jobs` | `job-agent jobs [--status shortlisted --search AI --page 1 --order posted_desc --source external_search]` |
| POST `/api/job-agent/jobs/{id}/review` | `job-agent review ID --revision N --status shortlisted --note "…"` |
| GET `/api/job-agent/events?page=1` | `job-agent events --page 1` |
| GET `/api/job-agent/resumes` | `job-agent resumes` (catalog with category and application-email context) |
| GET `/api/job-agent/applications` | `job-agent applications [--status ready --search Array --page 1 --order updated_desc]` |
| GET `/api/job-agent/resume?path=...&download=true` | Preview or download a catalog file; CLI: `job-agent resume-download PATH --output FILE` |
| GET `/api/job-agent/jobs/{id}` | `job-agent show ID` |
| POST `/api/job-agent/jobs/{id}/classify` | `job-agent classify ID` |
| POST `/api/job-agent/jobs/{id}/category` | `job-agent category ID --category ai_automation --revision N` |
| POST `/api/job-agent/jobs/{id}/application` (mode prepare) | `job-agent prepare ID --revision N` |
| POST `/api/job-agent/jobs/{id}/application` (mode send) | `job-agent apply ID --revision N` |
| POST `/api/job-agent/jobs/{id}/verify-sent` | `job-agent verify-sent ID` |
| POST `/api/job-agent/sync-comms` | `job-agent sync-comms` |

Use `processing_revision` from `show` for category/application actions. `jobs` also
accepts `--category CATEGORY` or `--category needs_review`, `--source
external_search|possibleos`, and `--legal-degree exclude|all|required` (default:
`exclude`). Search-produced jobs store `job_source=external_search`;
listings collected from the wider Possible OS firm directory store
`job_source=possibleos`. Older rows are derived from their discovery provider and
receive the explicit field on the next normal sync.
`sync-comms` repairs historical `sent_verified` and `delivery_unconfirmed` application
records in Communications without sending or changing mailbox state.

Orders: `posted_desc` (default), `contact_desc` (known firm email, then newest),
`posted_asc`, `found_desc` (added to queue).
All commands return JSON. `configure` accepts partial preferences and merges using
the current revision. Collection requests coalesce while a run is in progress.

## Validation

`python -m pytest tests/test_job_agent.py -q` covers schemas, URL identities, date
normalization, default ordering and API conflicts. With the project environment
loaded, `JOB_AGENT_DB_TESTS=1` also uses an isolated PostgreSQL schema to verify
605-record uncapped ingestion, concurrent requests, pause/resume, interruption and
checkpoint rollback, source changes during a run, automatic pickup, legacy review
preservation, source closures, complete queue pagination and activity beyond 100.
Frontend validation: staged production build plus desktop/mobile browser checks.

`tests/test_job_agent_processing.py` covers PDF restrictions, category uniqueness,
classification/overrides, direct and corroborating-source evidence validation,
explicit send intent, mocked Zoho CLI
attachment syntax, duplicate blocking, uncertain-send handling, exact Sent/PDF
verification and a complete prepared-to-sent workflow in an isolated database.


## Website applications

The shared application modal now includes **Apply on website**, live browser
progress, screenshots, application-specific questions, saved answers, pause and
resume controls. Website runs have independent status and confirmation evidence;
see [Website application architecture and operations](JOB_BROWSER_APPLICATIONS.md).
The Applications tab lists website runs and email applications separately.


Website applications support a saved OpenClaw gateway/direct OpenAI API choice in
Settings and a per-run provider selector when starting or resuming. Decisions,
audits and confirmation use the same selected provider. API keys remain on the
server; provider changes never unlock uncertain submissions.

### Automatic resume selection in applications
Website start and email prepare/apply now include category matching and one-page PDF selection as the first saved worker step. Existing valid selections and manual categories are reused. CLI commands and APIs accept unclassified jobs without an extra classification call. Opening a job does not start work. The modal shows a shared resume card with optional category controls, a website workflow with three progress stages, and an expandable email workflow. Missing resume mappings and classification failures remain actionable blockers.

### Reusable applicant profile
Answers to website application questions are saved automatically for contextual reuse. Manage them in the Applicant profile tab or inside the application modal. CLI: `job-agent profile`, `profile-save --file FILE`, `profile-remove ID --revision N`, `profile-import-answers`. `browser-control --action answer` defaults to remembering; `--this-application-only` limits reuse. See [JOB_APPLICANT_PROFILE.md](JOB_APPLICANT_PROFILE.md) for scope, provenance, snapshot and conflict behavior.


Resume selection uses Jev's highest-ranked category with an assigned PDF, even
when No clear match wins overall. The raw probabilities remain visible; closest
match does not establish qualifications. Confidence is informational, never a
selection gate; legacy classification_threshold values are ignored. Explicit
manual categories remain authoritative. Missing/invalid PDFs or failed model
requests still require correction. Use the existing classify or browser resume
commands for an individual job; no bulk reclassification is triggered.
