# Mission Control — pulling leads into the autocaller

Mission Control (`https://mission.getpossibleminds.com`) is our upstream
system of record for US personal-injury firms. The autocaller pulls
firms from Mission Control's `/api/pif-local/firms` endpoint, LLM-extracts
one best-contact per firm, and upserts them into the local `patients`
table as leads.

This doc is the operator reference for that sync: when to run it, what
the knobs do, how de-duplication works, and how to unblock the common
"no eligible patients in queue" state.

---

## When to run it

Run `leads sync-mission` whenever the dispatcher's recent decisions
show `no_candidate: No eligible patients in queue` for more than a
minute or two while `system_enabled=true` and `system_enabled` +
`within_hours` are both green. That state means every existing lead is
inside its `min_hours_between` cooldown (default 168 h / 1 week) and
you need fresh firms.

Diagnose first:

```bash
# How many leads are eligible right now?
sudo -u postgres psql -d autocaller -tAc "
  SELECT count(*) FILTER (WHERE last_attempt_at IS NULL
                          OR last_attempt_at <= NOW() - INTERVAL '168 hours')
  FROM patients;"

# If 0, you need more firms.
```

---

## The command

Entry point: `bin/autocaller leads sync-mission` (or
`python -m app.cli leads sync-mission`, same thing).

### Full option surface

```
--tiers                  Comma-sep ICP tiers (A, B, C, or "all"). [default: A,B]
--dm-threshold           Minimum decision_maker_confidence (0-10).
                         5 = at least associate attorney.
                         4 = include paralegals who run ops.
                         3 = include receptionists at tiny firms.
                         [default: 5]
--dry-run                Extract + report only, no DB writes
--limit                  Stop after N firms [default: 500]
--page-size              Firms per Mission Control API page [default: 100]
--concurrency            Parallel LLM calls [default: 10]
--extractor-model        LLM for extraction (default: LEAD_EXTRACTOR_MODEL
                         env or gpt-4o-mini)
```

### How it decides which contact to import

For each firm Mission Control returns, an LLM (default gpt-4o-mini,
~$0.002 per firm) reads the raw record and picks the best contact to
call. It handles:

- Messy title strings ("Managing Partner, Esq., CA Bar 123456")
- Phone extensions and international formats → E.164
- Multiple phone numbers per firm → picks the direct line when present,
  falls back to the main line
- State extraction from unstructured address text
- A `decision_maker_confidence` score (0–10) for the picked contact

No regex. If the LLM can't find a reachable contact with confidence
≥ `--dm-threshold`, the firm is skipped with one of these reasons:
`unreachable` (no phone) or `below_dm_threshold`.

### Idempotency

Every lead is keyed by `mc-{pif_id}` in the `patients.patient_id`
column. Re-running `sync-mission` is safe:
- New `mc-…` IDs are inserted.
- Existing `mc-…` IDs are updated in place (name, phone, title, tags,
  practice_area refreshed from the latest Mission Control record).
- `attempt_count`, `last_attempt_at`, and `last_outcome` are preserved
  — the dispatcher's retry state is never clobbered by a re-sync.

This means you can re-run the sync nightly without worrying about
double-dialing.

---

## Recipes

### "I'm out of leads; pull more"
```bash
bin/autocaller leads sync-mission --tiers=A,B,C --dm-threshold=4 --limit=500
```
Broadens both ICP tier and DM threshold. Typical yield: 100–150 kept
leads out of 500 fetched.

### "Pull only the highest-quality partners"
```bash
bin/autocaller leads sync-mission --tiers=A --dm-threshold=7 --limit=200
```
Tighter filter — partner/managing-partner titles only. Good for a
"quality not quantity" batch.

### "Test the extractor without writing to the DB"
```bash
bin/autocaller leads sync-mission --dry-run --limit=50
```
Prints what would be kept/skipped, no DB changes. Useful for tuning
`--dm-threshold`.

### "Scale the LLM extraction faster"
```bash
bin/autocaller leads sync-mission --concurrency=20 --limit=2000
```
Higher concurrency. Each call is ~300ms latency so default 10 ≈ 3
firms/sec; 20 ≈ 6 firms/sec. Bounded by OpenAI rate limits on your
key's tier.

### "I need to see what got skipped and why"
```bash
bin/autocaller leads sync-mission --dry-run --limit=100 2>&1 | tee /tmp/sync-report.txt
grep -E "skipped|kept|inserted|updated" /tmp/sync-report.txt
```

---

## After a sync — verify

```bash
# Total leads and how many are fresh
sudo -u postgres psql -d autocaller -tAc "
  SELECT count(*) AS total,
         count(*) FILTER (WHERE last_attempt_at IS NULL) AS never_called
  FROM patients;"

# New leads land with mc- prefix; see the most recent batch
sudo -u postgres psql -d autocaller -F $'\t' -A -c "
  SELECT patient_id, name, firm_name, state, phone, title, priority_bucket
  FROM patients
  WHERE updated_at > NOW() - INTERVAL '10 minutes'
    AND patient_id LIKE 'mc-%'
  ORDER BY priority_bucket, updated_at DESC
  LIMIT 20;"

# Dispatcher should stop logging 'no_candidate' within one poll cycle (10 s default)
curl -s http://127.0.0.1:8099/api/dispatcher/status | jq '.recent_decisions[:3]'
```

---

## Troubleshooting

### "Fetched 0 firms from Mission Control"
- Check Mission Control is up: `curl -s https://mission.getpossibleminds.com/api/pif-local/firms?tier=A&limit=1`
- Check `MISSION_CONTROL_API` env var isn't overriding to a stale URL
- Network: `.env` loads cleanly, no SSL cert issues

### "Extractor results: 0 kept"
- Lower `--dm-threshold` (try 4, then 3)
- Widen `--tiers` (`A,B,C` or `all`)
- Check a sample with `--dry-run --limit=10` — the LLM might be
  skipping due to a systemic field format the extractor doesn't
  handle yet (look for `reason: unreachable` on records that actually
  have phones)

### "Inserted 0, updated N — no new firms"
- Mission Control hasn't added new firms since last sync.
- Increase `--limit` to paginate deeper into the corpus.
- Consider broadening `--tiers`.

### "Don't cold-call our own partners"
Filter out anchor firms before they land in the patient list. Currently
the only one is Precise Imaging — it was purged manually. If new
partners show up in Mission Control, add them to a skip-list in the
extractor (see `app/services/lead_extractor.py`) or purge post-sync:
```bash
sudo -u postgres psql -d autocaller -c "
  DELETE FROM patients
  WHERE firm_name ILIKE '%precise%imaging%'
  RETURNING patient_id, name, firm_name;"
```

### "Dispatcher still says no_candidate after sync"
Two other gates besides `last_attempt_at`:
- `attempt_count >= max_attempts` (default 3)
- `within_state_window` (per-state calling hours; wider by default but
  can be tuned via `per_state_hours` settings)

Check a specific lead:
```bash
sudo -u postgres psql -d autocaller -F $'\t' -A -c "
  SELECT patient_id, name, firm_name, state, attempt_count,
         last_attempt_at, last_outcome
  FROM patients ORDER BY updated_at DESC LIMIT 10;"
```

---

## Related

- `docs/cli.md` §3 — one-line reference for all lead commands
- `.claude/skills/autocaller/SKILL.md` — full autocaller operator guide
- `app/cli.py::leads_sync_mission` — the command implementation
- `app/services/lead_extractor.py` — the LLM extraction logic
