# Prompt Editor — design parked for later

**Status:** Parked 2026-04-24. Not yet implemented. Revisit after we've
experimented with alternative prompt variants (the "simpler prompt" work
that comes next) and have a clearer sense of which slots actually need
operator-level editability.

**Goal:** Give a non-engineer operator a safe UI to edit the live system
prompt, organised by **when each section fires during a call** rather
than by file order. Today the prompt lives as a 1500-line Python string
in `app/prompts/attorney_cold_call.py`; any edit requires file edit +
version bump + commit + push + daemon restart (per CLAUDE.md prompt
protocol). This doc captures the design so we can pick it up cold.

---

## 1. Core insight — time, not file order

The current prompt is authored in a logical order for an LLM to read
(identity → rules → opener → discovery → VM → tone). That order is
**not** the order events happen on a call. A call actually runs:

```
t=0s     Line connects
t=0-3s   AI says "Hello?" (one word, then LISTEN)
t=3-10s  Caller replies → AI classifies: human? IVR? voicemail? queue?
          ├─ IVR  → stay silent, navigator takes over
          ├─ VM   → deliver 30-sec Case A or B script
          ├─ queue → "Okay." + wait
          └─ human → two-beat peer-first opener
t=10-30s Opener → Beat 1 (peer-ask) → Beat 2 (classify DM vs GK)
          ├─ DM confirmed → Branch A (A1 Precise anchor, A2 pain, A3 reveal, A4 schedule)
          └─ Gatekeeper   → Branch B (tier 1→2→3.5→4, intel harvest)
t=30-120s Discovery (Sobczak §8) OR gatekeeper rapport
t=60-120s AI self-reveal (if three preconditions met)
t=90-180s Recommendation + demo handoff (check_availability + book_demo)
t=end    Wrap-up with commitment OR end_call with outcome
```

The UI should surface the prompt **in call-flow order**, with each
section labelled by its role and by the time-window it fires.
Always-on rules (hard rules, tone, silence) sit as a ribbon beneath
the timeline indicating "applies every turn."

---

## 2. Proposed 14-section taxonomy

Parsed from the current `##` top-level headings in
`app/prompts/attorney_cold_call.py`, grouped into call-flow slots:

| # | Slot ID | Title | Role | When it fires |
|---|---------|-------|------|---------------|
| 1 | `identity` | Identity & Goals | Who the AI is; rep/firm/DM context; primary (book demo) + secondary objectives. | Pre-call; always loaded. |
| 2 | `turn_taking` | First Utterance — "Hello?" | Rule to say ONE word and then listen. Prevents pitching into voicemail greetings. | t ≈ 0–3 s. |
| 3 | `first_listen` | Classify What Answered | Hard-signal phrases that distinguish human vs. IVR vs. VM vs. queue vs. "record your name" screener. | t ≈ 3–10 s. |
| 4 | `voicemail_ivr_routing` | VM / IVR Routing | Stay silent on IVR (navigator drives DTMF); leave a message on VM. Includes queue exception + screening exception. | t ≈ 5–15 s if not a human. |
| 5 | `opener_two_beats` | Opener — Two Beats | Beat 1 (peer-ask + pause). Beat 2 (classify DM vs GK before speaking). | t ≈ 5–20 s on a human line. |
| 6 | `branch_dm` | Branch A — DM on the Line | Softener → A1 Precise anchor → A2 pain question → A3 AI reveal → A4 schedule now. | t ≈ 20–90 s when DM is confirmed. |
| 7 | `branch_gatekeeper` | Branch B — Gatekeeper | Tiers 1–4: identity strategy, Precise name-drop, rapport + intel harvest, never-empty-handed. | t ≈ 15–60 s when receptionist/PA picks up. |
| 8 | `discovery` | Discovery — After Permission | Sobczak's 5 rules (never "if", loaded-benefit 3rd-party, iceberg, quantify, depersonalize DM check). Pain areas to probe. | t ≈ 30–120 s with an engaged DM. |
| 9 | `objection_handling` | Objection Handling | Softener + redirecting question. When to bounce back vs. accept shutdown. Seed-planting close. | Any moment the caller pushes back. |
| 10 | `ai_reveal` | AI Self-Reveal | Proof-of-tech moment. Three preconditions. Understated phrasing. | t ≈ 60–120 s mid-pitch. |
| 11 | `recommendation_demo` | Recommendation + Demo Handoff | When to use `check_availability` + `book_demo` tools. Rules against scheduling prematurely. | t ≈ 90–180 s once a real pain is named. |
| 12 | `wrap_up` | Wrap-Up with Commitment | If no demo, leave with at least one secondary (email, intel, callback slot). Sobczak §11 close. | End of call, no demo booked. |
| 13 | `voicemail_script` | Voicemail Script (Case A & B) | ~30-sec pitch: Case A (firm-general opener), Case B (DM-named opener). CTA URL + text-back option. Hard rules for the script. | t ≈ 5–60 s when a mailbox is detected. |
| 14 | `rules_and_tone` | Hard Rules, Banned Phrases, Tone, Silence | Never lie, no character breaks, tool-use correctness, banned phrasings, flat intonation, silence-is-fine. | Always on, every turn. |

A 15th section (`spanish_parallel`) can surface the Spanish template as
a read-only block at the bottom for Spanish-language leads. Editing
Spanish without translation review risks breaking the language-aware
flow, so keep it read-only in Phase 1.

---

## 3. UI wireframe

Two panes side-by-side on `/prompt`:

```
┌──────────────────────────────────────────────────────────────────────┐
│  /prompt  ·  Prompt Editor                                           │
│  v1.61-en   14/14 sections loaded   [Preview rendered →] [Save all]  │
└──────────────────────────────────────────────────────────────────────┘

┌─────── TIMELINE ────────┐  ┌──────── SECTION EDITOR ─────────────────┐
│  PRE-CALL               │  │                                         │
│  [1] Identity & Goals   │  │  3. Classify what answered              │
│       │                 │  │                                         │
│  [2] First utterance    │  │  WHEN: t ≈ 3–10 s, AI's first decision  │
│       ←t=0s             │  │  ROLE: human vs IVR vs VM vs queue      │
│       │                 │  │  AFFECTS: speak or stay silent next     │
│  [3] Classify ●selected │  │                                         │
│   ←t=3-10s              │  │  ┌──────────────────────────────────┐   │
│       │                 │  │  │ ### Hard signals…                │   │
│   ├─IVR ├─VM ├─q ├─hum  │  │  │                                  │   │
│   │     │    │    │     │  │  │  (editable textarea)             │   │
│  [4]   [13] (4) [5]     │  │  │                                  │   │
│   VM/  VM    queue Opener│  │  └──────────────────────────────────┘   │
│   IVR  script            │  │  Slots: {lead_first_name} {firm…}       │
│       │                 │  │                                         │
│   [6] DM ── [7] GK      │  │  [Preview section ↓]                    │
│       │                 │  │  [Revert to default]   [Save]           │
│  [8] Discovery          │  │                                         │
│  [9] Objection (any)    │  └─────────────────────────────────────────┘
│  [10] AI reveal         │
│  [11] Demo handoff      │  ┌─── Always-on layer ──────────────────┐
│  [12] Wrap-up           │  │ 14. Rules, tone, silence (every turn) │
│ ══════════════════════  │  └───────────────────────────────────────┘
│  14. Rules & tone        │
│     (always on)          │
└─────────────────────────┘
```

**Left: call-flow timeline.** Vertical, top = t=0, bottom = end of call.
Each section is a box with an icon, slot number, title, and "when"
chip. Shows branching (IVR / VM / queue / human, then DM / GK under
human). The `rules_and_tone` always-on layer sits as a ribbon at the
bottom.

**Right: section editor for the selected slot.** Shows:

- **When** and **Role** chips (the call-flow context)
- **Affects** — what behavior this section controls
- Editable textarea with the body
- **Slots used** — template variables (`{lead_first_name}`,
  `{firm_name_clause}`, etc.) as chips that preview against a sample lead
- **Preview this section** — renders just this section with interpolation
- **Revert to default** — discards this section's override only
- **Save** — persists the edit

Clicking a timeline box loads the section in the editor. Edits are
pending (diffed against default) until Save. "Save all" at top commits
every pending edit in one transaction and bumps `PROMPT_VERSION`.

---

## 4. Data model

```sql
-- Stores ONLY edits (deltas). The Python source file remains the
-- default/floor. DB empty → render is 100% default, identical to today.
prompt_section_overrides (
  slot        text primary key,      -- one of the 14 slot IDs
  body        text not null,         -- user-edited section text
  note        text,                  -- optional "why I changed this"
  updated_at  timestamptz default now(),
  updated_by  text                   -- operator email/name if auth'd
)
```

**Key design decision: the default prompt stays in Python code.** The
source file is always the floor. The DB stores only overrides. This
means:

- Empty DB or fresh deployment → render is byte-identical to today.
- A corrupted override for one slot silently falls back to default
  for that slot; every other slot is unaffected.
- Editing a section in the UI writes a row; deleting reverts to default
  without losing the original text.
- `git blame` on the Python file still reflects authorship history.
- When we later add the variants system (`prompt_variants` table +
  per-slot A/B), these overrides become "the live variant" for each
  slot and we add a `prompt_variants` table alongside.

---

## 5. Loader design (Python)

```python
# app/prompts/sections.py
from dataclasses import dataclass

@dataclass
class SectionDef:
    slot: str
    title: str
    role: str          # "what this controls" — one sentence
    when: str          # "t ≈ 3–10 s, AI's first decision"
    order: int         # timeline position
    always_on: bool    # True for rules_and_tone
    # Markers used by the parser to locate this section in PROMPT.
    # Each section starts at the first H2 matching `start_heading`
    # and ends at the next H2 (or EOF).
    start_heading: str
    # Optional: if a single H2 covers multiple slots, use a regex
    # that matches the tighter H3 sub-heading.
    start_regex: str | None = None

SECTION_DEFS = [
    SectionDef("identity",              "Identity & Goals",             ..., order=1, always_on=False, start_heading="## Glossary"),
    SectionDef("turn_taking",           "First utterance — \"Hello?\"",  ..., order=2, ...),
    SectionDef("first_listen",          "Classify what answered",       ..., order=3, ...),
    SectionDef("voicemail_ivr_routing", "VM / IVR routing",             ..., order=4, ...),
    SectionDef("opener_two_beats",      "Opener — two beats",           ..., order=5, ...),
    SectionDef("branch_dm",             "Branch A — DM on the line",    ..., order=6, ...),
    SectionDef("branch_gatekeeper",     "Branch B — Gatekeeper",        ..., order=7, ...),
    SectionDef("discovery",             "Discovery — after permission", ..., order=8, ...),
    SectionDef("objection_handling",    "Objection handling",           ..., order=9, ...),
    SectionDef("ai_reveal",             "AI self-reveal",               ..., order=10, ...),
    SectionDef("recommendation_demo",   "Recommendation + demo",        ..., order=11, ...),
    SectionDef("wrap_up",               "Wrap with commitment",         ..., order=12, ...),
    SectionDef("voicemail_script",      "Voicemail script (Case A/B)",  ..., order=13, ...),
    SectionDef("rules_and_tone",        "Hard rules + tone + silence",  ..., order=14, always_on=True, ...),
]

def _split_prompt_by_h2(prompt_text: str) -> dict[str, str]:
    """Split PROMPT into slot → body by matching SectionDef markers."""
    ...

def _rejoin_sections(sections: dict[str, str]) -> str:
    """Concatenate sections back in order. MUST produce original string."""
    ...

def _parse_and_verify() -> dict[str, str]:
    sections = _split_prompt_by_h2(PROMPT)
    rejoined = _rejoin_sections(sections)
    if rejoined != PROMPT:
        idx = _first_diff(rejoined, PROMPT)
        raise RuntimeError(
            f"Section parser is lossy at char {idx}. Refusing to start — "
            "rendered prompt would differ from source. See sections.py."
        )
    return sections

_DEFAULT_SECTIONS = _parse_and_verify()   # runs at module import

async def get_effective_sections() -> dict[str, dict]:
    """Default + DB overrides. Returns full body info per slot."""
    overrides = await fetch_prompt_overrides()
    out = {}
    for slot, default_body in _DEFAULT_SECTIONS.items():
        ov = overrides.get(slot)
        out[slot] = {
            "default": default_body,
            "override": ov,
            "effective": ov if ov is not None else default_body,
            "is_overridden": ov is not None,
        }
    return out
```

---

## 6. `render_system_prompt` changes

**PR 1 — no change.** Parser exists but is only read by the new
`/api/prompt/sections` endpoint. `render_system_prompt` still calls
`PROMPT.format(...)` exactly as today.

**PR 3 (behind `PROMPT_OVERRIDES_ENABLED` env flag):**

```python
async def render_system_prompt(patient, ...) -> tuple[str, str]:
    if not os.getenv("PROMPT_OVERRIDES_ENABLED"):
        return PROMPT.format(**slots), PROMPT_VERSION

    sections = await get_effective_sections()
    assembled = "".join(
        sections[d.slot]["effective"]
        for d in sorted(SECTION_DEFS, key=lambda s: s.order)
    )
    return assembled.format(**slots), _version_with_patch_suffix()
```

Flag off → behavior identical to today, regardless of DB contents.

---

## 7. REST API

```
GET    /api/prompt/sections
       → List of { slot, title, role, when, order, is_overridden, updated_at }
         All 14 slots.

GET    /api/prompt/sections/{slot}
       → { slot, title, role, when, default_body, override_body, effective_body, is_overridden }

PUT    /api/prompt/sections/{slot}
       Body: { body, note }
       → Writes override. Validates: `.format(...)` interpolation still succeeds
         against a sample lead (catches `{` typos). Bumps PROMPT_VERSION.

DELETE /api/prompt/sections/{slot}
       → Clears override. Bumps PROMPT_VERSION.

GET    /api/prompt/preview?patient_id=<id>
       → Full rendered prompt for a sample lead (default or specified).
         Shows what calls will actually see.

GET    /api/prompt/verify
       → Runs _parse_and_verify() and reports "byte-equal ✓" or diff.
         Used by CI and post-deploy smoke.
```

---

## 8. CLI parity (CLAUDE.md rule)

```
autocaller prompt list                   # table: slot, title, when, overridden?
autocaller prompt show <slot>            # effective body
autocaller prompt show <slot> --default  # source body
autocaller prompt edit <slot>            # opens $EDITOR on effective; save → PUT
autocaller prompt reset <slot>           # DELETE override for one slot
autocaller prompt reset --all            # clear every override (panic button)
autocaller prompt preview [--lead=<id>]  # print rendered prompt
autocaller prompt diff <slot>            # unified diff default vs. override
autocaller prompt verify                 # parser byte-equality check
```

---

## 9. `PROMPT_VERSION` handling

**Option (a) — computed version:** `v{base}.{sum(len(overrides))}` or
similar hash. Every change produces a unique stamp automatically but
the number becomes ugly and non-semver.

**Option (b) — patch-number bump, recommended:** on any section save,
increment a patch component kept in a separate settings row:
`v1.61` → `v1.61.1` → `v1.61.2`. Resets when the base version bumps via
a code edit. The full rendered prompt is still stored verbatim on every
`call_logs.prompt_text`, so historical reproduction is exact regardless
of version-number precision.

Schema:

```sql
-- Extend system_settings (or a new table) with:
prompt_override_version  int default 0
```

`prompt_version` as sent to the voice backend becomes
`f"{PROMPT_VERSION}.{override_version}-{lang}"` when override_version > 0.

---

## 10. Risk + rollout (three PRs)

| PR | Change | Risk to live calls | Reversible |
|----|--------|-------------------|------------|
| **PR 1** | Add `sections.py` + parser + startup assertion + `autocaller prompt verify`. Adds GET `/api/prompt/sections` (read-only). No UI changes yet, or a read-only `/prompt` page. | **None.** Parser feeds only the new endpoint. `render_system_prompt` unchanged. Assertion refuses to start backend if parser is lossy — impossible to deploy a silently-broken prompt. | Delete new files, no other changes. |
| **PR 2** | Add DB migration for `prompt_section_overrides`. Wire GET endpoint to include override/effective bodies (still empty by default). Frontend `/prompt` page: timeline + cards read-only. | **None.** Table empty. No code path reads overrides yet. | Drop table. |
| **PR 3** | Add PUT/DELETE endpoints. Add CLI edit/reset commands. Add save + edit-mode in UI. Wire overrides into `render_system_prompt` behind `PROMPT_OVERRIDES_ENABLED` env flag. | **Medium — BUT** only if operator saves an edit AND the env flag is on. Default-off flag means deployment is still behavior-identical; flipping the flag without any saved overrides is also behavior-identical. First actual change happens only on explicit save + flag-on. | `DELETE FROM prompt_section_overrides` or `autocaller prompt reset --all`, or unset the flag. |

**Safety guarantees that apply to every PR:**

- **Startup assertion.** Backend refuses to boot if the parser produces
  a lossy split. No silent corruption path exists.
- **Python source = floor.** The `PROMPT` constant in
  `attorney_cold_call.py` is always the default. A deleted override row
  = default behavior. A corrupted override row = falls back to default
  for that slot, logged.
- **Env flag.** `PROMPT_OVERRIDES_ENABLED=0` (default) ignores all DB
  overrides. Panic switch.
- **Interpolation validator on save.** PUT endpoint rejects any body
  whose `.format(...)` against a sample lead raises `KeyError`,
  `IndexError`, or `ValueError` — catches `{` typos before they reach a
  live call.
- **Rendered prompt preservation.** `call_logs.prompt_text` continues
  to store the exact string sent to the model for every call. Post-hoc
  bug reproduction is unchanged.

---

## 11. Open questions to resolve before implementation

**Q1 — Section granularity.** Is the 14-slot split right? Specifically:

- Keep `branch_dm` and `branch_gatekeeper` as separate slots (matches
  call flow fork, enables GK-only A/B later), or merge into one
  `after_opener` slot (matches current file authorship)?
- Should the `opener_two_beats` slot include Beat 1 + Beat 2 + the
  branch *router* but exclude the Branch A/B bodies (which are their
  own slots), or should it be a single monolithic "opener" including
  branches?

**Q2 — Edit granularity.** Per-section save (proposed) vs. a single
monolithic textarea of the full prompt. Per-section prevents a bad edit
in one place from breaking another and allows per-slot revert; monolithic
feels like a text editor. Per-section wins for safety.

**Q3 — Auth.** Does the UI need operator authentication before it can
save? Today the autocaller admin UI has basic auth; the prompt editor
should inherit whatever the rest of `/system` uses. Log `updated_by`
so we know who changed what.

**Q4 — Save preview gating.** Should "Save" require "Preview rendered"
to have been viewed at least once on the pending diff? Prevents blind
saves; adds one click.

---

## 12. When to revisit

Revisit this doc when either:

1. Non-engineer operators are consistently asking for prompt edits (the
   main driver for this UI). Right now, prompt edits happen via
   developer file-edit flow and that's fine.
2. The alternative-prompt-variants work (separate WIP) ships and we
   want per-slot variants rather than whole-prompt swaps — the DB
   overrides table here becomes the natural scaffold for
   `prompt_variants`.
3. We want to run A/B experiments on individual sections (e.g. two
   opener variants) without forking the full prompt file.

Until one of those is pressing, the current file-edit + commit + push
flow is simpler and has git history baked in.
