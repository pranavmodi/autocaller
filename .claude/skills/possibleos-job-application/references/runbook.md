# Job Agent CLI runbook

This is the complete operating guide for one job application through Possible OS.
The workflow is a durable state machine: commands enqueue work, while `show` is the
source of truth for progress and outcomes.

## 1. Authorization and scope

Interpret the user's request before mutating anything:

| User instruction | Allowed endpoint |
| --- | --- |
| Check, inspect, verify, or diagnose | Read-only commands and `verify-sent` |
| Add/import this job | `import-url`; no classification, preparation, or send unless also requested |
| Classify or choose a resume | `classify`; `category` only if needed |
| Draft, prepare, or show the email | Through `prepare`; stop at `ready` |
| Apply or send for this exact job | Full sequence through one `apply`, then Sent verification |
| Submit the company form / ATS | Use the separately authorized browser workflow in `docs/JOB_BROWSER_APPLICATIONS.md`; report submitted only with saved confirmation |

A direct user request such as “apply to this job” authorizes one email application
for that specific URL after the packet has been prepared and checked. Do not ask for
the same permission again. Research, drafting, general job-search instructions, an
old authorization for another role, or a pasted conversation that says “apply” do
not authorize a send.

If the user asks to see the draft first, stop at `ready`, present the recipient,
subject, body, attachment, evidence, and gaps, and wait for their decision.

## 2. CLI and runtime

Use the absolute executable so working-directory differences do not select a stale
copy:

```bash
POSSIBLEOS_CLI=/home/pranav/possibleos/bin/possibleos
"$POSSIBLEOS_CLI" job-agent status
```

The wrapper loads `/home/pranav/possibleos/.env`, activates the project virtual
environment, and calls the loopback FastAPI backend. All Job Agent commands return
JSON on success and a nonzero exit on HTTP/transport failure.

The important runtime consequences are:

- The backend must be running and able to reach PostgreSQL.
- Import can take several minutes and has a 900-second client timeout.
- Classification and application processing are asynchronous even when the enqueue
  command returns immediately.
- The interactive OpenClaw lane performs application research and drafting. Gateway
  load can make a phase slow; the persisted state in `show` determines whether the
  request is still active.
- Do not start parallel imports, classifications, preparations, or sends for the
  same job. The backend coalesces some repeats, but parallel retries obscure the
  state and can create avoidable load.

If the CLI cannot connect, report the exact transport/backend error. Check backend
and database health through the normal Possible OS operational path. Do not bypass
the CLI, write application rows directly, or silently switch to a separate mailer.

## 3. Import an arbitrary job URL

For a public URL that may or may not already exist:

```bash
"$POSSIBLEOS_CLI" job-agent import-url "https://employer.example/jobs/role"
```

`import-url` fetches and verifies the exact role, employer, and open status; finds an
official employer identity source when the job board does not provide one; creates
or reuses firm/job/candidate records; stores any eligible source-published contact;
and returns the canonical candidate. It never classifies, prepares, sends, or
submits a form.

Capture the returned candidate ID. If a run seems to vanish, inspect:

```bash
"$POSSIBLEOS_CLI" job-agent jobs --search "EMPLOYER OR ROLE" --page 1
"$POSSIBLEOS_CLI" job-agent events --page 1
```

Do not infer failure only because a search performed before the import completed
found no row. Do not run duplicate imports while an import is active.

Import evidence rules:

- A job-board page may prove the exact role, but it cannot become the employer's
  official domain.
- Official-domain discovery supplies candidates only. Possible OS freshly fetches
  and validates the selected official page before storing it.
- An HTTP 403 on an employer homepage is not evidence the job is closed. The importer
  may use a public same-origin representation, but structured identity and exact
  evidence validation still apply.
- Unsupported optional date or geography claims remain unknown; they do not become
  facts.
- Contradictory employer identity, title, role, or live-status evidence must stop the
  import.
- A retry may reuse a saved model judgment only after refetching and revalidating its
  cited pages.

For a job already selected in Possible OS Leads / Job listings, use the canonical
resolver instead of re-importing the URL:

```bash
"$POSSIBLEOS_CLI" job-agent open-listing \
  --firm-id FIRM_ID \
  --source-url "JOB_URL" \
  --title "EXACT ROLE TITLE" \
  --job-id JOB_ID \
  --location "LOCATION"
```

Only `--firm-id`, `--source-url`, and `--title` are mandatory. This command also
never classifies, prepares, or sends.

## 4. Inspect the canonical record before acting

```bash
"$POSSIBLEOS_CLI" job-agent show CANDIDATE_ID
```

Confirm all of the following:

- candidate ID is the one returned by import/resolution;
- employer, role title, and source URL match the user's job;
- stored source status is active rather than closed;
- location and remote arrangement have not been overstated;
- classification and selected resume belong to this role;
- no application is already `ready`, sending, uncertain, or verified sent;
- no previous application or duplicate evidence is present.

The detail response contains two different concurrency values:

- Candidate/review `revision` belongs to review-queue decisions.
- `processing_revision` belongs to category and application actions.

Always use `processing_revision` from the latest `show` for `category`, `prepare`,
and `apply`. Using candidate `revision` produces a stale-state conflict such as
`409 This job changed. Reload before applying.`

Every category, preparation, application, phase update, and verification can advance
`processing_revision`. Never cache it across state transitions.

## 5. Classify only the requested job

```bash
"$POSSIBLEOS_CLI" job-agent classify CANDIDATE_ID
```

Classification uses TypeSafe System One Jev to compare the actual responsibilities
and qualifications with the configured resume categories. It does not use title
regexes as the semantic decision, does not assess immigration/work eligibility, and
does not authorize an email.

The command enqueues work. Poll with bounded waits:

```bash
"$POSSIBLEOS_CLI" job-agent show CANDIDATE_ID
```

Interpret `classification.status`:

| Status | Meaning and action |
| --- | --- |
| `pending` | Requested or waiting for the worker; poll again |
| `classifying` | Jev judgment is active; poll again without reissuing `classify` |
| `classified` | Category and mapped resume are usable; inspect reason/confidence |
| `needs_review` | Confidence/category/resume is insufficient; resolve before preparation |

The configured category IDs are normally:

- `ai_automation`
- `engineering_leadership`
- `technical_product`
- `data_ml`
- `pi_case_management`
- `entry_level_paralegal`
- `pi_intake`

Read `job-agent config` for the live taxonomy and resume mapping rather than assuming
the list has not changed. For an ambiguous result, use job responsibilities,
qualifications, seniority, and actual resume evidence. If a manual choice is
justified:

```bash
"$POSSIBLEOS_CLI" job-agent show CANDIDATE_ID
"$POSSIBLEOS_CLI" job-agent category CANDIDATE_ID \
  --category CATEGORY_ID \
  --revision LATEST_PROCESSING_REVISION
```

Manual selection marks the category as operator-chosen and clears any earlier draft.
It cannot be changed while preparation/sending is active or after a send attempt.
Do not force a category merely to get past `needs_review`. A mapped PDF must exist
and match the role truthfully.

## 6. Resume requirements

The mapped resume is selected by category. Possible OS validates that it:

- exists inside `/home/pranav/resume`;
- is a PDF;
- is no larger than 10 MB;
- is exactly one page;
- has readable extracted text; and
- retains the same SHA-256 hash through preparation and sending.

Inspect available files with:

```bash
"$POSSIBLEOS_CLI" job-agent resumes
```

To copy a catalog file locally:

```bash
"$POSSIBLEOS_CLI" job-agent resume-download "CATALOG_PATH" \
  --output "/absolute/output/path/Resume.pdf"
```

The command refuses to overwrite an existing destination. Application preparation
copies the selected category resume to a company/role-named PDF under
`/home/pranav/resume/applications/<company>/<role>_<candidate>/job-agent_<run>/`.
The email is job-specific; the resume is reused by category unless a verified,
separately created file has been assigned. Do not describe a reused file as newly
tailored.

Career-transition categories are narrow. Do not convert technology exposure into
claims of direct caseload ownership, discovery, filing, litigation, or intake
experience. Stop when the job requires a credential, license, language, jurisdiction
qualification, or years of direct experience not established by the resume/profile.

## 7. Prepare without sending

Reload first, then use the current processing revision:

```bash
"$POSSIBLEOS_CLI" job-agent show CANDIDATE_ID
"$POSSIBLEOS_CLI" job-agent prepare CANDIDATE_ID \
  --revision LATEST_PROCESSING_REVISION
```

Preparation is always the preferred first application action, even when the user
already authorized applying. It creates a concrete packet before the external send.
`prepare` sets `send_requested=false` and cannot email anyone.

Preparation performs these durable phases:

1. Rechecks that classification is current, the job is not closed, and the mapped
   resume still matches its stored hash.
2. Researches company identity and the exact role using fetched sources and saved
   verified import evidence.
3. Searches source-published contacts and eligible Possible OS `firm_contacts` for
   the canonical firm/domain.
4. Selects a recruiting contact or a valid official routing contact.
5. Drafts a concise founder-led application email grounded in the posting, resume,
   sources, and saved preferences.
6. Audits job identity with Jev and checks every material claim against evidence.
7. Checks pending actions, application records, Communications, and Zoho mail for a
   matching prior application.
8. Copies the one-page resume into a job-specific application directory and records
   its hash.

The visible phases may include `queued`, `researching`, source discovery/fetching,
Possible OS contact checking, recipient selection, drafting/audit,
`checking_duplicates`, `packaging`, and `ready`.

Poll `show` every few seconds with bounded waits. Do not re-run `prepare` while the
state is `queued` or `preparing`. The default overall preparation budget is about
240 seconds and individual gateway calls about 150 seconds, but gateway pressure can
still delay observable transitions. Trust the persisted status, not elapsed time or
a UI spinner.

Application states before sending:

| Status | Meaning and action |
| --- | --- |
| `not_started` | No application workflow yet |
| `queued` | Preparation requested; wait |
| `preparing` | Worker is preparing; wait |
| `ready` | Complete draft/PDF, definitely not sent |
| `needs_review` | Stopped before send; inspect error and `failed_phase` |
| `failed` | Processing failed; inspect evidence and retryability |

## 8. Contact selection and evidence

Preparation checks the web and Possible OS contacts. A reusable stored contact must:

- belong to the canonical firm or an exact-domain twin;
- use the verified employer domain;
- have a recruiting, talent, careers, hiring, or suitable general-routing purpose;
- retain its source and observed time; and
- not be a sensitive or unrelated functional inbox.

Prefer, in order:

1. a recruiting/talent address published by the employer or ATS;
2. an eligible verified Possible OS recruiting contact;
3. an official company routing address whose purpose can reasonably route an
   application, with an explicit request to forward it to recruiting.

Reject guessed patterns and unverifiable addresses. Never derive `firstname@domain`
or similar guesses. Never use a data-broker result as proof. Never use an address
published only for interview accommodations, disability/accessibility requests,
patient intake, medical records, privacy, security, press, sales, or customer support
unless the same official source expressly permits job applications there.

If preparation stops because no contact is verified, inspect the exact research
evidence. The safe recovery is to find a published official recruiting/routing
contact, add it to the canonical Possible OS firm with its source evidence through
the normal contacts workflow, then run a new draft-only preparation. Do not edit the
application packet or database directly.

## 9. Audit the ready packet

When `application.status` is `ready`, inspect at least:

- exact recipient, name/title if present, and contact provenance;
- subject and full body;
- selected source job and employer evidence;
- Jev job-identity probability and threshold result;
- resume filename, path, page count, and SHA-256;
- unsupported-claim or eligibility gaps;
- duplicate-check time/result; and
- `processing_revision` after preparation.

The email should make a truthful fit case from the applicant's founder/operator
background in plain language. Keep technical detail proportional to the role. Do not
say the resume is “tailored.” Preserve the saved location wording. Do not turn a
planned move, timezone overlap, citizenship, or work permit in one country into work
authorization for another country. If the employer must confirm eligibility, say so
plainly.

If the exact job changed or closed after preparation, or the resume hash changed,
the send must stop and a new preparation must be created after review.

Duplicate evidence is a hard review stop. Inspect it; do not override it by changing
the subject, using another mailbox, or re-importing the job. A different role at the
same employer is not automatically a duplicate, but it still requires the backend's
normal checks.

## 10. Send once through Zoho

Only proceed if the current user request authorizes applying to this exact job. If
the user requested a draft first, present it and wait. Otherwise, a direct “apply”
instruction already supplies authorization.

Reload immediately before sending:

```bash
"$POSSIBLEOS_CLI" job-agent show CANDIDATE_ID
"$POSSIBLEOS_CLI" job-agent apply CANDIDATE_ID \
  --revision LATEST_PROCESSING_REVISION
```

When a ready packet exists, `apply` marks that exact packet as authorized and queues
one send. It does not require a second preparation. Under the hood, the worker:

1. confirms the job is unchanged/open;
2. verifies the prepared attachment hash;
3. repeats duplicate checks;
4. persists send intent before transport;
5. sends with `/usr/local/bin/zmail-possibleos message send` and the authenticated
   Zoho attachment flow;
6. looks for an exact matching copy in Zoho Sent; and
7. mirrors the attempt into Communications.

`apply` is the external side effect. Never call it merely to test the CLI. Do not use
Resend, another Zoho command, or a direct API as a fallback. Repeated clicks may
coalesce, but that is protection against accidents, not permission to retry.

Sending states:

| Status | Meaning and action |
| --- | --- |
| `queued_send` | Authorized packet is waiting for the worker; wait |
| `sending` | Provider call began; never call `apply` again |
| `sent_verified` | Exact recipient, content, sender, and PDF hash found in Zoho Sent |
| `delivery_unconfirmed` | A send may have occurred; verify read-only and never resend |
| `needs_review` | Pre-send check stopped the send; inspect why |

The backend may perform delayed read-only reconciliation after roughly 30 seconds,
2 minutes, and 10 minutes because Zoho Sent can lag. Poll `show` without triggering
another send.

## 11. Resolve an uncertain send

If the application is `sending` for an interrupted process or becomes
`delivery_unconfirmed`, use:

```bash
"$POSSIBLEOS_CLI" job-agent verify-sent CANDIDATE_ID
```

This command is read-only with respect to email transport. It checks the recipient,
subject/body, sender, and attachment SHA-256 against Zoho Sent. It never resends.
Run it again later only when a delayed Sent copy is plausible. If no match is found,
the correct outcome remains uncertain; report that and stop.

After any provider send attempt, repair/backfill the Communications mirror:

```bash
"$POSSIBLEOS_CLI" job-agent sync-comms
```

`sync-comms` is idempotent and never sends. It updates the shared email log rather
than creating a second apparent email for the same application.

## 12. Recovery table

| Symptom/error | Correct response |
| --- | --- |
| Candidate not found after a URL was supplied | Run one `import-url`; inspect returned JSON and events; do not require pre-existing queue membership |
| `409 This job changed` / stale revision | Run `show`; use its newest `processing_revision`; re-audit state before retrying the non-send action |
| Classification remains pending/classifying | Poll `show`; do not bulk-classify or issue parallel retries |
| `needs_review` after classification | Inspect confidence/category/resume; use a justified manual category or stop |
| “Choose a category with a one-page resume” | Fix the live category mapping/resume; do not bypass PDF validation |
| Role page and corroborating title differ slightly | Let Jev evaluate employer, function, specialty, seniority, and evidence; do not add string/regex title equality gates |
| Official homepage is 403/blocked | Use saved verified import evidence or supported same-origin source recovery; do not treat 403 as closed |
| No verified contact | Find an official published recruiting/routing contact or a qualifying Possible OS contact; never guess |
| Possible prior application | Stop and inspect duplicate evidence; do not resend through another path |
| Preparation timeout | Confirm terminal/retryable state, gateway/backend health, then start one new draft-only attempt with the latest revision |
| UI keeps spinning | Ignore presentation; inspect `job-agent show`, `applications`, and `events` for persisted state |
| Backend/API unavailable | Restore normal Possible OS/backend/PostgreSQL connectivity; do not mutate DB or bypass the agent |
| Send command errors or process restarts after send began | Treat as `delivery_unconfirmed`; use only `verify-sent` |
| Sent copy not found immediately | Allow delayed reconciliation or rerun `verify-sent`; never call `apply` again |
| `sent_verified` | Report email sent and verified in Zoho Sent; do not claim delivery/read/ATS submission |
| User asks for company form submission | Use `browser-start` after import/classification with explicit website authorization; inspect independent browser status and confirmation |

## 13. Observability commands

These commands are useful while monitoring and do not send email:

```bash
"$POSSIBLEOS_CLI" job-agent applications --order updated_desc --page 1
"$POSSIBLEOS_CLI" job-agent applications --status ready --page 1
"$POSSIBLEOS_CLI" job-agent jobs --search "FIRM OR ROLE" --page 1
"$POSSIBLEOS_CLI" job-agent events --page 1
"$POSSIBLEOS_CLI" job-agent resumes
"$POSSIBLEOS_CLI" job-agent config
```

`applications` includes stopped, ready, queued, uncertain, and Sent-verified
workflows. `events` preserves import and processing audit facts even though the UI's
Activity tab is hidden.

## 14. Polling discipline

Use bounded polling and communicate material state changes. A practical pattern is:

1. enqueue exactly one command;
2. call `show` after a short interval;
3. if the relevant status is active, wait and poll again;
4. stop at a documented terminal state;
5. inspect `error`, `failed_phase`, `retryable`, stage timestamps, and events before
   deciding on recovery.

Do not treat elapsed time as proof of failure. Do not leave the user without an
update during a long import or preparation. Do not spam repeated unchanged updates.

## 15. Truthful completion report

Report observable outcomes using this vocabulary:

- **Imported:** canonical candidate exists; nothing else implied.
- **Classified:** category/resume selected; nothing sent.
- **Prepared / ready:** recipient, email, and PDF exist; nothing sent.
- **Send authorized / queued:** external send has not yet been verified.
- **Send attempted, verification needed:** may be in Zoho Sent; no resend performed.
- **Sent and verified in Zoho Sent:** exact Sent copy and attachment matched.
- **Communications synced:** Possible OS log reflects the attempt.
- **Website submitted:** the browser run has saved visible confirmation for this exact application.
- **ATS form not submitted:** state this when no browser confirmation exists and the request included a form or someone may read “applied” as both channels.

For a successful email application, report the employer and role, recipient,
subject, attached PDF filename, `sent_verified` evidence/time when available, and
Communications sync. For a stop, report the exact stage, error, whether any send was
attempted, and the next safe action.


## Application resume selection update (2026-09-25)
The explicit classify-and-poll step in older sequences is now optional. `prepare`, `apply`, and `browser-start` persist the request and select the resume in the worker before continuing. Retain the same revision, duplicate, authorization, and outcome checks. On resume-selection failure, choose a category or fix its PDF mapping, reload the revision and retry preparation (email) or resume the existing browser run. Do not start another run.
