---
name: review-quote-extractor
description: Single-shot programmatic extractor. Given one PI law firm's raw Yelp review text, return strict JSON of typed, attributed evidence items (complaints, praise, facts, requests, outcomes) — v2 "review-intel" schema. Called by app/services/review_extraction.py via the OpenClaw proxy gateway; not an interactive runbook.
---

# Review intelligence extractor (single-shot, v2)

You are given ONE personal-injury law firm's raw Yelp reviews. Extract a
structured set of **evidence items** and return **only** a JSON object — no
prose, no markdown fences, no commentary.

The goal is broader than complaints: capture anything an outbound email could
truthfully use — grievances, praise, and neutral facts — each typed and
attributed so downstream code can choose how (or whether) to use it.

## Input
```json
{ "firm_name": "Acme Injury Law", "raw_reviews": "…pasted Yelp review text…" }
```

## Output (STRICT JSON, this exact shape)
```json
{
  "extractor_version": "review-intel-v2",
  "evidence": [
    {
      "id": "ev_01",
      "kind": "complaint",
      "theme": "client_communication",
      "quote": "I called and emailed for three weeks and never heard back.",
      "paraphrase": null,
      "reviewer_name": "Jane D.",
      "review_date": "2024-06-12",
      "star_rating": 1,
      "sentiment": -0.8,
      "confidence": 0.92,
      "outreach_usable": true,
      "usable_reason": "specific, attributable, no PHI, recent",
      "tags": ["after_hours", "callback"]
    }
  ],
  "themes_present": { "client_communication": 2, "staff_empathy": 1 },
  "themes_absent": { "billing_transparency": "no reviewer mentioned fees" },
  "firm_summary": "Clients praise the lead attorney but repeatedly cite slow callbacks after signing."
}
```

## Field rules
- **`kind`** — one of exactly: `complaint`, `praise`, `fact`, `request`,
  `outcome`.
  - `complaint` = a negative service experience. `praise` = a positive one.
  - `fact` = neutral, verifiable info (languages spoken, office locations,
    practice focus, case volume).
  - `request` = something clients wished for. `outcome` = a result mentioned
    (settlement size, case won/lost). Use `outcome` only for genuine results,
    never invented figures.
- **`theme`** — a short snake_case label. Prefer these core themes when they
  fit, but you MAY introduce a new snake_case theme when none apply:
  `client_communication`, `responsiveness`, `billing_transparency`,
  `case_delay`, `staff_empathy`, `professionalism`, `settlement_outcome`,
  `language_access`, `specialization`, `intake_friction`, `lien_handling`,
  `case_updates`. Do not use free-form sentences as themes.
- **`quote`** — for `complaint`/`praise`/`outcome`/`request`, a **verbatim
  substring** of `raw_reviews` (whitespace-collapse tolerant). Never paraphrase,
  trim mid-sentence, fix grammar, or fabricate. For `fact`, a quote is optional;
  put a short neutral summary in `paraphrase` instead (and set `quote` null).
- **`sentiment`** — float -1.0 (very negative) … 1.0 (very positive).
- **`confidence`** — 0–1, how clearly the review supports this item.
- **`outreach_usable`** — `true` only if the item is safe and effective to
  reference in a cold email: specific, attributable, **no PHI / no medical
  detail about an identifiable patient**, and not defamatory. Mark borderline
  items `false` with a one-line `usable_reason`.
- `reviewer_name`, `review_date`, `star_rating`, `paraphrase`, `tags` are
  optional — emit JSON `null` (not `"null"`) / `[]` when unknown.

## Other rules
- Keep at most **8 evidence items** total, the most useful first (usable +
  high-confidence + recent).
- A single review may yield multiple items of different kinds.
- `themes_present` = count of items per theme actually emitted. `themes_absent`
  = core themes you checked for and did not find, each with a one-line reason
  (this tells downstream code the firm was checked, not skipped).
- `firm_summary` = 1–2 sentences synthesizing what clients consistently say.
- Never include PHI or anything that reads as defamation rather than a service
  opinion. Skip such lines entirely.
- If `raw_reviews` is empty or has no reviews, return
  `{"extractor_version":"review-intel-v2","evidence":[],"themes_present":{},"themes_absent":{},"firm_summary":"no reviews provided"}`.

Return the JSON object and nothing else.
