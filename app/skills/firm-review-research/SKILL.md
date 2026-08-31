---
name: firm-review-research
description: Source-backed public review collection for one exact firm. Returns strict JSON for Possible OS.
---

# Public firm-review researcher

Research public client reviews for exactly one firm. Return only a JSON object,
with no markdown fences or commentary.

## Input

```json
{
  "firm_name": "Example Injury Law",
  "official_website": "https://example.com",
  "address": "Los Angeles, CA"
}
```

## Required research

Find matching public firm listings on Google Maps, Yelp, Avvo, Justia,
Facebook, Martindale, and other reputable review sources. Confirm the exact
firm using its website, address, phone, or consistent identity. Reject
similarly named firms.

For every review text that is publicly accessible in the listing page, retain
the review verbatim. Follow source pagination or "more reviews" controls where
available. Do not use search snippets as review text. Do not paraphrase,
summarize, invent, or complete truncated reviews. If a source blocks access,
states a total but reveals only a subset, or has no accessible reviews, state
that plainly in `coverage_note`.

## Output

```json
{
  "sources": [
    {
      "source": "google",
      "listing_url": "https://maps.google.com/...",
      "coverage_note": "18 publicly accessible reviews collected; the listing showed no additional review page.",
      "reviews": [
        {
          "reviewer_name": "Jane D.",
          "rating": 5,
          "review_date": "2026-08-20",
          "text": "They kept me informed throughout the case.",
          "review_url": null
        }
      ]
    }
  ],
  "coverage_note": "Yelp listing was inaccessible; Google and Avvo were checked."
}
```

Use lower-case source keys when possible. `review_date` must be `YYYY-MM-DD`
or `null`; `rating` must be a number from 0 to 5 or `null`; `review_url` may be
null. Return `{"sources":[],"coverage_note":"..."}` when no verified public
reviews are accessible.
