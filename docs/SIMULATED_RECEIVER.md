# Simulated call receiver

A headless "persona on the other end of the line" that our autocaller can dial for scenario testing. Lets us iterate on prompt, tools, and objection handling without spending Twilio minutes or role-playing on the phone.

---

## What we're actually trying to test

Per scenario, we want to answer questions like:

- Does the AI **correctly invoke `end_call` with `outcome=gatekeeper_only`** when the line is picked up by a receptionist?
- Does the AI **avoid promising a meeting** when `check_availability` returns empty slots? Does it fall back to `send_followup_email`?
- Does the AI **handle price objections** gracefully without hallucinating a quote?
- Does the AI **detect voicemail** and hang up silently?
- Does the AI **quantify pain properly** ("how many hours/week does that eat?") before proposing a demo?
- Does the AI **book a plausible slot** and confirm the email before calling `book_demo`?

These are 80% of the questions that matter for quality. All answerable without a real phone call.

---

## Four implementation options (ranked by ROI)

### Option A — Text-only dual-agent loop (RECOMMENDED FOR V1)

Skip audio entirely. Two AI agents exchange text messages; our autocaller reads the persona's message as if it came from OpenAI Realtime's transcription. No TTS, no STT, no Twilio, no audio buffers — just LLM ↔ LLM.

**Flow:**
```
[Persona agent]  "Hello?"
    ↓ fed as user-speech transcript
[Autocaller AI]  "Hi, is this Jane? This is Alex from..."
    ↓ fed as AI message
[Persona agent]  "Who is this? What's this about?"
    ↓ ...
```

**Pros:**
- Runs in seconds, not minutes
- Zero cost per run (just text LLM tokens — $0.001-0.01/run)
- Fully deterministic when temperature=0
- Easy to snapshot transcripts for regression tests
- Can run hundreds in CI

**Cons:**
- Doesn't exercise the audio pipeline (Twilio bridge, VAD, interruptions)
- Tool-calling is harder to wire — the real Realtime API streams tool calls, but in text-mode we have to emulate the tool round-trip

**What it tests**: prompt quality, tool selection, objection handling, dialog flow, end-call logic. **What it doesn't**: barge-in, silence detection, audio latency, carrier quirks.

### Option B — Audio dual-agent loop (STRETCH)

Two **Realtime** sessions (both OpenAI or one of each) talking to each other. Our autocaller runs as normal; the persona runs on a second Realtime session with a persona-specific system prompt and no tools (it can only speak).

**Flow:**
```
Autocaller Realtime WS  ──audio──►  (in-memory pipe)  ──audio──►  Persona Realtime WS
        ▲                                                                  │
        └─────────────audio───────────(in-memory pipe)────audio◄───────────┘
```

**Pros:**
- Exercises the full audio path (VAD, barge-in, streaming)
- Closer to real call behavior
- Can still skip Twilio

**Cons:**
- 2× OpenAI Realtime cost per run (~$0.30-0.50/min for both sides)
- Non-deterministic — runs vary
- More code — need an audio pipe between two WS sessions
- Slower feedback loop (real-time duration)

**What it adds over Option A**: audio-specific behaviors only. Use for periodic validation, not daily iteration.

### Option C — Real Twilio, AI-driven receiver

Our autocaller dials a real Twilio number **that we own**, pointed at a TwiML endpoint that connects to our persona agent (another Realtime session). We pay Twilio on both legs; we exercise the full stack.

**Pros:**
- Tests everything including Twilio media stream, codec, AMD, cloudflared/nginx
- Real end-to-end validation — this is what production looks like

**Cons:**
- Twilio cost on both legs (~$0.04-0.08/min)
- Slowest feedback loop
- Overkill for prompt iteration

**When to use**: nightly smoke test + pre-deploy validation. Not for writing prompt changes.

### Option D — Scripted persona (no LLM on the receiver side)

Pre-written dialog trees: "if caller says X, respond with Y." Like a phone tree / chatbot on the receiver side.

**Pros:**
- Fully deterministic
- No token cost
- Easy to snapshot

**Cons:**
- Feels scripted; doesn't surprise us
- Misses the exact objections real humans invent
- Brittle — small prompt changes break scripts

**When to use**: regression tests where we want exact reproducibility (e.g., "this specific script must always produce `gatekeeper_only`").

---

## Recommended plan

**Build Option A now, add Option D on top, keep Option B and C as later stretch.**

Option A gives us a 30-second iteration loop on prompt changes, which is the single biggest lever for BD-agent quality. Option D layers deterministic regression tests on the same infrastructure.

---

## Architecture (Option A + D)

### New module: `app/services/simulation/`

```
app/services/simulation/
├── __init__.py
├── personas.py          # Library of 12-15 personas as dicts
├── scenario_runner.py   # Drives a conversation between autocaller + persona
├── judge.py             # LLM-based evaluator that scores outcomes
└── scripts/             # Deterministic dialog scripts for Option D
    ├── gatekeeper.txt
    ├── voicemail.txt
    └── ...
```

### Persona definition

```python
Persona(
    id="busy_skeptic",
    name="Jane Rothstein",
    title="Managing Partner",
    firm="Rothstein & Associates",
    state="NY",
    email="jane@rothsteinlaw.com",
    system_prompt="""You are Jane Rothstein, a managing partner at a
    mid-sized PI firm in NYC. You are busy, skeptical of cold calls, but
    professional. You WILL engage if the caller gets to the point within 15
    seconds. Your biggest pain: medical-records retrieval eats 12 hrs/week
    of paralegal time. You'd consider a demo only if the caller
    specifically addresses records retrieval. Otherwise, polite brush-off.""",
    behavior_hints={
        "initial_tone": "clipped",
        "willing_to_book": True,
        "pain_to_surface_if_asked": "medical records retrieval",
        "decision_maker": True,
    },
    expected_outcomes=["demo_scheduled", "callback_requested"],
)
```

### Scenario runner

```python
async def run_scenario(
    persona: Persona,
    autocaller_prompt: str,    # the live prompt from app/prompts/
    max_turns: int = 40,
    tool_handler: Callable,    # invokes real Cal.com etc., or mocked
) -> ScenarioResult:
    """Runs a simulated call end-to-end and returns transcript + verdict."""
```

Inside, it:
1. Creates two chat-completions loops (autocaller side + persona side), each with its own system prompt.
2. Passes each side's response as the other's next user message.
3. Intercepts tool calls from the autocaller side, invokes them (real Cal.com in live mode, or a mock that returns canned slots).
4. Terminates when autocaller calls `end_call`, or max_turns is reached.
5. Returns a `ScenarioResult` with transcript, tools invoked, final outcome.

### Judge / evaluator

After each scenario, a judge LLM (could be the same GPT-4 or a cheaper model) reviews the transcript against a rubric:

- Did the AI follow the opening script?
- Did it ask a quantifying follow-up?
- Did it handle objections without lying?
- Did it invoke the right tool at the right time?
- Did it end cleanly?

Score 0-10 per dimension. Output JSON for CI/reporting.

### CLI

```bash
bin/autocaller simulate --persona=busy_skeptic
bin/autocaller simulate --all                     # runs every persona, prints summary
bin/autocaller simulate --persona=busy_skeptic --diff=v1.3    # compare against saved baseline
```

Saves:
- `data/simulations/{run_id}/transcript.txt`
- `data/simulations/{run_id}/verdict.json`
- `data/simulations/{run_id}/tools_invoked.json`

### CI hook (later)

Run the full persona suite on every prompt change, fail the build if any baseline regresses. Cheap because Option A is text-only.

---

## Persona library (starting 12)

1. **Ideal case** — decision-maker with real pain, says yes, books demo
2. **Busy skeptic** — engages only if caller proves relevance fast
3. **Receptionist** — cheerful gatekeeper, won't escalate
4. **Voicemail** — answering machine greeting, no live person
5. **Wrong number** — "There's no Jane here"
6. **Hostile** — "Take me off your list" in turn 2
7. **Budget objection** — interested but "we can't afford anything right now"
8. **Already building in-house** — has internal tech team, but still curious
9. **Not the DM but wants to help** — paralegal who volunteers the partner's email
10. **Accidental answer** — kid / spouse picks up on a driving car
11. **Multilingual switch** — starts in English, switches to Spanish halfway
12. **Long rambler** — tells a 90-second story about their practice before we can ask

Each should have a defined "correct" autocaller outcome so the judge can grade.

---

## Effort

| phase | work | days |
|---|---|---|
| 1 | `personas.py` with 5 personas + scenario_runner for Option A (text-only, no tools) | 0.5 |
| 2 | Tool interception + real/mock tool dispatch | 0.5 |
| 3 | Judge / rubric scoring | 0.5 |
| 4 | CLI `simulate` command + JSON output + diff against baseline | 0.5 |
| 5 | Fill persona library to 12. Create golden baselines. | 0.5 |
| 6 | Optional: Option D deterministic scripts for regression suite | 0.5 |
| 7 | Optional: Option B audio-mode runner | 1.0 |
| 8 | Optional: Option C real-Twilio nightly | 0.5 |
| **Core (1-5)** | | **2.5 days** |

---

## Immediate small-scope proposal

If you just want to start testing scenarios NOW without the full build:

**20-minute version**: a single Python script `scripts/simulate.py` that:
- Loads the attorney cold-call prompt from `app/prompts/attorney_cold_call.py`
- Defines 3 personas inline (ideal, busy skeptic, gatekeeper)
- Runs one conversation per persona using plain `chat.completions` (not Realtime — text-only)
- Prints the transcript + the final `end_call` args

No DB, no CLI, no judge — just transcripts you can read. Good enough to iterate the prompt 10× in an hour. Graduates to the full design above when you want persistence + regression testing.

Want me to ship the 20-min version right now?
