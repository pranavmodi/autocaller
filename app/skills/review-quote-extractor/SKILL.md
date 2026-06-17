---
name: review-quote-extractor
description: Single-shot programmatic extractor. Given one PI law firm's raw Yelp review text, return strict JSON of verbatim client_communication pain-point quotes (v1 schema). Called by app/services/review_extraction.py via the OpenClaw proxy gateway — not an interactive runbook.
---

# Review quote extractor (single-shot)

You are given ONE personal-injury law firm's raw Yelp reviews. Extract verbatim
pain-point quotes and return **only** a JSON object — no prose, no markdown
fences, no commentary.

## Input
A JSON object:
```json
{ "firm_name": "Acme Injury Law", "raw_reviews": "…pasted Yelp review text…" }
```

## Output (STRICT JSON, this exact shape)
```json
{
  "extractor_version": "yelp-quotes-v1",
  "pain_points": {
    "client_communication": [
      {
        "quote": "I called and emailed for three weeks and never heard back.",
        "reviewer_name": "Jane D.",
        "review_date": "2024-06-12",
        "star_rating": 1,
        "confidence": 0.92
      }
    ]
  },
  "absent_pain_points": {}
}
```

## Pain-point taxonomy (closed set — use only these keys)
| key | what it means | typical signals |
|---|---|---|
| `client_communication` | Clients couldn't reach the firm, weren't called back, were ignored after signing, had to chase for updates. | "didn't return my call", "ignored my emails", "never heard back", "had to chase them", "no updates for months". |

Do **not** invent free-form keys. Anything that doesn't fit the taxonomy is
dropped — do not store it under `other`.

## Rules
- `quote` is **mandatory** and must be a **verbatim substring** of `raw_reviews`
  (whitespace-collapse tolerant). Never paraphrase, trim mid-sentence, fix
  grammar, or fabricate. If you cannot find a verbatim line, do not emit a quote.
- `reviewer_name`, `review_date`, `star_rating`, `confidence` are optional —
  emit JSON `null` (not the string "null") when unknown. `confidence` is 0–1.
- Keep at most **5 quotes per pain point**, ranked by confidence descending.
- A single review may yield multiple quotes.
- **Absent pain points are explicit.** If a taxonomy key has no qualifying
  quote, add it under `absent_pain_points` with a one-sentence reason (what the
  complaints were about instead, or "no negative reviews"). A key must appear in
  EITHER `pain_points` OR `absent_pain_points`, never both.
- Never include PHI, medical details about a specific patient, or anything that
  reads as defamation rather than a service complaint. Skip such lines.
- If `raw_reviews` is empty or contains no reviews, return
  `{"extractor_version":"yelp-quotes-v1","pain_points":{},"absent_pain_points":{"client_communication":"no reviews provided"}}`.

Return the JSON object and nothing else.
