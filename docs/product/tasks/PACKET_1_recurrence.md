# Packet 1 — Recurrence for existing listening capture

You are the implementer. A separate orchestrator reviews your diff, installs
units, restarts services, and runs expensive jobs. Stay exactly in scope.

## Read first
- /home/pranav/autocaller/docs/product/LISTENING_SYSTEM_IMPLEMENTATION_PLAN.md (Phase 1)
- backend/main.py — only these regions: reddit endpoints (~3595–3800), PILMMA
  research crawl/analyze (~1819–2160), pi-podcasts refresh/transcribe-new
  (~5376, ~6228), startup worker (~602)

## Objective
Make the existing capture recur via systemd timers, and provide a one-off
backlog script. No new Python features; this packet is shell + unit files.

## Tasks
1. Create `deploy/listening/` containing systemd units (curl against
   http://127.0.0.1:8001):
   - `mc-listening-reddit.{service,timer}` — weekly: POST
     /api/research/reddit/crawl, poll /api/research/reddit/crawl-status until
     done, then POST /api/research/reddit/analyze-batch for unanalyzed posts.
   - `mc-listening-pilmma.{service,timer}` — monthly: POST /api/research/crawl
     then POST /api/research/analyze.
   - `mc-listening-podcasts.{service,timer}` — weekly: POST
     /api/pi-podcasts/refresh, then POST /api/pi-podcasts/{id}/transcribe-new
     for each shortlist podcast id.
   - Each service unit runs a script in `deploy/listening/bin/` (bash, jq ok);
     timers use Persistent=true.
2. `deploy/listening/bin/resolve_shortlist.sh` — resolve podcast ids from
   titles (Maximum Lawyer, Personal Injury Mastermind, Trial Lawyer Nation,
   Elawvate, LawDroid Manifesto) via sqlite3 on data/mission.db; write
   `deploy/listening/shortlist.ids`. Fail loudly on a title with no match;
   fuzzy LIKE match is fine.
3. `deploy/listening/bin/backlog_analyze.sh` — loop analyze-batch (batch size
   25, sleep between batches) until `analyzed=0` count reaches 0; print
   progress. DO NOT run it beyond one validation batch.
4. Verify (read the code) that PILMMA `do_crawl` skips already-crawled URLs.
   If it does not, add minimal URL dedup to it — this is the only permitted
   main.py change in this packet.
5. `deploy/listening/install.sh` — copies units to /etc/systemd/system,
   daemon-reload, enables timers. Write it; DO NOT execute it.

## Constraints
- No service restarts; no writes outside the repo; don't touch the
  uncommitted podcast/frontend WIP.
- LLM spend in validation: one analyze-batch of ≤10 posts max.

## Validation (run, include output in final message)
- `bash -n` every script; `systemd-analyze verify deploy/listening/*.service` if available.
- `deploy/listening/bin/resolve_shortlist.sh` resolves exactly 5 ids.
- One analyze-batch of 10: confirm `analyzed=1` count rose by 10 via sqlite3.
- Report the PILMMA dedup finding (already present / patched).

## Done when
Units + scripts exist and validate; shortlist resolves; a 10-post batch
analyzed; install.sh ready for the orchestrator.
