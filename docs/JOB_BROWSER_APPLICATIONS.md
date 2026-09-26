# Website applications in Job Agent

Job Agent supports two independent submission channels: Zoho application emails
and employer website forms. Opening a job starts neither. **Start website
application** authorizes one browser submission for that exact saved job with its
automatically selected category resume. The worker reuses a valid existing choice or classifies this one job with Jev before opening the browser. Manual choices are preserved. Email preparation is not a prerequisite.

## Operator sequence

1. Import the exact URL using `job-agent import-url URL` or open an existing job.
2. Optionally assign a category. A separate classification command is no longer required.
3. Read `job-agent show ID` and its `processing_revision`.
4. Run `job-agent browser-start ID --revision N --authorize-submit` only when the
   user authorized website submission. Repeated starts return the existing run.
5. Poll `job-agent browser-status ID`. It returns the separate browser `revision`,
   current page, actions, errors, pending question, and confirmation evidence.
6. For `waiting_for_answer`, obtain a truthful answer, write it to a UTF-8 file,
   then use `job-agent browser-control ID --action answer --revision N
   --question-id QUESTION_ID --answer-file answer.txt`. Use the browser revision,
   not the classification revision. The live form remains open while waiting.
7. Use `browser-control --action pause` to stop after any in-flight action.
   Resume a paused/blocked pre-submit run with `--action resume`. A revision
   conflict means refresh status before retrying the control.
8. `submitted` requires a recorded submit action and independently checked visible
   confirmation. It does not mean email was sent, delivery occurred, or an
   interview was offered. Saved email status is never overwritten.

`browser-applications` lists website runs. `browser-screenshot ID --output page.png`
copies the latest screenshot on the server. Events are paginated in groups of 100;
pass `browser-status ID --after NEXT_CURSOR` to inspect all history. The modal
shows the latest 100, not a retention limit.

## Runtime and model loop

The background worker saves each run and its append-only events in
`job_agent_browser_runs` and `job_agent_browser_events`. A database advisory lock
ensures only one worker owns browser sessions. It processes one action at a time,
rotating between active runs by update time; waiting runs do not require model
calls. The current release is not a parallel model-call pool.

Each run has an isolated Playwright Chromium context. The worker observes visible
text and controls, including frames and popups. A structured OpenClaw model call
chooses one action; an independent call audits every non-wait interaction against
the resume, explicit answers and exact role. Gateway mode uses native RPC on the
interactive lane with gateway tools disabled. Direct API mode uses OpenAI Responses
with strict structured outputs and no API tools. The model gets current element IDs,
not arbitrary selectors, JavaScript, shell, or filesystem tools. Earlier page
identity evidence and recent actions carry forward across form steps.

The fixed tool set supports observed-link navigation, input, native selects,
checkboxes, buttons, resume upload, short waits, asking questions, blocking,
submitting, and verifying. Network requests are restricted to validated public
HTTPS addresses; private addresses, downloads, service workers, and WebSockets
are blocked. These restrictions can make some sites unsupported. No site-specific
ATS API bypass is implemented.

Resume content comes from the category PDF. The worker saves an immutable copy
and checks its hash before actions; it does not generate new qualifications or a
fresh resume. Unknown required facts become questions. Answers are stored for
this application, not automatically promoted to global profile facts. The
controller does not enter passwords, create accounts, buy services, solve
CAPTCHAs, or opt into marketing.

## Pause, failure and uncertain submission

Browser actions are recorded before execution. A submit marker is persisted
before the final click. Once set, the run permits only read-only observation and
confirmation checks. A timeout, process loss, or pause during a potentially
consequential interaction produces `submission_uncertain`, never an automatic
retry. `browser-control --action verify` inspects the original live session and
cannot click or navigate. If that session was lost, inspect the employer portal
manually; the worker cannot safely reset and resubmit it.

New sessions are owned by `possibleos-browser.service`, independently of the
backend. Backend restarts preserve the form, cookies, pages and network guards.
Recovery reconnects without navigation, pauses pre-submit work, and keeps possible
submissions locked. Resume continues the same form; pending questions stay pending.

`browser-control ID --action reconnect --revision N` attaches a stopped run
without filling, navigating, changing workflow status, or submitting.
`browser-status` reports live `browser_session_status` (available, lost,
unreachable, or closed) and `session_available`. An unreachable service does not
prove the browser was lost. `verify` reconnects and remains read-only, including
after an interrupted click without an explicit submit marker.

`release` explicitly closes the browser while keeping answers and history. A
fresh attempt requires guarded `restart`, unavailable after possible submission.
Browser-service restart, Chromium failure or host reboot still loses the live
page. This is process separation, not disk restoration. Legacy in-process
sessions cannot be adopted. Never reopen a listing as proof of submission.

Login/CAPTCHA/manual challenges are surfaced as blockers. The screenshot is
observability, not a remotely controllable desktop. The page link opens the
operator's own browser and does not attach to the worker's session. Universal
Workday support is not claimed; a login-required application may need manual
completion outside the worker.

## UI and deployment

The wider shared modal is available from Job Agent and Leads / Job listings. It
shows website status separately from the existing email workflow, current action,
last update, errors, questions with free-text answers, saved answers, recent events,
and a screenshot. Website runs also appear in the Applications tab.

Install `playwright==1.58.0` and run `.venv/bin/playwright install chromium` as the
backend service user. Browser data lives under ignored `var/job-browser` with
restricted run directories. Tables are added by the existing additive table
initializer. The backend worker starts idle: no application begins on daemon boot.

`JOB_BROWSER_MAX_SESSIONS` (default 3) bounds live contexts, including forms waiting
for an answer. Close an inactive browser to free capacity. `JOB_BROWSER_STEP_BUDGET`
(default 60) bounds actions per resumed segment; reaching it stops with an explicit
error and allows review/resume before further pre-submit work. Repeated actions
without page progress also stop. Neither is a job-queue or event-retention limit.

Validation: `tests/test_job_browser.py` covers action authorization/auditing,
question/revision handling, false confirmations, restart uncertainty, and a real
Chromium fixture that pauses, fills, uploads, submits once and verifies. Set
`JOB_BROWSER_DB_TESTS=1` with the configured database to run the isolated-schema
integration tests. No real employer application is submitted by these tests.


## AI provider selection

Job Agent Settings has a Browser agent AI provider section. The saved fields are
`browser_ai_provider` (`gateway` or `openai`, default `gateway`) and
`browser_openai_model` (default `gpt-5-mini`). Direct API uses the existing server
`OPENAI_API_KEY`, pins the official OpenAI endpoint, sets `store=false`, and returns
only provider/model/usage metadata to the UI. The API key is never returned.
No automatic fallback between providers occurs.

The provider selector is also in each website application panel. Its choice is
used on Start, Resume, Save answer and continue, or Check confirmation only.
Pause an active run before changing its provider. Changing a default alone does
not alter an in-flight run. Resume/answer/verify record an explicitly selected
provider and the configured API model; ordinary CLI resume without `--provider`
retains the run's existing provider/model. Older runs used the gateway.

All three controller modes use the selected provider: next action, action audit,
and confirmation verification. Provider switching never clears submission markers
or authorizes resubmission. API errors, incomplete responses and invalid structured
decisions stop before browser action execution. Response/model/usage metadata are
persisted with the same run checkpoints as gateway metadata.

CLI examples:

```bash
bin/possibleos job-agent browser-provider openai --model gpt-5-mini
bin/possibleos job-agent browser-provider gateway
bin/possibleos job-agent browser-start ID --revision PROCESSING_REVISION --authorize-submit --provider openai
bin/possibleos job-agent browser-control ID --action resume --revision BROWSER_REVISION --provider openai
```

The default affects new website runs; per-run provider overrides apply to that
run. Search, email preparation and Jev classification retain their own existing
providers. API billing is separate from gateway account usage. A configured model
must support Responses structured outputs. The transport follows the
[OpenAI structured outputs documentation](https://developers.openai.com/api/docs/guides/structured-outputs).

## Automatic resume selection

Starting a website application persists authorization immediately and returns `queued`. The worker first matches the job and snapshots its mapped one-page PDF, then opens the employer page. Polling reports the selection stage. Missing PDFs, failed matching, or changed job content stop before browser actions with an actionable error. Resume the same stopped run after fixing the issue. Opening the modal never initiates classification or an application. Bulk classification preferences are unchanged.

## Eligibility mismatches

The browser controller and action audit treat advertised eligibility requirements as advisory. They continue the authorized application with truthful location, sponsorship, authorization and qualification answers. A negative answer or likely rejection is not itself a blocker. Stop for an actual website rejection or restriction, or a mandatory declaration that cannot truthfully be made. Unknown required facts still become questions; login/CAPTCHA and uncertain-submission controls remain. Resuming an older eligibility-blocked run reevaluates it under this policy.

### Reusable applicant profile
Answers to website application questions are saved automatically for contextual reuse. Manage them in the Applicant profile tab or inside the application modal. CLI: `job-agent profile`, `profile-save --file FILE`, `profile-remove ID --revision N`, `profile-import-answers`. `browser-control --action answer` defaults to remembering; `--this-application-only` limits reuse. See [JOB_APPLICANT_PROFILE.md](JOB_APPLICANT_PROFILE.md) for scope, provenance, snapshot and conflict behavior.

### Restart from beginning

The modal offers **Restart from beginning** for stopped runs with no possible or
confirmed submission. A short inline confirmation explains that the browser/form
will be reset while the resume, saved answers and previous activity are retained.
The server returns `can_restart` and `restart_blocked_reason`; the same gate is
enforced by `browser-control --action restart --revision N` (provider optional).
Restart archives the prior private state and run directory, creates a fresh run
ID/browser, clears stale questions/actions/page snapshots, and queues the existing
authorized application. It preserves revision checks and employer identity.
Active runs must pause first. A submit marker, confirmation or unresolved browser
interaction blocks restart. The precise legacy missing-control error is eligible
only when the saved control is absent and no submit marker exists: its local
exception was raised before dispatch. New stale element decisions fail before
writing a possible-interaction marker. No reset can bypass a real uncertain send.

CAPTCHA handling requires visible challenge or website-validation evidence, not a
background iframe URL or an earlier model objection. Observation excludes child
frames hidden by their containing iframe or ancestor frame. Visible embedded form
controls remain available. Unsupported visible challenges still need manual
completion; verification tokens and site checks are never bypassed.

### Recoverable action audits

The structured action audit returns `recovery` (`none`, `correct_form`, or `stop`)
and `repair_hint`. A rejected proposal with `correct_form` before any interaction
or submit marker is recorded as an `audit_repair` event and fed to the next
controller call as `audit_feedback`. The rejected action is not executed and does
not set a submit marker. The UI displays Correcting the form before submission;
existing polling and CLI browser-status/events expose the same state.
Three consecutive rejected correction proposals stop for review; a successful
browser action resets that counter, while all repairs consume the existing
segment step budget. Explicit resume resets the consecutive counter. Hard
rejections, missing facts, website restrictions and actual/uncertain submissions
retain their existing handling. The audit must allow every corrected action.


## Browser service deployment and recovery

Install `deploy/systemd/possibleos-browser.service` and enable/start it before
restarting the backend. It deliberately has no PartOf/BindsTo dependency on the
backend. Update workers with `systemctl restart possibleos-backend`; do not
restart the browser service during live applications. Active-call and in-flight
browser-action deployment checks still apply.

The service listens only on a pre-bound mode-0600 Unix socket at
`var/job-browser/broker.sock`; override JOB_BROWSER_SOCKET identically for both
services. A file lock prevents competing owners. There is no TCP/CDP endpoint,
arbitrary JavaScript tool, or arbitrary file upload. Resume/screenshot paths are
fixed per run. Browser-side public URL/resource/frame restrictions survive worker
detachment, as do disabled WebSockets, downloads and service workers.

Each observation has a fresh token tied to its element handles. Execution consumes
that token once; worker action IDs and broker deduplication prevent replay after a
lost HTTP response. A disk tombstone prevents silent recreation after browser
loss. DB submission markers are written before dispatch and never cleared by
transport errors. The broker enforces the existing session cap across restarts.

Recovery: inspect browser-status, reconnect, then answer a pending question or
resume pre-submit work. Use verify only after uncertain submission. For lost
sessions use a fresh attempt only when the restart guard permits. For unreachable
sessions restore access to the existing service first. Sessions stay open until
explicit release/restart or confirmed completion.


### Quit a website application

`job-agent browser-quit-reasons ID` suggests editable reasons using the run's AI
provider and the job / current question / blocker; it does not save answers or
quit. Suggestions are possibilities, not established applicant facts. Custom
reasons and quitting without a reason remain available if inference fails.
`job-agent browser-control ID --action quit --revision N --reason "Not willing to relocate"`
stops a waiting/paused/blocked pre-submit run as `cancelled` (UI: Quit by you).
The modal offers this beside Save answer and continue, then shows suggested
reasons and an editable optional reason with a confirmation button.
History, the pending-question snapshot and saved answers remain; the reason is
not added to the applicant profile. Browser closure is best-effort and can be
retried with release if unavailable. Worker recovery leaves cancelled runs alone;
resume/answer do not reactivate them. Explicit guarded restart can begin a fresh
attempt. Active runs must pause first; possible/confirmed submissions cannot be
relabelled cancelled. This is local cancellation, not employer-side withdrawal,
and it does not cancel an independent email application or change job review.
