# Packet 5 — Proactive layer: watchdog, alert rules, proposed sources

You are the implementer, in mission control. Depends on Packet 2A. (The
master-agent listening goal — plan task 5.4 — is intentionally NOT in this
packet; that code is in flux and the orchestrator owns it.)

## Read first
- /home/pranav/autocaller/docs/product/LISTENING_SYSTEM_IMPLEMENTATION_PLAN.md (Phase 5 + Proactivity model)
- backend/listening.py

## Objective
The system announces its own failures and flags time-sensitive signal
immediately instead of waiting for the weekly digest.

## Tasks
1. `GET /api/listening/health` — per source: last_polled_at vs
   `expected_cadence_days` (add column if Packet 3 didn't), items/insights in
   last cycle, last_error. Overall status ok|degraded.
2. Alert rules: `listening_alert_rules` table (id, kind, params_json, enabled)
   with four built-in seeded rules:
   - `leader_topic` — item author matches a tracked person AND text matches
     wedge topics (intake, after-hours, AI adoption — params_json)
   - `cluster_spike` — a cluster's weekly insight count ≥2× its trailing
     4-week mean (min 3)
   - `name_mention` — item mentions Possible Minds, Precise Imaging, or
     params-listed competitors
   - `new_voice` — ≥3 insights from an author with no listening_sources row →
     also INSERT a proposed source (enabled=0)
3. `listening_alerts` table (rule_id, item_id/insight_id, payload_json with
   quote+link+suggested_action, status new|seen|dismissed, created_at) +
   `GET /api/listening/alerts?status=`, `POST /api/listening/alerts/{id}/status`.
4. Evaluate rules at the end of every extract batch (hook in listening.py) and
   from `GET /api/listening/health` runs.
5. `deploy/listening/bin/health_daily.sh` + `mc-listening-health.{service,timer}`
   (daily): GET health; on degraded or new alerts, deliver via the same
   digest-delivery mechanism Packet 3 used (email or data/digests/ + TODO line).
6. Surface alerts + proposed sources (with enable button → PATCH source
   enabled=1) on the /listening page if it exists; else endpoints only.

## Constraints
- No restarts; temp uvicorn 18001; TEST rows cleaned; no LLM calls needed
  (rules are deterministic — keep them so).

## Validation (include output)
- Seed a TEST item by a tracked leader containing "intake" → leader_topic
  alert with quote + link.
- Fabricate 3 TEST insights by an unknown author → new_voice alert + proposed
  source row (enabled=0).
- Set a source's last_polled_at 30 days back → health degraded + daily script
  reports it; restore value after.
- All TEST artifacts removed.

## Done when
Health, rules, alerts endpoints proven via the seeded scenarios; daily unit
written; nothing left enabled=1 that wasn't before.
