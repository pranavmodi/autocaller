# PACKET LEXVIS L4 — PDF export + report engagement events

Workdir: `/home/pranav/lexvisibility`. Read first: `app/main.py` (report
endpoint + QA gate), `app/pipeline.py` (artifact versions),
`frontend/components/PublicReportPage.tsx`, `frontend/app/r/[token]/`.

You are Codex. Do NOT commit/push, restart services, or call LLMs.

## Why

The web report stays primary (tracked, interactive). This packet adds:
(1) a "Download as PDF" secondary artifact rendered from the same page, and
(2) a minimal engagement-event log so report opens and PDF downloads become
operator signals (the call-on-open trigger).

## Scope

### 1. Print stylesheet

`@media print` styles for the report page: A4, memo margins (~2cm),
serif headings preserved, each of the 8 sections breaks cleanly
(`break-inside: avoid` on section cards; `break-before: page` for major
sections 3, 5, 7), grid + tables fit page width, sticky CTA footer becomes a
static final block, interactive-only elements hidden (copy buttons, modals'
click affordances render as plain text). Every printed page footer (via
`@page` margin boxes or a repeating element) carries:
"visible.getpossibleminds.com/r/<token> · scan dated <date> · page".

### 2. Backend PDF endpoint

- `GET /api/report/{token}/pdf`:
  - same QA gate as the JSON endpoint (403 pending_qa before approval);
  - renders `PUBLIC_REPORT_ORIGIN` (env, default `http://127.0.0.1:3140`) +
    `/r/<token>?print=1` to PDF via headless Chromium:
    binary path env `CHROMIUM_BIN` default `/snap/bin/chromium`, invoked as
    `--headless=new --no-sandbox --print-to-pdf=<out> --print-to-pdf-no-header <url>`
    with a subprocess timeout (60s). NOTE: snap chromium cannot write to
    /tmp reliably — output under `data/pdf/` (create dir; gitignore it).
  - cache: `data/pdf/<run_id>-v<render_version>.pdf`; regenerate only when
    the current render artifact version changes; serve with
    `application/pdf`, filename `<firm-ref>-ai-visibility-report.pdf`.
  - the subprocess runner must be injectable for tests (no real chromium in
    tests — fake writes a stub file).
- `?print=1` on the report page: skips the not-yet-published interstitial
  ONLY when the report is approved anyway (no gate bypass), applies
  print-friendly rendering synchronously (fetch server-side or wait until
  data loaded — chromium print must not race the client fetch; prefer
  server-side rendering of the page when `print=1`).

### 3. Engagement events (minimal)

- New table `report_events(id, run_id, token, event_type TEXT check in
  ('report_viewed','pdf_downloaded'), source TEXT, created_at)`.
- Record `report_viewed` on each successful `GET /api/report/{token}` and
  `pdf_downloaded` on each successful PDF response (after cache serve too).
- `GET /api/runs/{id}/events` already exists for run audit; add
  `GET /api/runs/{id}/engagement` returning counts + recent rows.
- CLI parity: `bin/lexvis pdf <run_id> [--out <path>]` (drives the same
  renderer, prints output path) and `bin/lexvis engagement <run_id>`.

### 4. Frontend

- "Download PDF" button on the published report page (top-right of the
  cover block, understated), href to the pdf endpoint.
- Rail run page: small engagement summary (views, downloads, last viewed)
  when the run is done.

## Guardrails (hard)

- QA gate must hold for the PDF exactly as for the page (test it).
- No new heavy deps (no puppeteer/playwright); shell out to system chromium.
- Additive only; do not modify stage logic. Do NOT `git commit`/`git push`.
- Tests: no real chromium, no network — inject the renderer.

## Validation (run, report)

- `pytest tests/ -q` green: pdf 403 pre-approval; renderer invoked with
  expected args post-approval; cache hit skips renderer on same render
  version and regenerates on new version; events recorded for view +
  download; engagement endpoint counts.
- `cd frontend && npm run build && npm run lint` clean.
- Do NOT run real chromium against the live run (orchestrator verifies).

## Report (end of run)

Files changed, endpoint paths, cache key scheme, how the print page renders
server-side, test/build output, STOP.
