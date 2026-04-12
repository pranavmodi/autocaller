# Patient Behavior Handling — Implementation Status

How the system handles each type of patient behavior/response during outbound calls.

---

## 1. No Answer / Voicemail

**Status: Implemented**

- **Twilio mode:** AMD (Answering Machine Detection) triggers `handle_twilio_amd_status()` in `call_orchestrator.py` → plays a pre-recorded voicemail message via `play_voicemail_and_hangup()` (no PHI)
- **Web mode:** Heuristic `looks_like_voicemail_signal()` detects phrases like "leave a message", "at the tone" in transcript → marks voicemail left and ends call
- **SMS:** Auto-sent on call end via `notification_service.send_sms_for_call()` with callback info (no PHI). Respects SMS opt-out and has idempotency checks to prevent duplicates.

**Files:** `call_orchestrator.py`, `twilio_voice_service.py`, `notification_service.py`, `twilio_sms_service.py`

---

## 2. Answers & Ready to Schedule

**Status: Implemented**

- AI greets patient, states purpose, asks "Is now a good time?"
- On readiness, `TransferService.execute_transfer()` re-verifies queue capacity, agent availability, and outbound-allowed status
- `resolve_transfer_queue_for_language()` maps patient language → queue (en, es, etc.; unknown defaults to English)
- Twilio `<Dial>` routes to destination (SIP or PSTN)
- If queue check fails → SMS fallback with callback info, outcome set to `CALLBACK_REQUESTED`

**Files:** `transfer_service.py`, `call_orchestrator.py`, `twilio_voice_service.py`, `realtime_voice.py`

---

## 3. Answers but Not Available Now

**Status: Implemented (with gap)**

- AI offers help with other questions, asks for preferred callback time
- `preferred_callback_time` parameter captured via `end_call` tool and persisted to `CallLog`
- SMS with callback info auto-sent
- Outcome: `CALLBACK_REQUESTED`

**Gap:** Preferred callback time is captured in DB but not yet surfaced in the dashboard UI.

**Files:** `call_orchestrator.py`, `notification_service.py`, `twilio_sms_service.py`, `call_log.py`

---

## 4. Wrong Number

**Status: Implemented**

- **Primary (AI):** AI instructed to call `end_call(reason="wrong_number")` immediately upon detection
- **Safety net (server-side):** `TransferService.recent_patient_indicates_wrong_number()` runs regex checks ("wrong number", "wrong person", "not me", etc.) before any transfer — blocks transfer if detected
- **Email:** `send_wrong_number_email()` sends notification to scheduling team with subject "Scheduling Call Issue - Wrong Number (Patient ID: {ID})" including patient_id, order_id, phone, call_id, timestamp
- Idempotent: email only sent once per call_id

**Files:** `call_orchestrator.py`, `transfer_service.py`, `notification_service.py`, `email_notification_service.py`, `realtime_voice.py`

---

## 5. Invalid/Disconnected Number

**Status: Implemented**

- `CarrierFailureHandler.handle_twilio_call_status()` receives Twilio status callbacks
- Detects failures via known error codes (32005 disconnected, 32009 invalid) and SIP codes (404, 410, 484, 604)
- Text heuristics: "disconnected", "invalid", "not in service", etc.
- Patient flagged `invalid_number` via `mark_patient_invalid_number()` to prevent retries
- **Email:** `send_disconnected_number_email()` sent to scheduling team with error/status details

**Files:** `carrier_failure_service.py`, `call_orchestrator.py`, `notification_service.py`, `email_notification_service.py`

---

## 6. Asks Allowed Questions

**Status: Implemented**

Knowledge base embedded in `SYSTEM_INSTRUCTIONS` in `realtime_voice.py` covering:
- Office hours (Mon-Fri 7 AM-7 PM, Sat 8 AM-4 PM, Closed Sunday)
- 3 locations with parking/transit details (Downtown LA, Burbank, Long Beach)
- What to bring (photo ID, insurance card, referral, medication list, prior imaging)
- MRI prep, scan duration, scheduling process, insurance/payment, after-scan info

AI answers directly, keeping responses short (under 2 sentences).

**Files:** `realtime_voice.py`

---

## 7. Asks Prohibited/Out-of-Scope Questions

**Status: Implemented (with gap)**

- Not allowed: medical questions, billing disputes, test results, diagnoses
- AI says "I'm not able to help with that" and offers to transfer to a human
- Transfer goes through the same safety check (`execute_transfer()`)
- If transfer unsafe → SMS fallback with callback number, outcome `CALLBACK_REQUESTED`

**Gap:** AI always optimistically offers transfer before checking availability. No `check_transfer_availability` tool exists yet — a future improvement would let the AI proactively adjust its language based on queue status.

**Files:** `call_orchestrator.py`, `transfer_service.py`, `notification_service.py`, `realtime_voice.py`

---

## Transfer Safety

**Status: Implemented**

Before any transfer, `TransferService.check_capacity()` verifies:
1. Target queue exists (`find_queue_by_name`)
2. Available agents ≥ 1
3. Outbound is still allowed

If any check fails:
- Transfer blocked
- SMS with callback info sent
- Call ends as `CALLBACK_REQUESTED`
- Event logged in transcript

**Gap:** Queue state polled via AMI every ~10 seconds, so up to 10-second staleness window at transfer time.

**Files:** `transfer_service.py`, `twilio_voice_service.py`, `queue_provider.py`
