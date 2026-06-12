# Packet 16 — Competitor graph: firm search + interactive graph visualization

You are the implementer in /home/pranav/autocaller. Packet 15 (deployed)
built firm_competitive_features + competitor_edges (5,858 edges live),
GET /api/front/competitors[?domain|pif_id], /summary, POST /rebuild, and
"Competes with" lists in /front warm-list rows. Now make the graph
explorable: search ANY firm (not just warm-list rows) and render its
competitive neighborhood visually.

## Read first
- app/services/competitor_graph.py (edge/feature shapes, get_competitors)
- app/api/front.py (router conventions), frontend/app/front/page.tsx,
  frontend/lib/api.ts
- frontend/package.json (current deps)

## Tasks

### 1. API
- `GET /api/front/competitors/search?q=&limit=10` — case-insensitive
  substring match on firm_name and domain over firm_competitive_features;
  return pif_id, firm_name, domain, metro, value_tier, edge_count, and
  whether it's on the warm list. Empty/too-short q (<2 chars) → 400.
- `GET /api/front/competitors/graph?pif_id=&depth=1` — ego-network payload
  for the viz: `{nodes:[{pif_id, firm_name, domain, metro, value_tier,
  volume_proxy, is_center}], links:[{source, target, score, components,
  evidence_summary}]}`. depth=1: center + its neighbors + ALL edges among
  that node set (neighbor↔neighbor edges included — that's what makes it a
  graph, not a star). depth=2 (cap: 60 nodes, keep highest-score nodes)
  optional param. 404 for unknown pif_id.

### 2. /front UI
- **Search box** at the top of the competitor/signals area: type-ahead
  (debounced 300ms) against the search endpoint, works for ANY firm with
  features — not just warm-list rows. Selecting a result opens the graph
  panel for that firm.
- **Graph panel** (also openable from each warm-list row's "Competes with"
  section via a "view graph" link): force-directed SVG rendering of the
  ego network.
  - Use `d3-force` ONLY (small, tree-shakeable — add as dependency; do NOT
    add react-force-graph/cytoscape/vis.js or anything canvas/WebGL).
    Run the simulation in a useEffect, render plain SVG circles/lines.
  - Node: circle sized by volume_proxy (sqrt scale, clamp 6–22px), colored
    by metro (stable palette + legend), center firm highlighted (ring).
    Label = firm name (truncate ~22 chars).
  - Edge: line width/opacity by score; hover → tooltip with score,
    components, evidence one-liner.
  - Click a non-center node → re-fetch graph centered on it (breadcrumb
    trail of visited firms, click to go back).
  - Depth toggle (1 hop / 2 hops). Loading + empty states ("no competitor
    data for this firm").
- Keep the existing warm-list "Competes with" lists working unchanged.

### 3. CLI (golden rule)
- `front competitors search <q>` → table of matches (same endpoint).
- `front competitors graph <domain-or-name> [--depth 1] [--json]` → prints
  nodes/links counts + top edges table; --json emits the raw payload (for
  scripts/agents).
- docs/cli.md: §3 rows + §10 recipe ("explore a firm's competitive
  neighborhood"); §11 note that the in-browser force-directed rendering is
  UI-only (the data behind it is fully available via
  `front competitors graph --json`).
- Update .claude/skills/autocaller/SKILL.md with the new commands
  (orchestrator syncs the openclaw copy — do not write outside the repo).

### 4. Tests
- API: search matching (name + domain substring, short-q 400), graph
  payload (neighbor↔neighbor links present, depth-2 node cap, 404).
- Seed fixtures directly via ORM rows; do NOT read MC sqlite in tests.
- `npm --prefix frontend run build` must pass.

## Constraints
- ZERO Front API calls, zero LLM/gateway calls.
- NO commits, NO daemon restarts. Do NOT touch master-agent WIP files
  (app/services/master_agent*.py, frontend/app/agents/,
  tests/test_master_agent_runner.py) or frontend/app/ideas/.
- Only new dependency allowed: d3-force (+ its types). Nothing else.
- A live scheduled email action fires 16:30 UTC — do not touch
  agent_actions or the scheduler.
- Backend may be serving live syncs — read-only queries against the
  competitor tables only.

## Validation (include output)
- pytest: new tests green, full suite not broken.
- npm build passes.
- curl the search + graph endpoints against the live daemon with a real
  firm (e.g. wilshirelawfirm.com → its pif_id) and show abbreviated JSON
  (node/link counts, 3 sample links with scores).
- `bin/autocaller front competitors graph wilshirelawfirm.com` prints
  sensible output; `--json | python3 -m json.tool | head` works.

## Done when
Any firm is findable via search; selecting it renders an interactive
force-directed ego graph with evidence tooltips, click-to-recenter, and
depth toggle; CLI/API/docs/SKILL complete; tests green.
