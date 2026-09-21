# Job agent workspace

The `/job-agent` tab provides a persistent operator review queue, preferences,
and collection progress. Only Review queue and Settings tabs are shown; the Activity
tab is hidden for now. Audit history remains available through the CLI/API.
Jobs can be classified on demand into configurable resume categories. Applications
are processed only after an explicit operator action. Email delivery uses the
official Zoho CLI.

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
from that job's detail view or with `job-agent classify ID`. It uses the existing
isolated OpenClaw `neo` lane and structured category IDs, confidence, reasons and
industry tags, avoiding contention with the stateful main-agent research queue. It
uses responsibilities, not employer sector or keyword rules. The default
confidence threshold is 80%. Unmatched, ambiguous, missing-resume and failed
classifications need review. Operators can override the category or request
reclassification. Operator decisions are protected from late model results.
The detail view distinguishes queued, actively classifying and needs-review states;
an active classification has a bounded provider timeout and becomes needs review on
failure rather than remaining indefinitely active.
Possible OS serializes calls within each OpenClaw agent lane but does not make the
independent `neo` classifier wait behind another agent's research requests.
Category-definition changes invalidate model classifications that have not entered
application processing. Bulk automatic classification remains an explicit Settings
option and is off by default. Pending jobs do not consume model calls while it is
off. Classification does not assess legal work eligibility or authorize
communication.

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
  platform may corroborate the same exact title and employer; alternate sources must
  pass trusted-host and exact-quote checks. Closed/unverified jobs, uncertain
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
| POST `/api/job-agent/config` | `job-agent configure --file preferences.json` |
| POST `/api/job-agent/collect` | `job-agent collect` |
| POST `/api/job-agent/search` | `job-agent search` |
| POST `/api/job-agent/listings/open` | `job-agent open-listing --firm-id ID --source-url URL --title TITLE [...]` |
| GET `/api/job-agent/jobs` | `job-agent jobs [--status shortlisted --search AI --page 1 --order posted_desc --source external_search]` |
| POST `/api/job-agent/jobs/{id}/review` | `job-agent review ID --revision N --status shortlisted --note "…"` |
| GET `/api/job-agent/events?page=1` | `job-agent events --page 1` |
| GET `/api/job-agent/resumes` | `job-agent resumes` (catalog with category and application-email context) |
| GET `/api/job-agent/resume?path=...&download=true` | Preview or download a catalog file; CLI: `job-agent resume-download PATH --output FILE` |
| GET `/api/job-agent/jobs/{id}` | `job-agent show ID` |
| POST `/api/job-agent/jobs/{id}/classify` | `job-agent classify ID` |
| POST `/api/job-agent/jobs/{id}/category` | `job-agent category ID --category ai_automation --revision N` |
| POST `/api/job-agent/jobs/{id}/application` (mode prepare) | `job-agent prepare ID --revision N` |
| POST `/api/job-agent/jobs/{id}/application` (mode send) | `job-agent apply ID --revision N` |
| POST `/api/job-agent/jobs/{id}/verify-sent` | `job-agent verify-sent ID` |
| POST `/api/job-agent/sync-comms` | `job-agent sync-comms` |

Use `processing_revision` from `show` for category/application actions. `jobs` also
accepts `--category CATEGORY` or `--category needs_review`, and `--source
external_search|possibleos`. Search-produced jobs store `job_source=external_search`;
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
