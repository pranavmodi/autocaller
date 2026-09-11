# Fixed Nightly Sync

## Schedule And Order

The backend starts one automatic pipeline at **01:00 Asia/Kolkata**, equal to
**19:30 UTC on the preceding calendar day**. For example, September 12, 2026
01:00 IST is September 11, 2026 19:30 UTC. The host timezone does not matter.

1. EmailTag firm extraction delta (`sync_firm_intel`, native directory flag).
2. EmailTag autoresponse delta (`sync_autorespond_events`, same flag).
3. Local contact ingestion (`ingest_pif_directory_contacts`, same flag).
4. Front incremental sync (`run_front_sync`, `full=False`, existing call budget).
5. Due profile, review, job-posting and sitemap maintenance (existing maintenance flag/budgets).

The order is the order of attempts: a failed upstream stage leaves its persisted
watermark/data intact according to that service's existing behavior. Later
independent stages can use already-stored data and are still attempted. Front
failure/timeout is also written to Front's existing last-run error status.
Partial per-firm failures returned by ingestion/maintenance are visible as
partial stages rather than silently reported as success.

The pipeline queues maintenance, not all-firm full research. Existing freshness,
per-kind daily caps (default 175), priority windows (7/30 days), and worker
concurrency are unchanged. Existing budget accounting uses UTC calendar days;
the 01:00 IST slot therefore counts against the preceding UTC date. Firm delta
sync may itself enqueue due local enrichment, and continuous workers can begin
that work while later sync stages run. Research completion may extend into the
day. Career search, outbound/action schedulers and call dispatch are untouched.

## Restart And Failure Policy

- Backend startup always waits for the strictly next slot. Starting at exactly
  01:00 IST also waits until tomorrow; there is no startup catchup/backfill.
- A PostgreSQL session advisory lock prevents concurrent automatic pipelines.
  The slot is checkpointed before side effects in the existing singleton
  `system_settings.agent_config.nightly_sync` key. Atomic JSON-key updates avoid
  replacing other agents' settings. No new tables or migration are required.
- A claimed slot is never retried automatically, including failure or process
  interruption. The next attempt is the following night. Existing per-service
  retries and research-worker retries remain unchanged.
- Each stage has a cooperative asyncio timeout (default 1800 seconds). Timeout
  cancels that stage and attempts the next. A database checkpoint failure stops
  the pipeline: it cannot safely continue without recording execution.
- A process suspended more than five minutes past its pending slot skips that
  slot instead of catching up unexpectedly. Clock checks happen at most 60
  seconds apart; work duration never shifts the next scheduled time.
- Status reads the durable latest checkpoint plus the database lock, so a
  leftover `running` checkpoint without its lock is reported as `interrupted`.
  Only the latest run is retained here; underlying service/task histories remain.
- Manual sync and maintenance commands remain available and are outside this
  automatic pipeline lock. Operators should avoid running them during a nightly
  pipeline. No new automatic full refresh or backfill is introduced.

## Configuration And Status

| Environment | Default | Purpose |
| --- | --- | --- |
| `POSSIBLEOS_NIGHTLY_SYNC_ENABLED` | `true` | Enable this automatic pipeline |
| `PIF_DIRECTORY_NATIVE` | `0` | Enable firm/autoresponse/contact stages |
| `FRONT_SYNC_ENABLED` | `true` | Enable automatic Front stage |
| `PIF_RESEARCH_MAINTENANCE_ENABLED` | `true` | Enable due research producer |
| `POSSIBLEOS_NIGHTLY_STAGE_TIMEOUT_SECONDS` | `1800` | Maximum wait per stage |
| `FRONT_SYNC_MAX_CALLS` | `300` | Existing Front API call budget |
| `PIF_RESEARCH_MAINTENANCE_DAILY_LIMIT` | `175` | Existing per-kind daily cap |

The old `FRONT_SYNC_INTERVAL_SECONDS`,
`PIF_RESEARCH_MAINTENANCE_INTERVAL_SECONDS` and
`PIF_RESEARCH_MAINTENANCE_STARTUP_DELAY_SECONDS` no longer control these producers.
Configuration is server-side environment; the CLI reads the running backend.

```bash
./bin/possibleos pif nightly-status
./bin/possibleos pif sync-status
./bin/possibleos pif maintenance-status
./bin/possibleos front status
```

`GET /api/pif/nightly-sync/status` returns `scheduler_active`, `enabled`,
`next_run_at` (UTC), `next_run_at_ist`, `stages_enabled`, budgets, `running`, and
`last_run` including `slot`, `current_stage`, `stages`, timestamps and `errors`.
`last_error` at the top is a scheduler-level failure/missed-slot diagnostic.
An inactive/disabled scheduler exposes no next run. Front's
`sync_health.next_daily_run_at` reflects this pipeline's next slot, not its
last-finished timestamp; Front itself starts after the preceding stages finish.

## Deployment

The parent/operator reviews the patch and checks active calls, research and
actions before deploying/restarting the backend. There are no migrations,
systemd units, frontend build or prompt-version changes for this feature.
Preserve the existing native-directory/maintenance flags and budgets; set the
master flag false for a staged but disabled deployment if needed. Parent mirrors
the canonical `.claude/skills/possibleos/SKILL.md` to the external skills path.

After restart, verify `pif nightly-status` shows active scheduler and the next
01:00 IST slot with no immediate run. This document describes implementation,
not confirmation that a deployment has been activated. The implementer performs
no live sync, research queueing, DB mutation or service restart for validation.

## Validation

```bash
.venv/bin/pytest -q tests/test_nightly_sync.py tests/test_pif_research_maintenance.py tests/test_front_sync.py tests/test_pif_directory.py tests/test_cli_pif_job_postings.py
```

All external stages and database operations are mocked in scheduler tests.
