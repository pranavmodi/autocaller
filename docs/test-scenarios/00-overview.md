# Test Scenarios Overview

This directory contains test scenarios for validating the AI Outbound Voice System behavior.

## Component State Reference

| Component | Key States |
|-----------|------------|
| **System Settings** | `system_enabled`, `business_hours.enabled`, `business_hours.start_time`, `business_hours.end_time` |
| **Queue Thresholds** | `calls_waiting_threshold`, `oldest_wait_threshold_seconds`, `stable_polls_required` |
| **Queue State** | `agents_available`, `agents_logged_in`, `calls_waiting`, `oldest_wait_seconds`, `stable_polls_count`, `ami_connected` |
| **Patient** | `priority_bucket`, `attempt_count`, `last_attempt_at`, `language`, `ai_called_before`, `has_called_in_before`, `has_abandoned_before` |
| **Active Call** | `call_active`, `call_outcome`, `transfer_requested` |

## Scenario Files

| File | Category | Scenarios | Count |
|------|----------|-----------|-------|
| [01-queue-gating.md](./01-queue-gating.md) | Queue Gating | 1-12 | 12 |
| [02-business-hours.md](./02-business-hours.md) | Business Hours / System Control | 13-18 | 6 |
| [03-patient-prioritization.md](./03-patient-prioritization.md) | Patient Prioritization | 19-28 | 10 |
| [04-retry-controls.md](./04-retry-controls.md) | Retry Controls | 29-33 | 5 |
| [05-call-outcomes.md](./05-call-outcomes.md) | Call Outcomes | 34-41 | 8 |
| [06-transfer-safety.md](./06-transfer-safety.md) | Transfer Safety | 42-47 | 6 |
| [07-ai-conversation-boundaries.md](./07-ai-conversation-boundaries.md) | AI Conversation Boundaries | 48-58 | 11 |
| [08-edge-cases.md](./08-edge-cases.md) | Edge Cases / Failures | 59-65 | 7 |
| [09-combined-scenarios.md](./09-combined-scenarios.md) | Combined/Complex | 66-70 | 5 |
| | **Total** | | **70** |

## Default Test Values

Unless otherwise specified, scenarios assume these defaults:

```
System Settings:
  system_enabled: true
  business_hours.enabled: false (24/7 mode)

Queue Thresholds:
  calls_waiting_threshold: 1
  oldest_wait_threshold_seconds: 30
  stable_polls_required: 3

Queue State:
  ami_connected: true
  agents_logged_in: 3
  agents_available: 2
  calls_waiting: 0
  oldest_wait_seconds: 0
  stable_polls_count: 3
  outbound_allowed: true

Active Call:
  call_active: false
```

## Priority Bucket Reference

| Priority | Description | Criteria |
|----------|-------------|----------|
| P1 | Highest | `has_abandoned_before: true` AND `ai_called_before: false` |
| P2 | High | `has_abandoned_before: true` AND `ai_called_before: true` |
| P3 | Medium | `has_called_in_before: true` AND `ai_called_before: false` |
| P4 | Lowest | `has_called_in_before: false` AND `ai_called_before: false` |

## Sorting Within Priority

1. Oldest `due_by` date first
2. Oldest `order_created` date first
3. Lowest `attempt_count` first
