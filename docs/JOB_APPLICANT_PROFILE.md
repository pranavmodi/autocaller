# Reusable applicant answers

Job Agent → Applicant profile stores operator answers independently of individual
website runs. Answers are saved atomically when submitted in an application's
question panel; the default is reuse when context fits. Unchecking Remember limits
reuse to that application. Existing website answers are imported idempotently at
worker startup and via `job-agent profile-import-answers`.

The profile retains the original question/answer, source company/role/location,
answer timestamp, reuse scope, revision and edit history. It does not silently
rewrite a bundled answer into universal facts. The model extracts relevant facts
at use time, preserving the original evidence. Edit answers or add separate facts
through the profile tab or the in-modal profile editor. Removing one disables
future reuse and does not erase historical application evidence or get undone by
legacy imports. There is no fixed item limit on the profile.

## Context skill and reuse

`app/skills/possibleos-job-applicant-context/SKILL.md` is the canonical policy.
Both gateway and direct API receive it in the trusted `answer_policy` payload for
all browser model calls. Current residence, relocation plans, preferred work
location, country-specific authorization and sponsorship stay separate.

Each browser observation loads the current profile. Changes are snapshotted in
that run's private `profile_history`; bulk profile contents do not appear in the
normal browser polling response. Decision and audit calls receive the same facts.
If the model proposes a question, a structured `resolve_question` call checks
saved answers again, cites exact source excerpts, and either answers it or narrows
it to missing/conflicting details. Reused answers include source IDs/revisions
and are not reimported as new independent operator confirmations. Edited/removed
sources invalidate previously derived answers in subsequent model payloads.

The worker cannot guarantee a model never misunderstands a field. Unknown,
conflicting, or materially ambiguous facts still become questions. An already
known fact or permission to perform routine authorized filling should not.

## Interfaces

- `GET /api/job-agent/profile`: all enabled answers.
- `POST /api/job-agent/profile`: add/edit; updates require current `id` and `revision`.
- `POST /api/job-agent/profile/{id}/remove`: revision-bound removal from future reuse.
- `POST /api/job-agent/profile/import-answers`: idempotent historical import.
- `browser/control` accepts `remember` (default true) with answer actions.

CLI:

```bash
bin/possibleos job-agent profile
bin/possibleos job-agent profile-save --file answer.json
bin/possibleos job-agent profile-remove ANSWER_ID --revision REVISION
bin/possibleos job-agent profile-import-answers
bin/possibleos job-agent browser-control JOB_ID --action answer --revision RUN_REVISION --question-id QUESTION_ID --answer-file answer.txt
# Optional: add --this-application-only to keep this answer out of other jobs.
```

A profile JSON file contains `question`, `answer`, `scope`, and `scope_value`.
Scope is contextual (default), global, country, company, role, or application.
Country/company/role/application scopes require a scope_value. Application scope
uses the candidate ID. For an edit, also include `id` and the current `revision`.
Never infer a US sponsorship answer merely from absence of US work authorization.

Validation: isolated database tests in `tests/test_job_browser.py`; opt-in live
model scenarios in `tests/evals/job_applicant_context.py`, which never execute
browser actions or submit forms.
