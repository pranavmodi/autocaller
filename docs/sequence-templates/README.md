# Archived sequence templates

Templates removed from the live registry but preserved for reuse.

## precise_pain_4step (`precise_pain_4step.py`)

The original Precise-context 4-step sequence (Apr-May 2026, 124 sequences,
13 with the Yelp quote step). Removed from the registry in 737f5e0 ("Make
lead gen dynamic composer only"); recovered verbatim from git history.

Structure:
1. **Day 0 — opener**: "we built Precise's automated replies", permission
   to ask questions, explicitly not a pitch.
2. **Day 4 — frozen review quote** (variant `with_quote` only): quotes a
   specific Yelp review of the recipient's firm verbatim (reviewer name +
   date frozen on the sequence row: `email_sequences.frozen_pain_quote`,
   `frozen_reviewer_name`, `frozen_review_date`), then reframes the pain
   generously ("an unowned case-manager queue, not anyone being lazy").
3. **Day 10 — proof**: Precise's ~100 hrs/week email triage automated,
   two weeks of human review, "handed it the keys".
4. **Day 17 — breakup**: close the file, consult link, no hard feelings.

Variant `without_quote`: drops step 2, runs 3 touches at days 0/7/14.

Revival notes (2026-06-12):
- The 100 hrs/week claim predates the approved-evidence rules. Current
  cleared numbers: ~600 inbound emails/day mechanic; 520 staff-hours/month;
  73% of volume auto-handled; max ONE number per email.
- The frozen-quote mechanism is the valuable part: pin one piece of
  evidence to the sequence row so all steps reference it consistently.
  Today's gentler equivalent: the firm's own after-hours traffic ratio or
  primary pain topic from front_firm_activity.behavioral_json, instead of
  a public negative review.
- Outcomes were never measured per step (no opens tracking then) — if
  revived, run it through the composer A/B framework.
