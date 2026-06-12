# Packet 15 — Competitor graph: which PI firms compete with each other

You are the implementer in /home/pranav/autocaller. Build a firm-vs-firm
competition graph from data already on disk. PI competition is local: two
firms compete when they overlap on metro, case mix, and case-value tier.
ZERO Front API calls — everything derives from local tables.

## Read first
- app/services/front_sync.py (resolve_firms shows how we read MC sqlite
  read-only + match domains to pif_firms; front_firm_activity shape)
- app/api/front.py + frontend/app/front/page.tsx (where the panel goes)
- MC sqlite (read-only, busy_timeout):
  /root/.openclaw/workspace/mission-control/data/mission.db
  - pif_firms: 1,711 rows; addresses TEXT json array (1,260 firms have at
    least one "street, City, ST 90210" string); research_data TEXT json
    (websites, attorney-profile sources, sometimes practice info);
    icp_score/icp_tier/score_breakdown
  - front_conversations / front_messages (107,912 bodies: lien-negotiation
    threads — subjects + bodies contain case types and dollar amounts)
  - lien_firm_stats — inspect it; if it already aggregates per-firm amounts,
    use it instead of re-deriving
- app/db/models.py + alembic conventions (additive only)

## Design

### 1. Schema (alembic, additive — autocaller postgres)
```
firm_competitive_features (
  pif_id varchar PK, firm_name varchar, domain varchar NULL,
  metro varchar NULL,            -- e.g. "los-angeles", "sf-bay", "state:TX"
  city varchar NULL, state varchar NULL,
  case_mix jsonb,                -- {"mva": 0.62, "premises": 0.2, ...}
  value_tier varchar NULL,       -- "small" | "mid" | "large" (amount median)
  volume_proxy int NULL,         -- conversation count in cache
  evidence jsonb,                -- sample subjects / amounts behind the tiers
  computed_at timestamptz
)
competitor_edges (
  id varchar PK, firm_a_pif_id varchar, firm_b_pif_id varchar,
  metro varchar, score float,
  components jsonb,              -- {"geo":1.0,"case_mix":0.8,"value_tier":1.0,"shared_orbit":0.5}
  evidence jsonb,                -- short human-readable why
  computed_at timestamptz,
  UNIQUE (firm_a_pif_id, firm_b_pif_id)   -- store each pair once, a < b
)
```

### 2. Feature extraction (app/services/competitor_graph.py)
- **Metro**: parse city+state+zip from pif_firms.addresses strings
  (deterministic regex on the well-formed "City, CA 90210" tail; use the
  FIRST address). Map to metro with an embedded static table: CA cities →
  {los-angeles, orange-county, inland-empire, san-diego, sf-bay, sacramento,
  central-valley, central-coast} (cover at least the ~80 most common CA
  cities in the data — query distinct cities first and cover what's actually
  there); any unmapped or non-CA → "state:XX" fallback metro. Firms with no
  address: metro NULL (excluded from edges).
- **Case mix**: deterministic keyword tagging over that firm's cached
  conversation subjects+bodies (match via the firm's emails/domains against
  front_messages.author_email and conversation participants — reuse the
  matching approach from resolve_firms). Categories: mva, premises,
  dog_bite, med_mal, workers_comp, other. Normalize to a distribution.
  NOTE: deterministic-by-design for v1 (the LLM gateway is a constrained
  resource right now); structure the tagger as a swappable function and say
  so in the docstring.
- **Value tier**: dollar amounts from the firm's threads ($X,XXX regex,
  ignore < $100) or lien_firm_stats if usable → median → small (<$5k), mid
  ($5k–$25k), large (>$25k). These are lien/bill amounts, not settlements —
  name the field honestly in evidence.
- **Volume proxy**: count of cached conversations matched to the firm.
- **Client-switching probe**: scan bodies for substitution-of-attorney
  language ("substitution of attorney", "no longer represents", "case has
  been transferred to", "new counsel"). Where two known firms appear, store
  a high-weight directional evidence entry on that pair's edge. Report how
  many you found in validation output (expected: few; zero is acceptable).

### 3. Edge computation
Within each metro, for firms with features: score pairs as
`geo (1.0 same metro, 0.4 adjacent CA metros — embed a small adjacency map)
× weighted sum of case-mix cosine, value-tier proximity (same=1, adjacent
tier=0.5), shared_orbit (both have front_firm_activity rows = 0.5 bonus,
both active in last 90d = 1.0)`. Normalize to 0–1. Keep only top-10 edges
per firm above a floor (0.3). Cap total pairwise work: metros with >200
firms — bucket by value tier first to avoid O(n²) blowup.
Rebuild is idempotent: wipe + recompute both tables in one transaction.

### 4. API + UI
- `POST /api/front/competitors/rebuild` (runs extraction + edges; returns
  counts + duration; it's CPU/SQLite work, run via asyncio.to_thread or
  executor so the event loop stays responsive)
- `GET /api/front/competitors?domain=|pif_id=&limit=10` → firm's neighbors
  with scores, components, evidence
- `GET /api/front/competitors/summary` → metro counts, edge counts, tier
  distribution, last computed_at
- /front page: in each warm-list expanded row, a "Competes with" list
  (name, score, one-line why) via the GET endpoint; plus a small
  "Competitor graph" stat chip in the signals panel (firms with features /
  edges / last rebuild).

### 5. CLI (golden rule)
`front competitors rebuild`, `front competitors show <domain-or-name>`,
`front competitors summary`. docs/cli.md §3 rows + §10 recipe ("who
competes with firm X"); update .claude/skills/autocaller/SKILL.md
(orchestrator syncs the openclaw copy).

### 6. Tests
Address→city/state/metro parsing (real-shaped fixtures incl. multi-address
and missing-zip), case-mix tagging + cosine, value-tier bucketing, edge
score math + top-K + a<b uniqueness, API smoke (rebuild on seeded fixture
data, then GET). Mock/seed everything; tests must not read MC sqlite.

## Constraints
- ZERO Front API calls. MC sqlite strictly read-only (busy_timeout 5000).
- No LLM/gateway calls anywhere in this packet.
- NO commits, NO daemon restarts. Do NOT touch master-agent WIP files
  (app/services/master_agent*.py, frontend/app/agents/, tests/
  test_master_agent_runner.py).
- Additive migrations only. No new deps.
- A live scheduled email action fires 16:30 UTC (Gary Guillen retry) — do
  not touch agent_actions or the scheduler.
- Front sync daemon loop may be running — your work must not lock its
  tables (keep the rebuild transaction short or batched).

## Validation (include output)
- pytest: new tests green; full suite not broken.
- `npm --prefix frontend run build` passes.
- Run the real rebuild once against live data via the service function
  (not the API): report firms-with-metro count, firms-with-case-mix count,
  edge count, top-3 edges by score with their evidence, and the
  client-switching hit count.
- `front competitors show` for one well-known firm (e.g. a top warm-list
  domain) prints sensible neighbors.

## Done when
Rebuild produces a populated graph from live local data; /front shows
"Competes with" per warm-list firm; CLI/API/docs/SKILL complete; tests
green.
