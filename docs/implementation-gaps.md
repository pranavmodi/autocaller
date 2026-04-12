# Implementation Gaps — Requirements Audit

Audit performed against all 70 test scenarios and the requirements document.
Original audit: 2026-02-23
Last updated: 2026-03-23

---

## Resolved Gaps

### Gap 1: Preferred Callback Time Not Captured — FIXED

**Requirement:** Scenario 36 (Patient not available), Requirements §Call Outcomes — Outcome 3

**Resolution:** Fully implemented end-to-end.
- `end_call` tool has `preferred_callback_time` parameter
- `CallLog` model stores the value, persisted via alembic migration
- Orchestrator logs a system transcript entry: "Preferred callback captured: {time}"
- Frontend displays it in call history rows (pen icon) and transcript modal notes
- Fallback `inferPreferredCallbackFromTranscript()` extracts it from transcript if structured field is empty

---

### Gap 2: Holiday Calendar Not Implemented — FIXED

**Requirement:** Requirements §Business Hours Enforcement, next-milestone.md Feature 6

**Resolution:** `HolidayEntry` model with recurring flag support. `_is_holiday()` / `_matching_holiday()` in `settings_provider.py` check holidays during business hours evaluation. Holiday CRUD exposed in settings API and dashboard.

---

### Gap 3: Document Upload Instructions Missing from AI Prompt — FIXED

**Requirement:** Scenario 51 (Patient asks how to upload documents), Requirements §AI Agent Capabilities — Allowed Topics

**Resolution:** Added "How to Upload Documents or ID Before Your Visit" section to the AI knowledge base in `realtime_voice.py` with patient portal URL, referral submission channels (email, text, web form), and help phone number. Sourced from precisemri.com. See TODO in code for replacing with more comprehensive instructions when available.

**Note:** The radflow360 knowledge base contains staff-facing front desk portal documentation (paper intake upload workflow). These are NOT patient-facing and must not be used for patient instructions.

---

### Gap 7: Wrong-Number Detection Uses Fragile Regex Heuristics — RESOLVED (removed)

**Requirement:** Scenario 37 (Wrong Number)

**Resolution:** Regex safety net (`looks_like_wrong_number_signal()`) removed entirely. Wrong-number detection now relies on the AI model in real time. The system prompt was strengthened with an extensive list of identity-mismatch phrasings: "wrong number", "wrong person", "not me", "I'm not that person", "you have the wrong guy", "nobody here by that name", "no one by that name", "never heard of them", "don't know who that is", "who is this for?", "no such person", "they don't live here", "that's not my name".

**Design rationale:** The AI model is the authoritative detector — it hears intent in real time and calls `end_call(reason="wrong_number")` immediately. The regex ran only at transfer time (too late) and had both false positives and false negatives.

---

### Gap 8: AI Cannot Proactively Indicate Queue Unavailability — FIXED

**Requirement:** Scenario 58 (Off-topic question, transfer not safe)

**Resolution:** Added `check_transfer_availability` function tool. The AI calls this silently before promising any transfer. The orchestrator checks queue capacity for the patient's language-specific queue and returns `{"available": true/false}`. The system prompt mandates: "NEVER call `transfer_to_scheduler` without first calling `check_transfer_availability`." If unavailable, the AI tells the patient the team is busy and offers SMS with callback info instead.

---

## Open Gaps

### Gap 4: No "system_disabled_during_call" Log Event

**Requirement:** Scenario 69 (System disabled during active call)

> "Log: system_disabled_during_call"

**Current behavior:** When an admin disables the system while a call is in progress, the active call runs to completion (correct behavior), but no special event is logged indicating the system was disabled mid-call. The dispatcher simply stops dispatching.

**Impact:** No audit trail that a call was in progress when the system was disabled.

**Suggested fix:**
- In the settings update handler (or dispatcher `stop()`), check if a call is active and log a `system_disabled_during_call` event to the call transcript

---

### Gap 5: No "hours_ended_during_call" Log Event

**Requirement:** Scenario 70 (Business hours end during active call)

> Expected: call completes normally, with logged note that hours ended

**Current behavior:** Same as Gap 4 — the call completes normally but no event is logged noting that business hours ended while the call was active.

**Impact:** No audit trail for after-hours call completion.

**Suggested fix:**
- In the dispatcher tick, if a call is active and business hours have just ended, log a `business_hours_ended_during_call` event

---

### Gap 6: Stale Queue State at Transfer Time

**Requirement:** Scenario 45 (Transfer requested, AMI now disconnected)

**Current behavior:** When the AI requests a transfer, `TransferService.execute_transfer()` reads queue state from the provider, which returns the last-polled snapshot (updated every 10 seconds by the dispatcher). If AMI disconnects between polls, the transfer check may use stale data showing AMI as connected.

**Impact:** A transfer could be attempted against a stale queue snapshot. The window is small (up to 10 seconds) and the actual Twilio transfer would likely still succeed or fail gracefully, but the safety check is not real-time.

**Severity:** Low — accepted as tolerable given the 10-second poll interval.

**Suggested fix (optional):**
- Force a fresh `queue_provider.poll()` inside `execute_transfer()` before checking capacity
