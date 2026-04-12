# Next Milestone: Complete Call Outcome Paths

## Goal

Close the remaining gaps between the requirements (`requirements.md`) and the current implementation so that all five call outcomes are fully functional end-to-end.

## Current State

The core call flow works: queue monitoring, dispatcher, call orchestrator, AI conversation, and basic transfer/end. What's missing are the **notification actions** (SMS, email) and **telephony edge-case handling** (voicemail detection, carrier failures, language-based routing) that the requirements specify for each outcome.

---

## Feature 1: SMS Notifications (Twilio SMS)

**Requirement refs:** Outcomes 1 & 3, SMS Notifications section

**What the requirements say:**
- Send SMS with callback information (no PHI) when voicemail is left
- Send SMS with callback info and main number when patient is not available
- Must not contain PHI
- Include callback number

**What exists today:**
- The AI can invoke `send_sms` as a function tool
- `sms_sent` flag exists in the call log database model
- No actual SMS sending implementation

**What needs to be built:**
- Twilio SMS provider using the Twilio SDK (`client.messages.create`)
- SMS message templates (voicemail follow-up, callback info) — no PHI
- Hook the `send_sms` function tool handler in `call_orchestrator.py` to the SMS provider
- Configuration: Twilio SMS-capable phone number, opt-out handling
- Logging of SMS delivery status

**Acceptance criteria:**
- When AI calls `send_sms` with `message_type: callback_info`, patient receives a text
- SMS contains Precise Imaging callback number, no patient health information
- `sms_sent` flag is set to true on the call log
- SMS delivery status is logged

---

## Feature 2: Email Notifications

**Requirement refs:** Outcomes 4 & 5, Email Notifications section

**What the requirements say:**
- Wrong number: email to `scheduling@precisemri.com` with subject "Scheduling Call Issue - Wrong Number (Patient ID: {ID})", including Patient ID, Order ID, Phone, Timestamp, Call ID
- Disconnected/invalid number: email with subject "Scheduling Call Issue - Invalid/Disconnected Number (Patient ID: {ID})", including Patient ID, Order ID, Phone, Timestamp, Call ID, Error/Status

**What exists today:**
- Call outcomes `wrong_number` and `failed` exist in the `CallOutcome` enum
- No email provider or templates

**What needs to be built:**
- Email provider (SMTP or SendGrid — decide based on infrastructure)
- Email templates matching the required subjects and fields
- Trigger email on `wrong_number` outcome (from AI `end_call` with reason `wrong_number`)
- Trigger email on disconnected number detection (see Feature 4)
- Configuration: SMTP credentials or SendGrid API key, recipient address

**Acceptance criteria:**
- When a call ends with `wrong_number`, scheduling team receives an email with the specified subject and fields
- When a disconnected number is detected, scheduling team receives an email with error/status details
- Emails are logged in the call record

---

## Feature 3: Voicemail Detection and Message

**Requirement refs:** Outcome 1

**What the requirements say:**
- Leave voicemail message (no PHI)
- Send SMS with callback information (depends on Feature 1)

**What exists today:**
- No voicemail/answering machine detection
- No pre-recorded voicemail message

**What needs to be built:**
- Enable Twilio Answering Machine Detection (AMD) on outbound calls
  - Use `machine_detection="DetectMessageEnd"` in the Twilio call creation
  - Handle the `AnsweredBy` callback (`machine_end_beep`, `machine_end_silence`, etc.)
- Pre-recorded or TTS voicemail message (non-PHI): "Hi, this is a call from Precise Imaging regarding scheduling. Please call us back at [number]."
- When AMD detects voicemail: play message, then hang up
- After voicemail: trigger SMS send (Feature 1)
- Set `voicemail_left` flag on call log
- When AMD detects human: proceed with normal AI conversation

**Acceptance criteria:**
- Twilio calls include AMD enabled
- When voicemail is detected, a non-PHI message is played after the beep
- Call log records `voicemail_left: true`
- SMS is sent after voicemail (if Feature 1 is complete)
- Human-answered calls proceed to AI conversation as before

---

## Feature 4: Disconnected/Invalid Number Detection

**Requirement refs:** Outcome 5

**What the requirements say:**
- Detected via carrier failure codes
- Email notification to scheduling team (depends on Feature 2)

**What exists today:**
- No carrier failure code handling

**What needs to be built:**
- Handle Twilio call status callbacks for failed calls
  - `call_status=failed` or `call_status=busy`/`call_status=no-answer` with SIP error codes
  - Twilio error codes: 32xxx series (e.g., 32009 invalid number, 32005 disconnected)
- Map carrier failure codes to `CallOutcome.FAILED` with a specific reason field
- Trigger email notification (Feature 2) with the error code/status
- Update patient record to flag the number as invalid (prevent retry)

**Acceptance criteria:**
- When Twilio reports a carrier failure, the call is logged with outcome `failed` and the error code
- Email is sent to scheduling team with error details (if Feature 2 is complete)
- Patient is not retried on a known-invalid number

---

## Feature 5: Language-Based Transfer Routing

**Requirement refs:** Language-Based Routing section, Transfer Safety section

**What the requirements say:**
- Patient language preference determines transfer destination
- Each language maps to a specific scheduling queue
- Unknown/null language defaults to English queue
- Before transferring: confirm correct language queue exists

**What exists today:**
- Patient `language` field is tracked (`en`, `es`, `zh`)
- `transfer_to_scheduler` function tool exists
- Transfer safety re-checks queue state
- No actual language-to-queue mapping or Twilio Dial to FreePBX

**What needs to be built:**
- Language-to-queue mapping configuration (e.g., `en` -> FreePBX extension/DID for English scheduling, `es` -> Spanish scheduling queue)
- When `transfer_to_scheduler` is invoked:
  1. Look up patient language
  2. Resolve target queue/extension
  3. Re-verify that specific queue has capacity (not just global)
  4. Execute Twilio `<Dial>` to bridge patient to the FreePBX queue
- Fallback: unknown language defaults to English queue
- If target queue is unavailable: inform patient, offer callback, send SMS

**Acceptance criteria:**
- English patients are transferred to the English scheduling queue
- Spanish patients are transferred to the Spanish scheduling queue
- Transfer fails gracefully if the target queue has no capacity
- Unknown language defaults to English

---

## Feature 6: Holiday Calendar

**Requirement refs:** Business Hours Enforcement section

**What the requirements say:**
- Holiday calendar support required

**What exists today:**
- Business hours with day-of-week support
- No holiday awareness

**What needs to be built:**
- Holiday table in the database (date, name, recurring flag)
- API endpoints: CRUD for holidays
- Business hours check includes holiday lookup — if today is a holiday, outbound is blocked
- Frontend: holiday management UI in settings

**Acceptance criteria:**
- Dispatcher does not place calls on configured holidays
- Admins can add/remove holidays via the dashboard

---

## Implementation Order

```
Feature 1: SMS Notifications
Feature 2: Email Notifications
    (these two are independent, can be built in parallel)
        |
        v
Feature 3: Voicemail Detection ──depends on──> Feature 1 (SMS after voicemail)
Feature 4: Disconnected Number  ──depends on──> Feature 2 (email on failure)
    (these two are independent of each other, can be built in parallel)
        |
        v
Feature 5: Language-Based Transfer Routing (independent)
Feature 6: Holiday Calendar (independent)
```

**Suggested sprint breakdown:**
- **Sprint A**: Features 1 + 2 (notification providers)
- **Sprint B**: Features 3 + 4 (telephony edge cases, now that notifications work)
- **Sprint C**: Features 5 + 6 (routing + calendar)
