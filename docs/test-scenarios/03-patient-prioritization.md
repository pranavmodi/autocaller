# Patient Prioritization Scenarios

These scenarios test the patient selection logic including priority buckets, tie-breakers, and language routing.

---

## Scenario 19: P1 patient exists (abandoned + no AI call)

**Description**: Highest priority patient available.

| Component | State |
|-----------|-------|
| Patient 1 | `priority_bucket: 1`, `has_abandoned_before: true`, `ai_called_before: false`, `attempt_count: 0` |
| Patient 2 | `priority_bucket: 3`, `has_abandoned_before: false`, `ai_called_before: false` |
| Queue State | All conditions met |

**Expected**: System calls Patient 1 (P1) first.

---

## Scenario 20: P1 and P2 patients exist

**Description**: Multiple priority levels in queue.

| Component | State |
|-----------|-------|
| Patient 1 | `priority_bucket: 2`, `has_abandoned_before: true`, `ai_called_before: true` |
| Patient 2 | `priority_bucket: 1`, `has_abandoned_before: true`, `ai_called_before: false` |
| Patient 3 | `priority_bucket: 3` |
| Queue State | All conditions met |

**Expected**: System calls Patient 2 (P1) before Patient 1 (P2).

---

## Scenario 21: Multiple P1 patients with different due dates

**Description**: Tie-breaker by due date.

| Component | State |
|-----------|-------|
| Patient A | `priority_bucket: 1`, `due_by: "2024-01-15"` |
| Patient B | `priority_bucket: 1`, `due_by: "2024-01-12"` |
| Patient C | `priority_bucket: 1`, `due_by: "2024-01-18"` |
| Queue State | All conditions met |

**Expected**: System calls Patient B (oldest due date: Jan 12) first.

---

## Scenario 22: Multiple P1 patients, same due date, different order dates

**Description**: Tie-breaker by order creation date.

| Component | State |
|-----------|-------|
| Patient A | `priority_bucket: 1`, `due_by: "2024-01-15"`, `order_created: "2024-01-10"` |
| Patient B | `priority_bucket: 1`, `due_by: "2024-01-15"`, `order_created: "2024-01-08"` |
| Patient C | `priority_bucket: 1`, `due_by: "2024-01-15"`, `order_created: "2024-01-11"` |
| Queue State | All conditions met |

**Expected**: System calls Patient B (oldest order: Jan 8) first.

---

## Scenario 23: Multiple P1 patients, same dates, different attempt counts

**Description**: Tie-breaker by attempt count.

| Component | State |
|-----------|-------|
| Patient A | `priority_bucket: 1`, `due_by: "2024-01-15"`, `order_created: "2024-01-10"`, `attempt_count: 2` |
| Patient B | `priority_bucket: 1`, `due_by: "2024-01-15"`, `order_created: "2024-01-10"`, `attempt_count: 0` |
| Patient C | `priority_bucket: 1`, `due_by: "2024-01-15"`, `order_created: "2024-01-10"`, `attempt_count: 1` |
| Queue State | All conditions met |

**Expected**: System calls Patient B (0 attempts) first.

---

## Scenario 24: Only P4 patients exist

**Description**: Lowest priority patients only.

| Component | State |
|-----------|-------|
| Patient A | `priority_bucket: 4`, `has_abandoned_before: false`, `ai_called_before: false`, `has_called_in_before: false` |
| Patient B | `priority_bucket: 4` |
| Queue State | All conditions met |

**Expected**: System calls P4 patients (sorted by due date, order date, attempt count).

---

## Scenario 25: No patients in queue

**Description**: Empty outbound queue.

| Component | State |
|-----------|-------|
| Patient Queue | Empty (0 patients) |
| Queue State | All conditions met |

**Expected**: No outbound calls made. System idles.

---

## Scenario 26: Patient has language=EN

**Description**: English-speaking patient.

| Component | State |
|-----------|-------|
| Patient | `language: "en"`, `priority_bucket: 1` |
| FreePBX Queues | `scheduling_en`, `scheduling_es` available |

**Expected**: On transfer, route to `scheduling_en` queue.

---

## Scenario 27: Patient has language=ES

**Description**: Spanish-speaking patient.

| Component | State |
|-----------|-------|
| Patient | `language: "es"`, `priority_bucket: 1` |
| FreePBX Queues | `scheduling_en`, `scheduling_es` available |

**Expected**: On transfer, route to `scheduling_es` queue.

---

## Scenario 28: Patient has language=null/unknown

**Description**: No language preference set.

| Component | State |
|-----------|-------|
| Patient | `language: null` or `language: ""`, `priority_bucket: 1` |
| FreePBX Queues | `scheduling_en`, `scheduling_es` available |

**Expected**: Default to `scheduling_en` (English) queue on transfer.
