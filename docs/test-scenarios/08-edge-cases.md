# Edge Case / Failure Scenarios

These scenarios test error handling, failures, and edge conditions.

---

## Scenario 59: Call in progress when queue becomes busy

**Description**: Queue conditions change during active call.

| Component | State (Call Start) |
|-----------|-------|
| Queue State | `calls_waiting: 0`, `outbound_allowed: true` |
| Active Call | `call_active: true` |

| Component | State (Mid-Call) |
|-----------|-------|
| Queue State | `calls_waiting: 5`, `outbound_allowed: false` |
| Active Call | Still `call_active: true` |

**Expected**:
1. Current call continues uninterrupted
2. No new outbound calls initiated
3. Transfer safety check will block transfer if patient wants to schedule
4. Next candidate selection waits for queue to calm

---

## Scenario 60: Twilio API error during call initiation

**Description**: Twilio fails to place call.

| Component | State |
|-----------|-------|
| Twilio Response | HTTP 500 or timeout |
| Patient | Selected for outbound call |

**Expected**:
1. Log error with Twilio error code/message
2. Do NOT count as attempt against patient
3. Retry with exponential backoff (or skip to next patient)
4. Alert if persistent failures

---

## Scenario 61: OpenAI connection drops mid-call

**Description**: AI service becomes unavailable during conversation.

| Component | State |
|-----------|-------|
| Active Call | `call_active: true`, conversation in progress |
| OpenAI WebSocket | Connection lost |

**Expected**:
1. Play fallback message: "I apologize, we're experiencing technical difficulties. Please call us back at [number]."
2. End call gracefully
3. Send SMS with callback info
4. Log outcome: `technical_error`
5. Do count as attempt (call was connected)

---

## Scenario 62: SMS sending fails

**Description**: Twilio SMS API returns error.

| Component | State |
|-----------|-------|
| Call Outcome | `voicemail` (requires SMS) |
| Twilio SMS Response | Error (rate limit, invalid number, etc.) |

**Expected**:
1. Log SMS failure
2. Queue SMS for retry
3. Call outcome still logged normally
4. Alert if persistent SMS failures

---

## Scenario 63: Email notification fails

**Description**: Cannot send email to scheduling team.

| Component | State |
|-----------|-------|
| Call Outcome | `wrong_number` (requires email) |
| Email Service | SMTP error or timeout |

**Expected**:
1. Log email failure
2. Queue email for retry
3. Call outcome still logged normally
4. Store notification in pending queue
5. Alert if persistent email failures

---

## Scenario 64: Patient data unavailable

**Description**: Cannot fetch patient candidates.

| Component | State |
|-----------|-------|
| Patient Database | Connection error or timeout |
| Queue State | All conditions met |

**Expected**:
1. Cannot select outbound candidates
2. Log database error
3. Outbound calling paused until data available
4. Retry database connection with backoff

---

## Scenario 65: Multiple threshold changes during a call

**Description**: Admin changes thresholds while call active.

| Component | State (Call Start) |
|-----------|-------|
| Queue Thresholds | `calls_waiting_threshold: 1` |
| Active Call | `call_active: true` |

| Component | State (Mid-Call - Admin Change) |
|-----------|-------|
| Queue Thresholds | `calls_waiting_threshold: 3` |

**Expected**:
1. Current call unaffected
2. Transfer safety check uses NEW thresholds
3. Next outbound decision uses NEW thresholds
