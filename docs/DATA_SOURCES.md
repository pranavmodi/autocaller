# Firm data sources — what's what (/firms vs /front vs lead-gen vs mission.db)

Last verified: 2026-06-17. Numbers are approximate and drift.

There are several "lists of firms" in the system and they come from **different
sources for different purposes**. Don't conflate them.

## The canonical source: emailtag PifInfo
emailtag (the email-processing system for Precise, `emailprocessing.mediflow360.com`)
extracts PI-firm records from Precise's inbox into its `PifInfo` table and serves
them at the **pif-info API** (`/api/v1/pif-info`). This is the source of truth for
the firm *directory*: ~3,500 firms, updated continuously by emailtag's Celery
extraction + enrichment. Everything below is either a live view of this, a synced
copy of it, or a different (activity) layer entirely.

## The four firm "lists"

| Surface | What it is | Source | Read path | Size (2026-06-17) |
|---|---|---|---|---|
| **/firms** page | The PI-firm **directory** (identity, profile, ICP, reviews) | **Live emailtag pif-info API** | Browser fetches it **directly** (`frontend/lib/pifstats.ts`, `PIF_BASE`); backend `/api/firms/*` (`firm_reviews.py`) also hits pif-info via httpx for stats/with-reviews. Reviews overlay from local `FirmReviewRow`. | ~3,528 firms |
| **`pif_directory_firms`** (Postgres) | The **synced copy** of emailtag pif-info that **lead-gen** uses | Pulled from the pif-info API by `pif sync` (`app/services/pif_directory.py`), gated by `PIF_DIRECTORY_NATIVE` | Lead-gen matching (`front_sync.resolve_firms`), selection, and the composer read this (as-of-last-sync, not live) | ~3,505 firms |
| **/front** page | Front-inbox **activity / warmth** (engagement, referrals, recency) | possibleos Postgres `front_firm_activity` + `firm_contacts`, populated by `front_sync` pulling Precise's Front inbox (Front API) | `/api/front/*` (`app/api/front.py`) → `front_sync` | ~7,146 domains seen; ~1,727 matched to a PI firm; ~2,186 warm (score>0) |
| **mission.db** | Legacy Mission Control SQLite cache | A separate app (Mission Control) | possibleos no longer uses it for matching (replaced by `pif_directory_firms`). Still read **only** by the competitor-graph rebuild (raw `front_messages`/`front_conversations` text + `pif_firms`), and as the matching **fallback** when `PIF_DIRECTORY_NATIVE=0` | frozen ~1,711 (stale since Mar 2026) |

## The /firms vs /front distinction (the one people confuse)
- **/firms = identity / directory.** "Who are all the PI firms?" The full target
  universe from emailtag, **including firms with no recent Front activity**.
  Live. Used for profile, ICP tier, reviews, research.
- **/front = behavior / engagement.** "Which firms are *active in Precise's
  inbox right now*, and how warm?" Built from who actually emails through Precise.
  Its domains include many **non-PI-firm senders** (vendors, individuals); only
  the **matched** subset are known PI firms, warm-scored by recency/volume/
  referrals.

So:
- In **/firms but not /front** → a known PI firm with no recent Precise inbox traffic.
- In **/front but not /firms** → an inbox sender that isn't a matched PI firm.
- **Overlap** (~1,727 matched) → PI firms that both exist in the directory *and*
  are active in Precise's inbox = the warm, highest-signal leads. Lead-gen uses
  /firms-style identity to know the universe and /front-style warmth to prioritize.

## Gotchas / consistency notes
- **/firms is live; lead-gen is a synced copy.** If emailtag adds firms between
  `pif sync` runs, /firms shows them before lead-gen can target them.
- **`resolve_firms` matches Front domains against `pif_directory_firms`** when
  `PIF_DIRECTORY_NATIVE=1`. Widening the native directory (3,528 vs mission.db's
  1,711) is why /front's matched count rose from ~1,141 to ~1,727.
- **/firms calls emailtag directly from the browser**, so it needs that API
  reachable/CORS-open from the client (reads are currently unauthenticated).
- mission.db is **not** on the daily path anymore — only the competitor-graph
  rebuild needs it (for raw Front message text, which possibleos has no native
  copy of). See `docs/LEAD_GEN_CYBERNETIC_TECHNICAL.md` for the native-directory
  details.
