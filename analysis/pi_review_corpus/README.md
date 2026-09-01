# PI Review Corpus Analysis

This directory contains the frozen, reproducible analysis used for the Possible Minds article published on September 1, 2026.

## Frozen snapshot

- Snapshot: `2026-09-01T07:28:42Z`
- Included distinct reviews: 7,383
- Independent-source reviews: 7,320
- PI firms represented: 1,002
- Classification: 7,383 of 7,383 on `pi_reviews_v1`

## Reproduce

Run from the Possible OS repository root against the live database:

```bash
python3 scripts/analyze_pi_review_corpus.py \
  --snapshot-at 2026-09-01T07:28:42Z \
  --output-dir analysis/pi_review_corpus
```

The command enforces the 5,000-review gate and fails if any included review is not classified. It writes `aggregate.json` plus the eight chart-ready CSV files under `charts/`.

The primary analysis excludes firm-curated testimonials and aggregator records. Exact within-source duplicates are removed, and identical review text found across sources for the same firm is marked as a republication rather than counted as an independent client experience.

## Limitations

Google accounts for 7,197 of the 7,383 included reviews. Yelp contributes seven. The corpus is therefore broad across firms but unsuitable for cross-platform comparisons. Public reviews are self-selected, and `pi_reviews_v1` is primarily a deterministic rules baseline that may miss implicit meaning.
