# Retry Control Scenarios

These scenarios test the retry limits and cooldown logic for patient call attempts.

---

## Scenario 29: Patient at max attempts

**Description**: Patient has reached the retry limit.

| Component | State |
|-----------|-------|
| System Config | `max_attempts_per_patient: 3` |
| Patient | `attempt_count: 3`, `priority_bucket: 1` |
| Queue State | All conditions met |

**Expected**: Patient skipped. Not eligible for outbound call.

---

## Scenario 30: Patient called less than 6 hours ago

**Description**: Patient in cooldown period.

| Component | State |
|-----------|-------|
| System Config | `min_hours_between_attempts: 6` |
| Patient | `attempt_count: 1`, `last_attempt_at: "2024-01-15T10:00:00"` |
| Current Time | 2024-01-15T14:00:00 (4 hours later) |

**Expected**: Patient skipped (in cooldown). Not eligible until 4:00 PM.

---

## Scenario 31: Patient called exactly 6 hours ago

**Description**: Patient cooldown just expired.

| Component | State |
|-----------|-------|
| System Config | `min_hours_between_attempts: 6` |
| Patient | `attempt_count: 1`, `last_attempt_at: "2024-01-15T08:00:00"` |
| Current Time | 2024-01-15T14:00:00 (6 hours later) |

**Expected**: Patient eligible for outbound call.

---

## Scenario 32: Patient never called before

**Description**: Fresh patient, no prior attempts.

| Component | State |
|-----------|-------|
| Patient | `attempt_count: 0`, `last_attempt_at: null`, `ai_called_before: false` |

**Expected**: Patient eligible for outbound call.

---

## Scenario 33: Patient has 2 attempts, last was 8 hours ago

**Description**: Patient eligible with prior attempts.

| Component | State |
|-----------|-------|
| System Config | `max_attempts_per_patient: 3`, `min_hours_between_attempts: 6` |
| Patient | `attempt_count: 2`, `last_attempt_at: "2024-01-15T06:00:00"` |
| Current Time | 2024-01-15T14:00:00 (8 hours later) |

**Expected**: Patient eligible for outbound call (under max, past cooldown).
