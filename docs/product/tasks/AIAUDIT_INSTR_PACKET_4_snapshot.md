# PACKET — AIAudit instrumentation 4: daily funnel snapshot

Workdir `/home/pranav/AIAudit`. Build on commit `a622740` (Layers 0/1/2 done:
`funnel_stats(day)` exists in `app/db.py`; `aiaudit funnel` in `bin/aiaudit`).
Touch only `app/db.py`, `bin/aiaudit`, `deploy/`, `tests/`.

## Goal
Persist a daily snapshot of the funnel so we get a historical trend (engagement
over time), not just a point-in-time read. A daily job captures the *previous*
UTC day's `funnel_stats`; snapshots are idempotent (re-runnable per day).

## Scope
1. **`funnel_snapshots` table** (`app/db.py` `_init_db_sync` + ALTER-safe
   migration like `_migrate_event_columns`):
   ```
   funnel_snapshots(
     day TEXT PRIMARY KEY, captured_at TEXT NOT NULL,
     raw_opens INTEGER, human_opens INTEGER, bot_opens INTEGER,
     real_sessions INTEGER, first_answer INTEGER, submitted INTEGER,
     completed INTEGER, median_ttfi_ms INTEGER,
     pct_bounced_lt3s_no_scroll REAL, full_json TEXT NOT NULL
   )
   ```
2. **`snapshot_funnel(day)` in `app/db.py`** — call `funnel_stats(day)`, extract
   the key scalars (pull from `event_funnel[...]['count']` etc.), `INSERT ... ON
   CONFLICT(day) DO UPDATE` (idempotent), store the full stats dict in
   `full_json`. Return the row. Add `list_funnel_snapshots(limit=14)`.
3. **`bin/aiaudit snapshot [--day YYYY-MM-DD]`** — default day = **yesterday
   (UTC)**; persist via `snapshot_funnel`; print the saved row. Support `--day`
   for manual capture/backfill.
4. **`bin/aiaudit snapshots [--limit N]`** — print recent snapshots as a trend
   table (day, real_sessions, first_answer, submitted, median_ttfi).
5. **Deploy units in `deploy/`** (write the files only — DO NOT install/enable):
   - `aiaudit-funnel-snapshot.service` — `Type=oneshot`, ExecStart runs
     `/home/pranav/AIAudit/bin/aiaudit snapshot`, same env as `aiaudit.service`
     (set `AIAUDIT_DB_PATH` if that unit does).
   - `aiaudit-funnel-snapshot.timer` — daily at ~00:10 UTC, `Persistent=true`.

## Guardrails
- **Do NOT install/enable systemd units or restart services** — orchestrator
  does that. Just write the unit files to `deploy/`.
- No `/etc` writes, no `pip install`. Temp port 18011 only if needed; delete any
  TEST rows. Keep `funnel_stats` output back-compatible.

## Validation (paste output)
- `python3 -m pytest tests/ -q` — all pass.
- `tests/test_snapshot.py`: seed a couple `audit_events` for a fixed day, run
  `snapshot_funnel(day)` twice, assert the row exists once (idempotent upsert)
  and the scalars match `funnel_stats(day)`.
- `bin/aiaudit snapshot --day <day-with-seeded-events>` then
  `bin/aiaudit snapshots` both run and print.
- `systemd-analyze verify deploy/aiaudit-funnel-snapshot.{service,timer}` is
  clean (or note it can't run without install — at minimum the unit files are
  syntactically valid).

## Finish
Report diff + validation. Do NOT commit, do NOT install the timer, do NOT
restart services.
