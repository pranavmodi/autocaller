# Call dispositions — GTM follow-up taxonomy

Every completed call gets an LLM-assigned disposition that tells the GTM specialist **exactly what to do next**. Separate from (and complementary to) `outcome` (what the AI declared) and `call_disposition` (the internal status derived from outcome + error).

The GTM disposition answers: *"Should we call this firm again? When? By whom? Or stop forever?"*

---

## 13 primary dispositions

Grouped by what action the GTM owner should take.

### "Win" group — something to protect
| id | disposition | meaning | follow-up action |
|---|---|---|---|
| 1 | **`meeting_booked`** | Demo on the calendar. `demo_booking_id` is non-null. | Send reminder 24h + 1h before. Confirm attendance. |
| 2 | **`hot_lead_no_booking`** | They said "yes, let's do a demo" but couldn't book live (time conflict, wanted to check calendar). | Call back the same or next day. High priority. Email a scheduling link as insurance. |

### "Pursue" group — real conversation, earned another touch
| id | disposition | meaning | follow-up action |
|---|---|---|---|
| 3 | **`warm_interest`** | Surfaced real pain, expressed openness, wants more info before committing. | Email case study + explicit follow-up in 5-7 business days. |
| 4 | **`qualifying_signal_no_commitment`** | Had a real conversation, no explicit "yes" but no "no" either. | Nurture sequence: email cadence every 2-3 weeks for 3 months. |

### "Defer" group — timing is the issue, not fit
| id | disposition | meaning | follow-up action |
|---|---|---|---|
| 5 | **`not_now_try_later`** | Clear fit but bad timing (busy trial, mid-hiring, fiscal cycle, etc.). Lead named a horizon. | Scheduled nurture on the stated horizon (e.g. `follow_up_when = "2026-07-01"`). |
| 6 | **`budget_cycle_gate`** | Would consider it but needs budget approval / next fiscal cycle. | Tag for FY-boundary follow-up (usually Q4 of current year → call Q1 of next). |

### "Retarget" group — wrong human, need a pivot
| id | disposition | meaning | follow-up action |
|---|---|---|---|
| 7 | **`wrong_target_path_captured`** | Reached non-DM but got DM's name/email/direct line. | Call the captured contact within 48h. Update lead record with DM info. |
| 8 | **`dead_end_at_firm`** | Reached non-DM, no path forward surfaced. | Park for 3 months. Research DM via LinkedIn/state bar before retrying. |

### "Close out softly" — respect the no but don't burn forever
| id | disposition | meaning | follow-up action |
|---|---|---|---|
| 9 | **`not_interested_polite`** | Soft, professional refusal. "Thanks but no thanks." | Long-horizon nurture (quarterly email for 12 months). Do NOT call back in under 6 months. |
| 10 | **`competing_solution_satisfied`** | Uses a named competitor and sounds happy. | 12-month follow-up. Track competitor. Watch for dissatisfaction signals (job changes, review sites). |

### "Close out hard" — do not touch again
| id | disposition | meaning | follow-up action |
|---|---|---|---|
| 11 | **`do_not_recontact`** | Explicit opt-out ("take me off your list"), hostile, or legal/ethical concern raised. | Add phone + firm to DNC list. Never call again. Log consent-revocation record. |
| 12 | **`bad_data`** | Wrong number / disconnected / not this firm. | Flag phone as `invalid_number`. Potentially dead-letter the lead entirely. |

### "Cannot classify yet"
| id | disposition | meaning | follow-up action |
|---|---|---|---|
| 13 | **`no_conversation`** | Voicemail, no answer, hung up <5s, AMD hit. | Standard retry cadence (existing dispatcher rules). |
| 14 | **`technical_failure`** | Our pipeline broke mid-call (OpenAI disconnect, Twilio error, etc.). | Don't count against attempt limits. Re-dial after fixing. |
| 15 | **`needs_human_review`** | AI unsure or transcript is ambiguous. | Queue for human triage. Do not auto-retry. |

---

## Additional fields per call (all LLM-filled)

### Core
| field | type | use |
|---|---|---|
| `disposition` | enum (above) | primary workflow routing |
| `follow_up_action` | enum: `confirm_demo`, `call_back_next_day`, `call_back_scheduled`, `email_case_study`, `add_to_nurture`, `research_dm`, `mark_dnc`, `mark_bad_number`, `discard`, `human_review`, `standard_retry` | what automation/human should actually do |
| `follow_up_when` | timestamp or null | earliest date to take the follow-up action |
| `follow_up_owner` | enum: `autocaller`, `sales_human`, `none` | who owns the action |
| `follow_up_note` | text (1-2 sentences) | what the human/agent should know before the next touch |
| `summary` | text (1-2 sentences) | what happened, for scanning |

### Context enriching
| field | type | use |
|---|---|---|
| `signal_flags` | string[] | `["hostile", "friendly", "busy", "decisive", "evasive", "confused", "authoritative", "junior"]` — free-form tags for filtering |
| `pain_points_discussed` | string[] | e.g. `["medical_records_retrieval", "demand_letters", "intake_volume"]` — canonicalized |
| `objections_raised` | array of `{objection, ai_response_quality}` | for the objection library (Phase C) |
| `captured_contacts` | array of `{name, title, email, phone}` | net-new people the call surfaced (usually via `mark_gatekeeper`) |
| `dm_reachability_assessment` | enum: `reached`, `path_captured`, `path_unclear`, `no_path` | feeds lead scoring loop |
| `dnc_reason` | text | populated iff disposition is `do_not_recontact` — legal audit trail |

### Quality (these are the "judge" scores from Phase A)
| field | range | meaning |
|---|---|---|
| `opening_quality` | 0-10 | permission-based, concise, honest |
| `discovery_quality` | 0-10 | asked quantifying question, listened |
| `tool_use_correctness` | 0-10 | right tool at right time, no hallucinated results |
| `objection_handling` | 0-10 | pushed back sensibly, no lies |
| `closing_quality` | 0-10 | graceful exit on yes AND on no |
| `overall` | 0-10 | would you let this AI represent your company? |
| `missed_opportunities` | string[] | what signals did the AI miss? |
| `ai_errors` | string[] | what did the AI say that was wrong/weird? |
| `recommended_prompt_edits` | string[] | targeted changes to the system prompt |

---

## Why 15 dispositions and not 5

Fewer options means less signal. "Not interested" collapsed with "would you call me in 6 months" collapsed with "take me off the list" destroys the GTM decision tree.

Why not 50? Diminishing returns past ~15 — the additional nuance lives in `signal_flags` + `follow_up_note`, which are free-form and don't require schema changes.

---

## Example rows

### A hot lead that didn't book live
```json
{
  "disposition": "hot_lead_no_booking",
  "follow_up_action": "call_back_next_day",
  "follow_up_when": "2026-04-15T14:00:00-04:00",
  "follow_up_owner": "autocaller",
  "summary": "Managing partner interested in records retrieval tooling, asked to confirm a slot tomorrow after checking calendar.",
  "signal_flags": ["friendly", "decisive", "busy"],
  "pain_points_discussed": ["medical_records_retrieval"],
  "objections_raised": [],
  "captured_contacts": [],
  "dm_reachability_assessment": "reached"
}
```

### A gatekeeper who volunteered the DM's email
```json
{
  "disposition": "wrong_target_path_captured",
  "follow_up_action": "research_dm",
  "follow_up_when": "2026-04-15T09:00:00-07:00",
  "follow_up_owner": "autocaller",
  "summary": "Legal assistant Melissa gave us partner Morrison's direct email (jmorrison@morrisonpi.com).",
  "signal_flags": ["friendly", "helpful"],
  "captured_contacts": [
    {"name": "Attorney Morrison", "title": "Managing Partner", "email": "jmorrison@morrisonpi.com", "phone": null}
  ],
  "dm_reachability_assessment": "path_captured"
}
```

### An explicit opt-out
```json
{
  "disposition": "do_not_recontact",
  "follow_up_action": "mark_dnc",
  "follow_up_when": null,
  "follow_up_owner": "none",
  "summary": "Partner asked to be removed from list; expressed frustration about cold calls.",
  "signal_flags": ["hostile"],
  "dnc_reason": "Requested removal from call list during the call (timestamp 0:42). No prior relationship."
}
```

---

## Operational guardrails

- **`do_not_recontact` is a hard-stop.** Once set, phone + firm go into a permanent DNC table. No LLM or human override without a logged audit entry.
- **`follow_up_when` must be a real future date**, never "soon" or null unless disposition is a terminal one. Prevents leads getting stuck.
- **`captured_contacts` phone/email** must be formatted (E.164 / lowercase). The autocaller LLM already does this in `lead_extractor.py`; reuse that normalizer.
- **`dnc_reason`** must cite the transcript moment that triggered it. Searchable audit trail for TCPA defense.

---

## How this ties into the rest of the system

| field | feeds loop |
|---|---|
| `disposition` | The GTM follow-up queue (new `/followups` screen on frontend, a later task) |
| `follow_up_when` | Dispatcher reconsiders the lead on or after this date |
| `signal_flags` | Objection library (Phase C) clusters patterns |
| `pain_points_discussed` | Helps match leads to case studies |
| `captured_contacts` | New lead ingest path for DMs surfaced by gatekeepers |
| `dm_reachability_assessment` | Feeds lead reranker (Phase D from `SELF_IMPROVEMENT.md`) |
| `quality scores` | Prompt A/B tests + weekly digest (Phase A → B) |

The disposition is NOT just labeling — it's what makes the pipeline self-correcting.
