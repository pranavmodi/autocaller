# Combined / Complex Scenarios

These scenarios test multiple rules interacting together.

---

## Scenario 66: P1 patient exists but at max attempts

**Description**: Highest priority patient is exhausted.

| Component | State |
|-----------|-------|
| Patient A | `priority_bucket: 1`, `attempt_count: 3` (max) |
| Patient B | `priority_bucket: 1`, `attempt_count: 1` |
| Patient C | `priority_bucket: 2`, `attempt_count: 0` |

**Expected**: System skips Patient A, calls Patient B (P1, eligible).

---

## Scenario 67: All P1 patients exhausted or in cooldown

**Description**: Must fall back to lower priority.

| Component | State |
|-----------|-------|
| Patient A | `priority_bucket: 1`, `attempt_count: 3` (maxed out) |
| Patient B | `priority_bucket: 1`, `last_attempt_at: 2 hours ago` (in cooldown) |
| Patient C | `priority_bucket: 2`, `attempt_count: 0` |
| Patient D | `priority_bucket: 3`, `attempt_count: 1` |

**Expected**: System calls Patient C (P2, first eligible lower priority).

---

## Scenario 68: System enabled mid-business-hours

**Description**: Admin turns on system at 2 PM.

| Component | State (Before) |
|-----------|-------|
| System Settings | `system_enabled: false` |
| Current Time | 2:00 PM (within business hours) |

| Component | State (After Enable) |
|-----------|-------|
| System Settings | `system_enabled: true` |
| Queue State | All conditions met, `stable_polls_count: 3` |

**Expected**: Outbound calls begin immediately (no warm-up needed if queue already stable).

---

## Scenario 69: System disabled during active call

**Description**: Admin turns off system while call in progress.

| Component | State (During Call) |
|-----------|-------|
| Active Call | `call_active: true` |
| System Settings | `system_enabled: true` |

| Component | State (Admin Disables) |
|-----------|-------|
| System Settings | `system_enabled: false` |
| Active Call | Still `call_active: true` |

**Expected**:
1. Current call completes normally (including transfer if appropriate)
2. No new outbound calls initiated after current call ends
3. `can_make_calls: false` for subsequent checks

---

## Scenario 70: Business hours end during active call

**Description**: Clock strikes 5 PM during conversation.

| Component | State (4:58 PM) |
|-----------|-------|
| Active Call | `call_active: true` |
| Business Hours | `end_time: "17:00"` |

| Component | State (5:01 PM) |
|-----------|-------|
| Active Call | Still `call_active: true` |
| Business Hours | Now outside hours |

**Expected**:
1. Current call completes normally
2. Transfer still allowed if conditions met (don't strand patient)
3. No new outbound calls after 5:00 PM
4. `is_within_business_hours: false` for subsequent checks
