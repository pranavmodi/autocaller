# Business Hours / System Control Scenarios

These scenarios test business hours enforcement and system enable/disable functionality.

---

## Scenario 13: Within business hours, system enabled

**Description**: Normal operating conditions during work hours.

| Component | State |
|-----------|-------|
| System Settings | `system_enabled: true`, `business_hours.enabled: true`, `business_hours.start_time: "08:00"`, `business_hours.end_time: "17:00"`, `business_hours.timezone: "America/New_York"` |
| Current Time | 10:30 AM Eastern |
| Queue State | All conditions met |

**Expected**: Outbound calls allowed.

---

## Scenario 14: Outside business hours, system enabled

**Description**: System is on but it's after hours.

| Component | State |
|-----------|-------|
| System Settings | `system_enabled: true`, `business_hours.enabled: true`, `business_hours.start_time: "08:00"`, `business_hours.end_time: "17:00"` |
| Current Time | 7:00 PM Eastern |
| Queue State | All conditions met |

**Expected**: Outbound blocked. `is_within_business_hours: false`, `can_make_calls: false`.

---

## Scenario 15: Within business hours, system disabled

**Description**: Admin has turned off the outbound system.

| Component | State |
|-----------|-------|
| System Settings | `system_enabled: false`, `business_hours.enabled: true` |
| Current Time | 10:30 AM Eastern (within hours) |
| Queue State | All conditions met |

**Expected**: Outbound blocked. `can_make_calls: false`.

---

## Scenario 16: Outside business hours, system disabled

**Description**: System off and after hours.

| Component | State |
|-----------|-------|
| System Settings | `system_enabled: false`, `business_hours.enabled: true` |
| Current Time | 7:00 PM Eastern |
| Queue State | All conditions met |

**Expected**: Outbound blocked. `can_make_calls: false`.

---

## Scenario 17: Business hours disabled (24/7 mode)

**Description**: Business hours restriction turned off for 24/7 operation.

| Component | State |
|-----------|-------|
| System Settings | `system_enabled: true`, `business_hours.enabled: false` |
| Current Time | 2:00 AM Eastern |
| Queue State | All conditions met |

**Expected**: Outbound allowed (business hours not enforced). `is_within_business_hours: true`.

---

## Scenario 18: Timezone edge case

**Description**: Call starts at 4:59 PM, business hours end at 5:00 PM.

| Component | State (Call Start) |
|-----------|-------|
| System Settings | `business_hours.end_time: "17:00"` |
| Current Time | 4:59 PM Eastern |
| Active Call | `call_active: false` |

| Component | State (During Call) |
|-----------|-------|
| Current Time | 5:01 PM Eastern |
| Active Call | `call_active: true` |

**Expected**: Call is allowed to start. Active call completes normally even after business hours end. No new calls after 5:00 PM.
