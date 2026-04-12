# Transfer Safety Scenarios

These scenarios test the safety checks performed before transferring a patient to a live agent.

---

## Scenario 42: Transfer requested, queue still calm

**Description**: Conditions remain favorable at transfer time.

| Component | State (at call start) |
|-----------|-------|
| Queue State | `agents_available: 3`, `calls_waiting: 0` |

| Component | State (at transfer request) |
|-----------|-------|
| Queue State | `agents_available: 2`, `calls_waiting: 0` |

**Expected**: Transfer executes successfully to appropriate language queue.

---

## Scenario 43: Transfer requested, queue now busy

**Description**: Inbound calls arrived during AI conversation.

| Component | State (at call start) |
|-----------|-------|
| Queue State | `agents_available: 3`, `calls_waiting: 0` |

| Component | State (at transfer request) |
|-----------|-------|
| Queue State | `agents_available: 2`, `calls_waiting: 4` |

**Expected Actions**:
1. Do NOT transfer
2. AI says: "I apologize, it looks like our scheduling team is currently assisting other patients. Can I have someone call you back shortly?"
3. Offer callback window
4. Send SMS with callback info
5. Log outcome: `transfer_blocked_queue_busy`

---

## Scenario 44: Transfer requested, no agents now available

**Description**: All agents became busy during conversation.

| Component | State (at call start) |
|-----------|-------|
| Queue State | `agents_available: 2`, `calls_waiting: 0` |

| Component | State (at transfer request) |
|-----------|-------|
| Queue State | `agents_available: 0`, `calls_waiting: 0` |

**Expected Actions**:
1. Do NOT transfer
2. AI apologizes, offers callback
3. Send SMS
4. Log outcome: `transfer_blocked_no_agents`

---

## Scenario 45: Transfer requested, AMI now disconnected

**Description**: Lost connection to queue monitoring during call.

| Component | State (at call start) |
|-----------|-------|
| Queue State | `ami_connected: true`, `agents_available: 2` |

| Component | State (at transfer request) |
|-----------|-------|
| Queue State | `ami_connected: false` |

**Expected Actions**:
1. Do NOT transfer (cannot verify safety)
2. AI apologizes, offers callback
3. Send SMS
4. Log outcome: `transfer_blocked_ami_down`

---

## Scenario 46: Transfer to English queue succeeds

**Description**: English-speaking patient successfully transferred.

| Component | State |
|-----------|-------|
| Patient | `language: "en"` |
| Queue State | `agents_available: 2` in `scheduling_en` |
| Transfer Target | `scheduling_en` queue |

**Expected**:
1. Call transferred to `scheduling_en`
2. Patient hears hold music/queue message
3. Agent in EN queue receives call
4. Log: `transfer_success`, `transfer_queue: "scheduling_en"`

---

## Scenario 47: Transfer to Spanish queue succeeds

**Description**: Spanish-speaking patient successfully transferred.

| Component | State |
|-----------|-------|
| Patient | `language: "es"` |
| Queue State | `agents_available: 1` in `scheduling_es` |
| Transfer Target | `scheduling_es` queue |

**Expected**:
1. Call transferred to `scheduling_es`
2. Patient hears Spanish hold message
3. Spanish-speaking agent receives call
4. Log: `transfer_success`, `transfer_queue: "scheduling_es"`
