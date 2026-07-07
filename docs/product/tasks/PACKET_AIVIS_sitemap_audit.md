# PACKET AIVIS — sitemap-aware website audit (deeper, precise site read)

Workdir: `/home/pranav/ai-visibility`. Read first: `app/services/website_analyzer.py`
(the whole file — you extend it), `app/services/scoring.py` (consumes
`website_signals_json`), `app/db.py` (scan schema), `docs/cli.md` §website,
and the repo `CLAUDE.md` (CLI parity is a golden rule).

You are Codex. No commit/push/service restarts/deploys. Build + unit-test
(mock all HTTP — no live web fetches in tests).

## Why

Today the analyzer fetches the homepage and discovers internal pages only by
parsing homepage anchor links, capped at 6 pages total
(`FIRM_PAGE_LIMIT = 6`, `_rank_internal_links`). It never reads sitemap.xml.
Result: recommendations are shallow and miss whether a firm already has (or
lacks) a dedicated market landing page, and whether pages carry
machine-readable schema. We need a thorough, repeatable per-firm site read so
every scan's recommendations are precise (the Block LLP report got this by
hand; make it a tool capability).

## Scope (all additive; do not remove or rename existing signal keys)

### 1. Sitemap-aware page discovery

- New helper `_discover_sitemap_urls(client, base_url, robots)`:
  - fetch `/robots.txt` (reuse `_robots_parser`) and honor any `Sitemap:`
    lines; else try `/sitemap.xml` and `/sitemap_index.xml`.
  - follow ONE level of sitemap-index nesting (index → child sitemaps →
    urls). Cap total sitemap files fetched (e.g. 8) and total URLs parsed
    (e.g. 500). Handle Yoast-style `<sitemapindex>`/`<urlset>`; be tolerant
    of missing/invalid XML (return []).
  - respect robots `can_fetch` per URL; skip disallowed.
- Rank discovered URLs by relevance to this scan using the existing
  `RELEVANT_URL_TERMS` + market city slug (reuse the scoring logic in
  `_rank_internal_links`; factor a shared scorer so ranking is identical for
  sitemap URLs and anchor URLs). Prefer: market/city pages, core practice
  pages (car/truck/motorcycle/wrongful-death/etc.), attorney/about, reviews,
  FAQ, contact.
- **Page budget:** new setting `SITEMAP_PAGE_LIMIT` (default 18) used when a
  sitemap is found; fall back to the existing homepage-anchor discovery +
  `FIRM_PAGE_LIMIT` when no sitemap exists. Always include the homepage.
  Make the deep budget overridable via env (`AIVIS_SITE_PAGE_LIMIT`).
- Per-request politeness: keep `REQUEST_TIMEOUT_S`; add a small delay between
  page fetches (e.g. 0.3s) and cap total wall time defensively.

### 2. Schema / machine-readability detection (per page)

- Extend `_analyze_page` (additive): parse `<script type="application/ld+json">`
  blocks; record the set of schema `@type` values found (LegalService,
  Attorney, FAQPage, Review, BreadcrumbList, Organization, LocalBusiness,
  WebSite, etc.), tolerant of `@graph` arrays and parse errors. Add
  `schema_signals: {jsonld_present: bool, types: [..]}` to the page.

### 3. New `site_read` summary block (top-level in website_signals)

Add `site_read` to the returned signals dict (leave all existing keys intact):
```
site_read: {
  sitemap_found: bool,
  sitemap_urls_total: int,          # URLs seen in sitemap(s)
  pages_fetched: int,
  market_pages: [urls],             # dedicated city/market landing pages found
  has_market_landing_page: bool,    # any page clearly targeting scan market city
  practice_pages: [urls],           # core accident practice pages present
  practice_coverage: {car:bool, truck:bool, motorcycle:bool, pedestrian:bool,
                      wrongful_death:bool, ...},  # from URL/anchor slugs
  schema_types_seen: [..],          # union across fetched pages
  schema_coverage: {jsonld_pages: int, has_legalservice:bool,
                    has_attorney:bool, has_faqpage:bool, has_review:bool,
                    has_breadcrumb:bool},
  faq_page_present: bool,
  faq_has_schema: bool,             # FAQ page exists but lacks FAQPage JSON-LD => strong reco
  badges_without_links: bool        # proof badges (Avvo/SuperLawyers/Justia/Expertise) shown as images with no outbound profile link
}
```
- `badges_without_links`: detect known directory brand names appearing on a
  page as image/text but WITHOUT an outbound `<a href>` to that directory's
  domain — the "badges are weak evidence, link the profiles" finding.

### 4. Recommendations use it

In the recommendations builder (see `recommendations`/scoring path that reads
`website_signals`), when `site_read` is present, prefer specific,
site-grounded recos over the generic ones:
- no `has_market_landing_page` → "Build the <City> hub" (note existing
  practice pages so it reads as 'package what you have', not 'rebuild').
- `faq_page_present and not faq_has_schema` → "Add FAQPage schema to the
  existing FAQ page".
- missing schema types → "Add LegalService/Attorney/Review/breadcrumb JSON-LD
  on priority pages".
- `badges_without_links` → "Turn badges into linked citation proof".
Keep these evidence-backed (cite the fetched URLs). Do not fabricate; if
`site_read` absent (dry-run / no fetch), fall back to current behavior.

### 5. CLI + docs (golden rule)

- `bin/aivis website <scan_id>` gains `--deep/--no-deep` (default `--deep`:
  use sitemap discovery; `--no-deep` forces the legacy 6-page anchor mode)
  and `--max-pages N`. Print a short site-read summary
  (sitemap found?, pages fetched, market page?, schema coverage, badges).
- Update `docs/cli.md` §website row + add a one-line recipe.
- `--dry-run` still makes zero fetches and fabricates signals incl. a stub
  `site_read`.

## Guardrails (hard)

- **Additive only:** never remove/rename existing `website_signals` keys or
  change `scoring.py` inputs' meaning; `site_read` is new and optional.
- Respect robots.txt for every fetch; cap sitemap files, URLs, pages, and
  wall-time; identify as the existing `USER_AGENT`.
- No live network in tests — mock httpx; include a fixture sitemap-index +
  child sitemap + a couple of HTML pages (one with JSON-LD, one with a
  bare badge, one market page).
- Do NOT `git commit`/`git push`, no service restarts, no scans run.

## Validation (run, report)

- `pytest -q` (or the repo's test runner) green, incl new tests:
  sitemap-index nesting parsed; ranking picks market+practice pages;
  JSON-LD types detected incl `@graph`; `has_market_landing_page` true/false
  cases; `faq_has_schema` false when FAQ page lacks FAQPage; badges-without-
  links detection; graceful no-sitemap fallback to legacy mode; dry-run makes
  zero fetches.
- `bin/aivis website <any_scanned_id> --dry-run` prints the site-read stub,
  zero fetches.
- Confirm an existing scanned firm still scores (no KeyError from added keys).

## Report (end of run)

Files changed, the `site_read` schema, new settings/env, CLI additions, test
list, and STOP.
