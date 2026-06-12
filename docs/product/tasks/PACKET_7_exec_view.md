# Packet 7 — Executive view with drill-down

You are the implementer in /root/.openclaw/workspace/mission-control. Goal: a
30-second executive read at the top of /listening, where every element drills
down into the detail section that explains it.

## Read first
- backend/listening.py: digest endpoint, brief storage (stats_json holds
  cluster counts used for trend deltas), health endpoint, alerts endpoints
- frontend/src/app/listening/page.tsx — note the CollapsibleSection component
  (packet 6): sections are keyed and persist open state in localStorage

## Tasks
1. **Backend** `GET /api/listening/exec` — plain SQL + existing brief
   stats_json aggregation, NO LLM call. Returns:
   - `headline`: items and unique insights added in the last 7 days, current
     brief version + created_at
   - `movers`: top 3 clusters by delta from the latest brief's stats vs the
     previous brief (name, current weighted count, delta)
   - `quotes`: 3 most recent high-confidence insights (confidence >= 0.7,
     prefer is_primary items, distinct clusters), each with quote, author,
     source name, url, insight id, cluster
   - `decisions`: counts of pending alerts by rule kind + proposed sources
     awaiting enable
   - `health`: ok|degraded + one human-readable line
2. **Frontend**: an "Executive view" card rendered at the very top of
   /listening (above the stat cards; always visible, not collapsible):
   - What changed: headline numbers in one sentence
   - Rising: the 3 movers as clickable chips ("medical-records-workflow +9")
   - Voice of the market: the 3 quotes with author/source attribution
   - Needs your decision: "N alerts, M proposed sources" as buttons
   - One health line (green/amber dot)
3. **Drill-down wiring**:
   - Mover chip click → expand the Insights section, set its cluster filter
     to that cluster (add a cluster filter to the insights loader if missing
     — the API already supports ?cluster=), scroll to it
   - Quote click → open its source url in a new tab (fallback: expand Items)
   - Decisions button → expand Health & Alerts section, scroll to it
   - Health line click → expand the sources section
   - Implement by lifting section open-state or via a small event/callback
     from the exec card to the CollapsibleSection states; also support URL
     query params (?section=insights&cluster=...) applied on load.

## Constraints
- No LLM calls anywhere in this packet.
- Backend additions go in backend/listening.py (preserve the try/except
  import pattern note: service runs `python3 main.py` from backend/).
- Validate backend on temp uvicorn :18001 ONLY (kill it after; if PID is
  hidden use `fuser -k 18001/tcp`); frontend via `npm --prefix frontend run
  build` only — do not restart live services.
- An extraction backfill is writing to the DB concurrently; keep
  busy_timeout=15000 on any new connections.

## Validation (include output)
- curl the exec endpoint on :18001 — show the JSON with real data (movers
  non-empty given briefs v1/v2 exist; quotes non-empty).
- `npm --prefix frontend run build` passes.
- Describe the drill-down wiring (which click expands what).

## Done when
Exec endpoint returns real aggregates; the card renders at top; every exec
element drills into its detail section.
