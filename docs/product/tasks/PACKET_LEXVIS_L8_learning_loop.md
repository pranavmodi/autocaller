# PACKET LEXVIS L8 — the learning loop: experiment cards + waves compare

Workdir: `/home/pranav/lexvisibility`. Read first: `app/pipeline.py` (runs
table + checkfirst ALTER pattern), `app/main.py` (admin endpoints from L7),
`frontend/app/admin/` + `frontend/components/AdminEngagementPage.tsx`.

You are Codex. No commit/push/restarts/LLM calls; no live HTTP in tests.

## Why

Each outbound wave is an experiment. The app must hold the lab notebook:
what was tried (the experiment card), what was predicted, and what happened
(the funnel row) — side by side across waves, so learning is visible and
post-hoc storytelling is impossible.

## Scope

### 1. Experiment card (backend)

- `runs` gains (checkfirst ALTER): `experiment_json TEXT` — a card:
  `{wave_id, story_type, subject_style, send_pattern, recipients_planned,
  changed_vs_previous, prediction, predicted_at, notes}`. All strings/ints;
  `wave_id` is operator-assigned (e.g. "wave-1-block", "wave-2-culver").
- CLI: `bin/lexvis run set-experiment <run_id> '<json>'` (merge-patch
  semantics: supplied keys overwrite, others kept) + shown in `run show`.
- Card fields are free-form strings — no enum validation beyond wave_id
  required when the card is set.

### 2. Funnel row (backend)

`GET /api/admin/waves` → one row per run that HAS an experiment card:
- card fields (wave_id, story_type, subject_style, send_pattern,
  changed_vs_previous, prediction);
- funnel numbers computed from report_events (human, non-test only):
  `recipients_planned` (card), `refs_clicked` (distinct human refs seen),
  `opens` (report_viewed count), `deep_reads` (refs with max scroll >= 50 or
  >= 3 sections), `actions` (refs with verify_copied OR pdf_downloaded OR
  booking_clicked), `booking_clicks`, `first_click_at`, `last_activity_at`;
- ordered by first send… the app does not know send times — order by
  run created_at; include run_id, firm_name, report token.

### 3. Waves tab (frontend /admin)

- Add a tab or section "Waves" to the existing /admin page (keep the
  current engagement view as-is):
  - one card per wave, side by side (grid), each showing: wave_id, firm,
    what changed vs previous, **the prediction (verbatim, styled as a
    quote)**, then the funnel: planned → clicked → opened → deep → acted,
    as a compact horizontal mini-funnel with counts;
  - a verdict line under each card: operator judges later — provide an
    editable "outcome note" (PATCH via
    `POST /api/admin/waves/{run_id}/outcome-note` {note} stored in
    experiment_json.outcome_note);
  - waves with zero clicks render honestly (all-zero funnel, not hidden).
- Dense, readable, PT timestamps.

### 4. Tests

- set-experiment merge semantics; waves endpoint computes funnel from
  fixture events (human vs bot vs test refs respected); outcome-note
  persistence; existing suite green; `npm run build` + lint clean.

## Guardrails

- Additive only; do not touch stage logic, QA gate, relay, or bot filter.
- Do NOT `git commit`/`git push`.

## Report

Files changed, waves payload schema, test list, STOP.
