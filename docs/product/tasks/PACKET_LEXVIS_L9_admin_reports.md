# PACKET LEXVIS L9 — /admin reports index (firms + report links)

Workdir: `/home/pranav/lexvisibility`. Read first: `app/main.py` (admin
endpoints), `app/pipeline.py` (runs table, report_token, get_run_detail),
`frontend/app/admin/` + `frontend/components/AdminEngagementPage.tsx`.

You are Codex. No commit/push/restarts/LLM calls; no live HTTP in tests.

## Why
The admin console shows engagement per wave but has no browsable list of the
reports that exist. Operators need one place that lists every run with a
clickable link to its report, appendix, and PDF, plus at-a-glance status and
human engagement counts.

## Scope
1. Backend `GET /api/admin/reports`: one row per run —
   `{run_id, firm_name, firm_domain, status, current_stage, report_token,
   report_url, appendix_url, pdf_url, human_views, refs_clicked,
   pdf_downloads, last_activity_at, created_at, has_experiment_card}`.
   - `report_url` = `<PUBLIC_REPORT_ORIGIN>/r/<token>` (env, default the
     public origin already used elsewhere); appendix `/r/<token>/appendix`;
     pdf `/api/report/<token>/pdf`. Null token -> null urls.
   - engagement counts reuse the existing human/bot/test screening (bots and
     test refs excluded), same logic as the engagement endpoint.
   - order by created_at desc.
   - CLI parity: `bin/lexvis reports` prints the table (firm, status, url,
     views, clicks).
2. Frontend: add a "Reports" tab/section to `/admin` — dense table, firm +
   status + clickable Report/Appendix/PDF links (open new tab) + view/click
   counts + created date (PT). Reuse the existing admin page shell; do not
   disturb the engagement or waves views.

## Guardrails
- Additive only; no changes to pipeline stages, QA/publish behavior, relay,
  or bot filter. Do NOT git commit/push, no restarts.

## Validation
- `pytest -q` green incl. a test: reports endpoint lists runs with correct
  urls (token present vs null), engagement counts screen bots/tests.
- `npm run build` + `npm run lint` clean.
- `bin/lexvis reports` prints rows for existing runs.

## Report
Files changed, endpoint schema, CLI addition, test list, STOP.
