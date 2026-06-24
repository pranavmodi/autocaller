# PACKET — lead-gen daily-run TOP-UP (add N more sends to today, route overflow to Resend)

Workdir `/home/pranav/possibleos`. Orchestrator (Claude) will review, restart the
backend, and run the live top-up. **You do NOT send email, restart services, or
commit.** Build + validate only.

## Why
Today's daily run is capped at `daily_batch_size`. We want to ADD N more sends to
*today* without recomposing the existing batch. The transport layer
(`app/services/lead_gen_transport.py`, strategy `zoho_first_then_resend`) already
overflows sends past the Zoho daily cap (20) to Resend at send time — so simply
creating N more approved, scheduled sends today makes them go out via Resend
automatically. No per-channel code needed.

## Scope — additive top-up
1. **`top_up_daily_run(*, n, composer_variant_key=None, created_by="operator", run_date=None)`**
   in `app/services/lead_gen_daily.py`. It must:
   - Resolve `run_date` (default = today in the run TZ, same as the pipeline).
   - Build an **exclude set** = every `contact_id` already in *any* batch for that
     run_date (so we never double-email a contact already queued today). Query
     `LeadGenBatchItemRow` joined to that day's batches.
   - Select `n` **fresh first-touch** contacts via the same path the pipeline uses
     for fresh selection (`recommend_sequence_contacts` / `_select_contacts`),
     **excluding** the exclude set. (Follow-up supply is exhausted; this is
     first-touch.)
   - Create a **new sidecar batch** (name `Daily run <date> top-up`).
   - Compose each item with `composer_variant_key` (we will pass `ai-audit`),
     reusing `_compose_batch` / `_compose_batch_items`.
   - **Schedule into today's send window + auto-approve**, reusing the exact same
     functions the daily pipeline uses (`_schedule_drafted_items` + the
     auto-approve path). Do NOT invent new scheduling/approval/transport logic.
   - Return counts (selected, composed, held, scheduled, approved, batch_id).
2. **ai-audit bypasses the first-touch review-evidence gate.** In
   `_compose_batch_items`, the `REQUIRE_REVIEW_EVIDENCE_FIRST_TOUCH` hold currently
   applies to all first-touch items. Make it **skip the hold when the resolved
   variant is `ai-audit`** (generic AI-readiness pitch needs no firm evidence;
   review-evidence-style variants still gate). Keep it principled: a small
   "evidence-exempt variants" set (`{"ai-audit"}`) or equivalent.
3. **API:** `POST /api/lead-gen/daily-run/top-up` body `{n:int (1..40), composer_variant_key?:str}`.
   Validate the variant like the daily-run endpoint does.
4. **CLI:** `lead-gen top-up --count N [--variant ai-audit]` → posts to the
   endpoint; print the returned counts.

## Guardrails
- Touch only `app/services/lead_gen_daily.py`, `app/services/lead_gen_email_agent.py`
  (gate exemption), `app/api/lead_gen.py`, `app/cli.py`, `docs/`, `tests/`.
- **No real sends, no service restart, no commit.** Validate with `--dry`-style or
  unit tests using temp/mock data; if you must exercise compose, limit to ≤1 item.
- No new transport/scheduling/approval code — reuse the pipeline's functions.
- Update `docs/cli.md` (new-command row) + `.claude/skills/possibleos/SKILL.md`
  (mention `lead-gen top-up`).

## Validation (paste output)
- `python3 -m py_compile` the changed files.
- A test (or dry invocation) proving: exclude-set logic omits already-batched
  contacts; ai-audit first-touch is NOT held by the evidence gate; the function
  returns the expected counts shape. Do not require a live gateway.

## Finish
Report diff + validation. Orchestrator will restart the backend and run
`lead-gen top-up --count 20 --variant ai-audit` live.
