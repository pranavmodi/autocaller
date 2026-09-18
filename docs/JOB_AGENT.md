# Job agent workspace

The `/job-agent` tab provides a persistent operator review queue, preferences,
and collection progress. Only Review queue and Settings tabs are shown; the Activity
tab is hidden for now. Audit history remains available through the CLI/API.
Jobs are classified into configurable resume categories. Applications are processed
only after an explicit operator action. Email delivery uses the official Zoho CLI.

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
  dates last and a stable identity tie-breaker. Oldest posted and recently added to
  queue are alternative orders. Discovery/import time never substitutes for a posting
  date. Queue pages and audit API pages are 25 records; every page remains accessible.
- Employer-scoped identities use stored job IDs, otherwise source URL/title/location.
  Legacy URL-only IDs and reviews are retained where the role and location match.
  Multiple source records can identify the same job, so source totals can exceed the
  number of unique jobs in the queue.
- Old saved `import_limit` values are ignored on read and removed on the next settings
  write; new requests containing that retired control fail validation.

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
are never automatically resent. Successful status requires matching the recipient,
subject/body and attachment hash in Zoho Sent. Sent evidence is not proof of recipient
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
or resend and exposes only the read-only Zoho Sent verification action. `ready`
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
| POST `/api/job-agent/listings/open` | `job-agent open-listing --firm-id ID --source-url URL --title TITLE [...]` |
| GET `/api/job-agent/jobs` | `job-agent jobs [--status shortlisted --search AI --page 1 --order posted_desc]` |
| POST `/api/job-agent/jobs/{id}/review` | `job-agent review ID --revision N --status shortlisted --note "…"` |
| GET `/api/job-agent/events?page=1` | `job-agent events --page 1` |
| GET `/api/job-agent/resumes` | `job-agent resumes` |
| GET `/api/job-agent/resume?path=...` | Preview a file returned by `job-agent resumes` |
| GET `/api/job-agent/jobs/{id}` | `job-agent show ID` |
| POST `/api/job-agent/jobs/{id}/classify` | `job-agent classify ID` |
| POST `/api/job-agent/jobs/{id}/category` | `job-agent category ID --category ai_automation --revision N` |
| POST `/api/job-agent/jobs/{id}/application` (mode prepare) | `job-agent prepare ID --revision N` |
| POST `/api/job-agent/jobs/{id}/application` (mode send) | `job-agent apply ID --revision N` |
| POST `/api/job-agent/jobs/{id}/verify-sent` | `job-agent verify-sent ID` |
| POST `/api/job-agent/sync-comms` | `job-agent sync-comms` |

Use `processing_revision` from `show` for category/application actions. `jobs` also
accepts `--category CATEGORY` or `--category needs_review`.
`sync-comms` repairs historical `sent_verified` and `delivery_unconfirmed` application
records in Communications without sending or changing mailbox state.

Orders: `posted_desc` (default), `posted_asc`, `found_desc` (added to queue).
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
