# Call Outcome Scenarios

These scenarios test the handling of different call outcomes including voicemail, transfers, wrong numbers, and disconnected lines.

---

## Scenario 34: No answer, goes to voicemail

**Description**: Patient doesn't answer, voicemail detected.

| Component | State |
|-----------|-------|
| Call State | `status: "no-answer"` or `status: "voicemail-detected"` |
| Twilio | AMD (Answering Machine Detection) returns `machine_start` |

**Expected Actions**:
1. Play pre-recorded voicemail message (no PHI)
2. Send SMS with callback number (no PHI)
3. Log outcome: `voicemail`
4. Update patient: `attempt_count++`, `last_attempt_at: now`, `ai_called_before: true`

---

## Scenario 35: Patient answers, ready to schedule

**Description**: Patient wants to schedule now.

| Component | State |
|-----------|-------|
| Call State | `status: "in-progress"` |
| AI Conversation | Patient says "Yes, I can schedule now" |
| Queue State (at transfer time) | `agents_available: 2`, `calls_waiting: 0` |

**Expected Actions**:
1. AI confirms transfer
2. Re-check queue conditions (safe)
3. Execute transfer to appropriate language queue
4. Log outcome: `transferred`
5. Update patient: `attempt_count++`, `ai_called_before: true`

---

## Scenario 36: Patient answers, not a good time

**Description**: Patient can't talk right now.

| Component | State |
|-----------|-------|
| Call State | `status: "in-progress"` |
| AI Conversation | Patient says "Can you call me back later?" or "Not a good time" |

**Expected Actions**:
1. AI acknowledges, offers callback options
2. AI asks for preferred callback time (optional)
3. Send SMS with callback number and main scheduling line
4. End call politely
5. Log outcome: `callback_requested`
6. Update patient: `attempt_count++`, `ai_called_before: true`

---

## Scenario 37: Patient says "wrong number"

**Description**: Phone number doesn't belong to patient.

| Component | State |
|-----------|-------|
| Call State | `status: "in-progress"` |
| AI Conversation | Person says "Wrong number" or "I'm not [patient name]" |

**Expected Actions**:
1. AI apologizes: "I'm sorry for the confusion, goodbye"
2. End call immediately
3. Send email to scheduling@precisemri.com with:
   - Subject: "Scheduling Call Issue - Wrong Number (Patient ID: {ID})"
   - Body: Patient ID, Order ID, Phone, Timestamp, Call ID
4. Log outcome: `wrong_number`
5. Flag patient for manual review

---

## Scenario 38: Carrier reports disconnected number

**Description**: Twilio returns carrier error for disconnected line.

| Component | State |
|-----------|-------|
| Twilio Response | `status: "failed"`, `error_code: 21211` (Invalid phone number) |
| Call State | Never connected |

**Expected Actions**:
1. Send email to scheduling@precisemri.com with:
   - Subject: "Scheduling Call Issue - Invalid/Disconnected Number (Patient ID: {ID})"
   - Body: Patient ID, Order ID, Phone, Timestamp, Error Code, Carrier Message
2. Log outcome: `disconnected_number`
3. Flag patient for manual review (do not retry)

---

## Scenario 39: Carrier reports invalid number

**Description**: Phone number format invalid or unroutable.

| Component | State |
|-----------|-------|
| Twilio Response | `status: "failed"`, `error_code: 21214` (Invalid destination) |
| Call State | Never connected |

**Expected Actions**:
1. Send email to scheduling@precisemri.com
2. Log outcome: `invalid_number`
3. Flag patient for manual review (do not retry)

---

## Scenario 40: Patient answers, asks operational question

**Description**: Patient has a question AI can answer.

| Component | State |
|-----------|-------|
| Call State | `status: "in-progress"` |
| AI Conversation | Patient asks "What are your hours?" or "What should I bring?" |

**Expected Actions**:
1. AI provides answer from knowledge base
2. AI offers: "Is there anything else I can help with, or would you like to schedule your appointment?"
3. Continue conversation flow based on response

---

## Scenario 41: Patient answers, asks medical question

**Description**: Patient asks something AI cannot answer.

| Component | State |
|-----------|-------|
| Call State | `status: "in-progress"` |
| AI Conversation | Patient asks "What did my test results show?" or "Should I be worried about the findings?" |
| Queue State | `agents_available: 2` (transfer safe) |

**Expected Actions**:
1. AI declines: "I'm not able to discuss medical information, but I can connect you with our scheduling team who can help direct your question."
2. Offer transfer to human
3. If accepted and safe, execute transfer
4. Log that medical question was asked
