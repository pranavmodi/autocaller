# Fixed 01:00 India daily sync and research schedule

Workdir: /home/pranav/possibleos. Execution owner: existing Possible OS task. Parent is the user-authorized orchestrator and handles deployment/restart. Read AGENTS.md/CLAUDE.md and preserve extensive existing WIP. Parent checkpoint: /tmp/possibleos-nightly-schedule-baseline/{files.tar.gz,baseline.diff,status.txt}.

User: "can do it all in India early AM time, like 1 AM IST ?" This refers to the immediately preceding schedule answer: EmailTag firm sync, autoresponse sync/contact ingestion, Front sync, and daily firm research maintenance (profiles, reviews, job postings, sitemaps). Implement and test fixed 01:00 Asia/Kolkata scheduling, then hand off for parent to activate live. Do not stop at proposal. Parent has said dependent steps run in order.

Current live/source findings:
- app/main.py starts independent front_sync_loop, pif_directory_sync_loop, research_maintenance_loop. Each sleeps86400 after processing, causing drift. Directory begins60sec after startup; maintenance120sec; Front immediately.
- pif_directory loop does sync_firm_intel, sync_autorespond_events, ingest_pif_directory_contacts. Firm sync may queue dirty-profile enrichment.
- research maintenance queues bounded due profiles/reviews/jobs/sitemaps; daily limit175 perkind, refresh30d/priority7d. Worker loops continuously process queue; preserve them.
- front_status sync_health.next_daily_run_at currently reports lastfinished+interval and must reflect new actual schedule.
- Latest live Front error ReadTimeout; do not expand into unrelated repair but failures must not permanently stop other independent nightly stages or advance a duplicate immediate retry.
- Current backend active since Sep10 11:45:38UTC. User wants 1AMIST =19:30UTC prior calendar day. Current Sep11 ~09:20UTC, so next due Sep12 01:00IST (Sep11 19:30UTC).

Scope/behavior:
- Replace interval/startup execution of these daily producers with one fixed daily India schedule. Prefer a small shared scheduler/orchestrated nightly pipeline rather than separately drifting loops. Directory -> autoresponses -> contact ingestion stay ordered; research maintenance starts after sync stages; Front may be independent but bounded and must not prevent maintenance on failure. Retain explicit enable flags and budgets; no additional catchup/backfill on activation.
- Backend restart during day waits until next01:00IST; no immediate expensive nightly run on startup. Prevent overlapping automatic runs and repeat run within same slot; preserve a durable last-run/slot record if necessary using existing settings pattern. Handle stage exceptions without losing following independent work. Include precise status, next_run_at UTC/IST, running and laststage errors via normal API plus CLI.
- Keep implementation minimal and reviewable; existing code architecture should guide details. Do not change unrelated outreach, action scheduler, call dispatcher, career-search timer or other automations. The separate daily PI career search remains on its existing schedule.
- No new external data research or real full sync for testing. No direct DB mutations. Do not touch secrets, provider strategy, sender caps, drafts, or links.
- Update relevant docs/CLI, .env.example as needed, canonical .claude/skills/possibleos/SKILL.md (parent handles external mirror), and focused tests. New feature must be operable/readable through ./bin/possibleos; status must reflect live server rather than only local env. Configuration fixed/default01:00Asia/Kolkata is sufficient; avoid needless settings UI/schema expansion.
- Validate timezone conversion/date rollover, process restart waits, same-slot/overlap prevention, error continuation, existing enable flags, stage ordering, and Front next-run status. Run narrow existing related tests as appropriate, no live mutations/backfills in tests.
- No commits/push, no service restarts, no /etc writes. Parent reviews patch, checks activecalls/research/actions and deploys. No new tasks/subagents necessary.

Deliver /tmp/possibleos-nightly-schedule-handoff.json and shortmd with changedfiles, design,testsresults, required deployment/config, supported CLI/statuscommands, exactnextslot, and limitations. Capture task-specific diff relative to parent baseline if helpful. Send concise progress when design is chosen. Finish bounded code/docs/tests work autonomously.
