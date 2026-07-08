# PACKET — demand-driven per-DM LinkedIn resolver (Option 1)

Workdir: `/home/pranav/possibleos`. Read first: `app/services/firm_contacts_service.py`
(firm_contacts model + linkedin_url), the `contacts` typer group in `app/cli.py`
(`contacts backfill/list`), how `app/services/post_call_transcribe.py` /
`ivr_navigator.py` construct `AsyncOpenAI`, `docs/cli.md` §contacts, and the
CLI-parity golden rule in `CLAUDE.md`. For the web_search call pattern, see how
`/home/pranav/ai-visibility/app/services/scan_runner.py` calls
`client.responses.create(model=..., tools=[{"type":"web_search", ...}], input=...)`.

You are Codex. Additive only. No commit/push, no service restarts. In tests,
**inject/monkeypatch the OpenAI client — no live web_search calls.**

## Why
LinkedIn URLs are near-empty for our targets because the enrichment path that
runs (`research_firm_profile_once`) doesn't hunt LinkedIn. Rather than re-enrich
3,800 firms, resolve LinkedIn **on demand, per decision-maker**, only for the
handful we actually contact — one targeted web search that writes back to
`firm_contacts.linkedin_url`, so the (future) LinkedIn console and any consumer
upgrade from Google-fallback to a direct profile link, and coverage compounds
where we work.

## Scope

### 1. Service — `app/services/linkedin_resolver.py` (new)
- `async resolve_linkedin_for_contact(contact_id: str, *, force: bool=False,
  client=None) -> dict`:
  - Load the `firm_contacts` row (name, title, email, pif_id). Resolve the firm
    name + location from the pif mirror (`PifFirmRow` / research_data) like the
    contacts service already does.
  - **Idempotent:** if `linkedin_url` already set and not `force`, return
    `{"status":"skipped","linkedin_url":<existing>}` with no API call.
  - Build a tight query and call OpenAI **Responses `web_search`** (model env
    `LINKEDIN_RESOLVER_MODEL`, default `gpt-4o-mini`; key from `OPENAI_API_KEY`;
    `AsyncOpenAI` injected for tests). Prompt (system + user), e.g.:
    "Find the personal LinkedIn profile URL for **{name}**, {title} at
    **{firm}**{, in {city}}. Return ONLY a JSON object
    `{\"linkedin_url\": \"https://www.linkedin.com/in/...\"}` or
    `{\"linkedin_url\": null}` if you cannot confidently identify the specific
    person. Never return a company page (/company/), a search page, or
    explanatory text."
  - **Validate** the returned URL: must match `^https?://([a-z]+\.)?linkedin\.com/in/`
    (personal profile), else treat as null. Reject `/company/`, non-linkedin,
    and any non-URL text.
  - On a valid URL: write `firm_contacts.linkedin_url` (+ bump updated_at),
    return `{"status":"resolved","linkedin_url":...,"model":...}`. On null:
    return `{"status":"not_found"}` and leave the field untouched.
- `async resolve_linkedin_for_batch(batch_id: str, *, force=False,
  only_decision_makers: bool=True, limit: int=25, client=None) -> dict`:
  resolve every contact in a lead-gen batch that lacks a `linkedin_url`
  (optionally only titled/decision-maker personas), rate-aware (small delay
  between calls), returns per-contact results + a summary. Never exceed `limit`
  live calls in one invocation.

### 2. REST (`app/api/` — the contacts router, or lead_gen if that's where
contact endpoints live; match the existing pattern)
- `POST /api/contacts/{contact_id}/resolve-linkedin` body `{force?:bool}`.
- `POST /api/lead-gen/batches/{batch_id}/resolve-linkedin` body
  `{force?:bool, only_decision_makers?:bool, limit?:int}`.

### 3. CLI (under the existing `contacts` group — CLI parity)
- `contacts resolve-linkedin <contact_id> [--force] [--json]` -> prints the
  resolved URL / skipped / not_found.
- `contacts resolve-linkedin-batch <batch_id> [--force] [--all] [--limit N]
  [--json]` -> `--all` includes non-DM staff; default DMs only. Prints a table:
  contact, status, url.
- Drive REST on loopback, matching how other `contacts`/`lead-gen` subcommands
  call the API.

### 4. Docs (golden rule)
- `docs/cli.md`: two rows in the §3 new-command table; a §10 recipe "resolve
  LinkedIn profiles for a wave's decision-makers before LinkedIn outreach".
- `.claude/skills/possibleos/SKILL.md`: add the two commands to the contacts
  section (orchestrator syncs the openclaw copy).

## Guardrails (hard)
- No live OpenAI calls in tests — inject a fake client returning canned
  JSON; cover: valid /in/ URL written; company-page/non-linkedin/explanatory
  text rejected → not_found; idempotent skip when already set; force re-resolves;
  batch resolves only missing + respects limit + DM-only default.
- Only ever write a validated personal `/in/` URL; never overwrite a non-empty
  `linkedin_url` unless `--force`.
- Additive; do not change enrichment, sync, or the firm_contacts schema beyond
  reading/writing the existing `linkedin_url` column. No commit/push, no restart.
- Do not print/log the OpenAI key.

## Validation (run, report)
- `pytest tests/ -q -k linkedin` (new `tests/test_linkedin_resolver.py`) green,
  covering the cases above with an injected fake client.
- `python3 -c "import app.services.linkedin_resolver, app.cli"` clean.
- Do NOT run a live resolution (orchestrator does live verification).

## Report (end of run)
Files changed, the two command signatures, the URL-validation regex, the
model/env used, test list, and STOP.
