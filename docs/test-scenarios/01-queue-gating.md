# Queue Gating Scenarios

These scenarios test the queue protection logic that ensures outbound calls never interfere with inbound capacity.

---

## Scenario 1: Quiet queue, agents available

**Description**: Ideal conditions for outbound calling.

| Component | State |
|-----------|-------|
| System Settings | `system_enabled: true`, `business_hours.enabled: false` (or within hours) |
| Queue Thresholds | `calls_waiting_threshold: 1`, `oldest_wait_threshold_seconds: 30`, `stable_polls_required: 3` |
| Queue State | `agents_available: 2`, `agents_logged_in: 3`, `calls_waiting: 0`, `oldest_wait_seconds: 0`, `stable_polls_count: 3`, `ami_connected: true` |
| Active Call | `call_active: false` |
| Patient Queue | At least 1 eligible patient |

**Expected**: Outbound calls allowed. System selects highest priority patient.

---

## Scenario 2: No agents available (all logged out)

**Description**: No agents are logged into the scheduling queues.

| Component | State |
|-----------|-------|
| System Settings | `system_enabled: true` |
| Queue Thresholds | Default values |
| Queue State | `agents_available: 0`, `agents_logged_in: 0`, `calls_waiting: 0`, `oldest_wait_seconds: 0`, `ami_connected: true` |
| Active Call | `call_active: false` |

**Expected**: Outbound blocked. Reason: "No agents available to handle transfers."

---

## Scenario 3: No agents available (all on calls)

**Description**: Agents are logged in but all currently handling calls.

| Component | State |
|-----------|-------|
| System Settings | `system_enabled: true` |
| Queue Thresholds | Default values |
| Queue State | `agents_available: 0`, `agents_logged_in: 4`, `calls_waiting: 0`, `oldest_wait_seconds: 0`, `ami_connected: true` |
| Active Call | `call_active: false` |

**Expected**: Outbound blocked. Reason: "No agents available to handle transfers."

---

## Scenario 4: No agents available (all paused)

**Description**: Agents are logged in but all in paused/break status.

| Component | State |
|-----------|-------|
| System Settings | `system_enabled: true` |
| Queue Thresholds | Default values |
| Queue State | `agents_available: 0`, `agents_logged_in: 3`, `calls_waiting: 0`, `oldest_wait_seconds: 0`, `ami_connected: true` |
| Active Call | `call_active: false` |

**Expected**: Outbound blocked. Reason: "No agents available to handle transfers."

---

## Scenario 5: Calls waiting exceeds threshold

**Description**: Too many inbound calls waiting in queue.

| Component | State |
|-----------|-------|
| System Settings | `system_enabled: true` |
| Queue Thresholds | `calls_waiting_threshold: 1` |
| Queue State | `agents_available: 2`, `agents_logged_in: 3`, `calls_waiting: 3`, `oldest_wait_seconds: 15`, `ami_connected: true` |
| Active Call | `call_active: false` |

**Expected**: Outbound blocked. Reason: "Queue has calls waiting. Outbound paused."

---

## Scenario 6: Oldest wait time exceeds threshold

**Description**: A caller has been waiting too long.

| Component | State |
|-----------|-------|
| System Settings | `system_enabled: true` |
| Queue Thresholds | `oldest_wait_threshold_seconds: 30` |
| Queue State | `agents_available: 2`, `agents_logged_in: 3`, `calls_waiting: 1`, `oldest_wait_seconds: 45`, `ami_connected: true` |
| Active Call | `call_active: false` |

**Expected**: Outbound blocked. Reason: "Queue has calls waiting. Outbound paused."

---

## Scenario 7: Conditions met but not stable (1/3 polls)

**Description**: Queue just became quiet, hysteresis not satisfied.

| Component | State |
|-----------|-------|
| System Settings | `system_enabled: true` |
| Queue Thresholds | `stable_polls_required: 3` |
| Queue State | `agents_available: 2`, `calls_waiting: 0`, `oldest_wait_seconds: 0`, `stable_polls_count: 1`, `ami_connected: true` |
| Active Call | `call_active: false` |

**Expected**: Outbound blocked. Reason: "Waiting for stable conditions (1/3 polls)."

---

## Scenario 8: Conditions met but not stable (2/3 polls)

**Description**: Queue has been quiet for 2 polling cycles.

| Component | State |
|-----------|-------|
| System Settings | `system_enabled: true` |
| Queue Thresholds | `stable_polls_required: 3` |
| Queue State | `agents_available: 2`, `calls_waiting: 0`, `oldest_wait_seconds: 0`, `stable_polls_count: 2`, `ami_connected: true` |
| Active Call | `call_active: false` |

**Expected**: Outbound blocked. Reason: "Waiting for stable conditions (2/3 polls)."

---

## Scenario 9: Conditions were stable, then queue gets busy

**Description**: Queue was allowing outbound, then inbound calls arrive.

| Component | State (Before) |
|-----------|-------|
| Queue State | `stable_polls_count: 3`, `calls_waiting: 0`, `outbound_allowed: true` |

| Component | State (After inbound calls arrive) |
|-----------|-------|
| Queue State | `calls_waiting: 2`, `stable_polls_count: 0`, `outbound_allowed: false` |

**Expected**: Stable polls reset to 0. Outbound immediately blocked.

---

## Scenario 10: AMI connection lost

**Description**: Connection to FreePBX/Asterisk fails.

| Component | State |
|-----------|-------|
| System Settings | `system_enabled: true` |
| Queue State | `ami_connected: false`, `outbound_allowed: false` |
| Active Call | `call_active: false` |

**Expected**: Outbound immediately blocked (fail-closed). Reason: "AMI connection lost. Outbound disabled for safety."

---

## Scenario 11: AMI connection recovered

**Description**: Connection to FreePBX/Asterisk restored after failure.

| Component | State (Before) |
|-----------|-------|
| Queue State | `ami_connected: false`, `stable_polls_count: 0` |

| Component | State (After recovery) |
|-----------|-------|
| Queue State | `ami_connected: true`, `stable_polls_count: 0` |

**Expected**: Outbound remains blocked until 3 consecutive good polls complete. System restarts stability counting from 0.

---

## Scenario 12: One outbound call already active

**Description**: AI is currently on a call with a patient.

| Component | State |
|-----------|-------|
| System Settings | `system_enabled: true` |
| Queue State | `agents_available: 2`, `calls_waiting: 0`, `stable_polls_count: 3`, `ami_connected: true` |
| Active Call | `call_active: true`, `patient_id: "P001"` |

**Expected**: No additional outbound calls initiated until current call ends.
