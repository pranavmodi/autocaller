# Prompt A/B Testing — Design Note (PARKED)

Status (2026-04-16): designed, not implemented. Parked so we can ship
script-quality improvements first. When we come back to this, the plan
below is ready to go.

Why we're parking it: the system's biggest pain today isn't "which of
two prompts works better" — it's that the single prompt we have isn't
Sobczak-aligned yet. Once we have two genuinely different, well-tuned
candidates, this framework becomes worth building.

---

## Goal

Run two or more prompt variants in parallel on the same lead pool,
measure which wins on demo-book rate + other outcomes, and graduate the
winner to default. Without this framework, every prompt change is a
guess and we can't tell noise from signal.

## One-line summary

A registry of named prompt variants, a weighted-assignment policy per
experiment, and a report that groups the existing judge scores + call
outcomes by variant with a basic significance test.

## Data model

```python
# app/prompts/variants.py
PROMPT_VARIANTS: dict[str, Variant] = {
    "v1.10-baseline": Variant(
        label="Baseline (Precise anchor + bad-time inversion)",
        template_en=CURRENT_TEMPLATE,
        template_es=CURRENT_ES_TEMPLATE,
        notes="Shipped 2026-04-15. Two-beat opener, Precise anchor after buy-in.",
    ),
    "v1.11-sobczak": Variant(
        label="Sobczak Smart-Call opener + objection state-machine",
        template_en=NEW_SOBCZAK_TEMPLATE,
        template_es=NEW_SOBCZAK_TEMPLATE_ES,
        notes="4-step opener, embedded time-respect, verbatim objection handlers.",
    ),
    # future variants drop in here
}
```

New `system_settings.prompt_experiment` JSONB column:

```json
{
  "variants": {"v1.10-baseline": 0.5, "v1.11-sobczak": 0.5},
  "assignment": "hash",
  "salt": "2026-04-exp1"
}
```

## Assignment modes

- **hash** (recommended default): `hash(lead_id + salt) % total_weight`
  — deterministic. Re-dials of the same lead stay on the same variant,
  preventing within-lead contamination.
- **weighted_random**: per-call random pick. Use when you want exact
  %-split regardless of list composition.

Both modes honour the weights; both stamp the chosen `variant_id` into
`call_logs.prompt_version` (existing column — keeps today's queries
working).

## Reporting

`autocaller experiment report --since=7d`:

```
variant              N    demo%   cb%    dm-reach   vm%    mean_score
v1.10-baseline      24    0.0%    4.2%   45.8%     37.5%   3.8
v1.11-sobczak       26    3.8%    7.7%   53.8%     30.8%   5.1

vs baseline:
  demo_rate   +3.8pp  (N too small for significance, need ≥30/arm)
  dm-reach    +8.0pp  (p=0.54, not significant)
  mean_score  +1.3    (p=0.08, marginal)
```

Significance tests:
- Two-proportion z-test for binary outcomes (demo_scheduled, callback,
  dm-reach, voicemail).
- Welch's t-test for continuous score (mean judge_score).
- Below N=30/arm, print "insufficient data" instead of a p-value —
  matches common practice and keeps us from declaring winners on noise.

## Controls

- CLI:
  - `prompts list` / `prompts show <id>`
  - `experiment status`
  - `experiment set-weights "a:0.5,b:0.5"`
  - `experiment set-mode hash|weighted_random`
  - `experiment reset`
  - `experiment report [--since=7d]`
- REST: `PUT /api/settings/experiment`, `GET /api/experiment/report`
- UI: new "Experiments" card on the Now page (or a separate
  `/experiments` route) showing active variants, live counts, latest
  report snapshot.

## Per-call override

`autocaller call <lead> --prompt=v1.11-sobczak` forces a specific variant
for a single dial. Useful for "let me try the new one on this firm."

## Defaults to confirm before implementation

1. **Hash vs weighted_random as default**: recommend **hash** to avoid
   re-dial contamination.
2. **Ship registry alone first**, or **registry + v1.11-sobczak draft in
   one commit**: recommend separate commits. Registry is plumbing;
   variant content deserves its own review.

## Minimum shippable scope (when unparked)

- Registry + migration + v1.10-baseline as single entry.
- Hash assignment + orchestrator wiring + stamp on call_log.
- `experiment report` CLI with per-variant aggregates + z-test.
- `experiment set-weights` + `experiment status` CLI.

Deferrable:
- Frontend experiments page (ship backend first; build UI after we've
  run one real experiment).
- The actual v1.11 template — that's a prompt-writing session on its
  own.

## Statistical rigor notes

- Minimum sample size per variant before declaring winner: N=30, with
  demo-book a rare event we may need N=100+ per arm to get tight CIs.
- Stratify by prompt_language (en vs es) when computing — different
  base rates.
- Stratify by voice_provider (openai vs gemini) too — confounder.
- Consider a sequential test (e.g. SPRT) if we want to stop experiments
  early; not for v1.

---

## Why this is parked (2026-04-16)

From the last-10-calls analysis the bigger levers are:
- Sobczak-aligned opener (kills the banned "bad time?" phrasing)
- Objection-handler state machine (verbatim response bank)
- Secondary objectives per call (never leave empty-handed)
- Actually leaving voicemails on first attempt
- Call-high + gatekeeper 4-step social engineering

We'll ship those as v1.11 first, let it run, then come back here.
