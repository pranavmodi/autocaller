# AI Outbound Call Orchestrator - Implementation Plan

## Overview

This plan outlines the implementation approach with a focus on developing against mocked external systems (FreePBX/Asterisk, Twilio) to enable parallel development before production infrastructure is available.

---

## Phase 1: Foundation & Abstractions

### 1.1 Define Provider Interfaces

Create abstract interfaces for all external system interactions:

```
providers/
├── queue/
│   ├── interface.ts          # QueueProvider interface
│   ├── mock.ts               # MockQueueProvider
│   └── asterisk-ami.ts       # Real AMI implementation (later)
├── telephony/
│   ├── interface.ts          # TelephonyProvider interface
│   ├── mock.ts               # MockTelephonyProvider
│   └── twilio.ts             # Real Twilio implementation
├── voice-ai/
│   ├── interface.ts          # VoiceAIProvider interface
│   ├── mock.ts               # MockVoiceAIProvider
│   └── openai-realtime.ts    # Real OpenAI Realtime implementation
└── notification/
    ├── interface.ts          # EmailProvider, SMSProvider interfaces
    ├── mock.ts               # Mock implementations
    └── production.ts         # Real email/SMS
```

**Key Interfaces:**

- `QueueProvider`: `getQueueStatus()`, `getGlobalPressure()`
- `TelephonyProvider`: `initiateCall()`, `transferCall()`, `endCall()`, `playMessage()`
- `VoiceAIProvider`: `startSession()`, `handleAudio()`, `getTranscript()`
- `NotificationProvider`: `sendEmail()`, `sendSMS()`

### 1.2 Configuration System

Environment-based provider selection:

```
PROVIDER_MODE=mock|production

# Mock settings
MOCK_QUEUE_AGENTS_AVAILABLE=3
MOCK_QUEUE_CALLS_WAITING=0
MOCK_CALL_ANSWER_RATE=0.7
MOCK_CALL_OUTCOMES=random|sequential|specific

# Production settings (for later)
AMI_HOST=...
TWILIO_ACCOUNT_SID=...
```

---

## Phase 2: Mock Implementations

### 2.1 Mock Queue Provider

Simulates FreePBX/Asterisk queue state:

**Capabilities:**
- Configurable number of queues
- Adjustable agent availability
- Simulated call arrivals and departures
- Controllable failure scenarios for testing fail-closed behavior
- Time-based patterns (busy periods, quiet periods)

**Test Scenarios:**
- All agents busy
- Queue pressure high
- AMI connection failure
- Fluctuating conditions (hysteresis testing)

### 2.2 Mock Telephony Provider

Simulates Twilio call flow:

**Capabilities:**
- Simulated call states (ringing, answered, no-answer, busy, failed)
- Configurable answer rates and outcomes
- Voicemail detection simulation
- Transfer success/failure simulation
- Webhook event generation
- Carrier error code simulation

**Test Scenarios:**
- Successful call → transfer
- No answer → voicemail
- Wrong number detection
- Disconnected number
- Transfer failure mid-call

### 2.3 Mock Voice AI Provider

Simulates OpenAI Realtime conversations:

**Capabilities:**
- Pre-scripted conversation flows
- Configurable patient responses
- Intent detection simulation
- Transcript generation

**Conversation Scenarios:**
- Patient ready to schedule → transfer
- Patient busy, wants callback
- Patient says wrong number
- Patient asks scheduling questions
- Patient asks out-of-scope questions

### 2.4 Local Call Simulator (Interactive Testing)

Console-based or web-based interface for manual testing:

- Developer can "answer" calls as the patient
- Type responses or select from common replies
- See AI responses in real-time
- Trigger various outcomes manually

---

## Phase 3: Core Business Logic

### 3.1 Candidate Selection Service

Implements the 4-bucket priority system:

- Query candidates from database
- Apply priority ordering
- Check retry eligibility (max attempts, cooldown)
- Respect do-not-call windows and business hours
- Lock candidate during call

### 3.2 Queue Pressure Calculator

Aggregates queue data into gating decisions:

- Compute global metrics from per-queue data
- Apply thresholds
- Track stability for hysteresis
- Emit outbound-allowed flag

### 3.3 Outbound Gating Service

Central decision point for outbound eligibility:

- Check business hours
- Check queue pressure
- Check for active outbound call
- Verify stability requirement met

### 3.4 Call Orchestration Service

Manages the call lifecycle:

- Initiate call via provider
- Handle state transitions
- Coordinate with Voice AI
- Execute outcome handlers
- Log results

### 3.5 Outcome Handlers

One handler per outcome type:

- `NoAnswerHandler`: Voicemail + SMS
- `TransferHandler`: Queue verification + transfer
- `CantNowHandler`: SMS with callback info
- `WrongNumberHandler`: Email notification
- `DisconnectedHandler`: Email notification

---

## Phase 4: Data Layer

### 4.1 Database Schema

Tables:
- `outbound_call_state`: Per-patient/order call tracking
- `outbound_call_log`: Append-only call history
- `queue_snapshots`: Historical queue state (optional, for analytics)
- `configuration`: Runtime settings

### 4.2 Repositories

- `CandidateRepository`: CRUD for call candidates
- `CallLogRepository`: Append call records
- `ConfigRepository`: Read/write settings

---

## Phase 5: Workflow Orchestration

### 5.1 Queue Polling Workflow

Runs continuously:
- Poll every 10 seconds
- Update pressure metrics
- Publish to event bus or state store

### 5.2 Outbound Dispatcher Workflow

Runs continuously:
- Check outbound eligibility
- Select next candidate
- Spawn call workflow
- Ensure single-call concurrency

### 5.3 Outbound Call Workflow

Per-call workflow:
- Lock candidate
- Initiate call
- Handle conversation events
- Execute outcome
- Unlock and log

---

## Phase 6: API & Webhooks

### 6.1 Internal APIs

- `GET /health`: System health
- `GET /metrics`: Prometheus metrics
- `GET /status`: Current queue state and outbound eligibility
- `POST /admin/config`: Update runtime settings

### 6.2 Webhook Handlers

- `POST /webhooks/call-status`: Call state changes
- `POST /webhooks/voice-events`: Voice AI events

---

## Phase 7: Dashboard

### 7.1 Agent Dashboard

- List all AI agents
- Select agent to view details

### 7.2 Outbound Agent Views

- Enable/disable toggle
- Business hours configuration
- Call log with filtering
- Real-time queue status
- Configuration editor

---

## Phase 8: Integration Testing with Mocks

### 8.1 Scenario Tests

Automated tests using mock providers:

- Full call flow: dial → answer → transfer
- Full call flow: dial → voicemail → SMS
- Queue pressure prevents outbound
- Business hours enforcement
- Retry logic and cooldowns
- Priority bucket ordering
- Concurrency (only one call at a time)

### 8.2 Chaos Testing

- Random provider failures
- Delayed responses
- Inconsistent queue states

---

## Phase 9: Production Provider Implementation

### 9.1 Asterisk AMI Provider

When FreePBX/Asterisk is available:
- Implement `QueueProvider` with real AMI
- Test against staging PBX
- Validate queue name mappings
- Verify agent state detection

### 9.2 Twilio Provider

- Implement `TelephonyProvider` with Twilio SDK
- Configure webhooks
- Test with real phone numbers
- Verify transfer mechanics

### 9.3 OpenAI Realtime Provider

- Implement `VoiceAIProvider` with OpenAI API
- Integrate conversation scripts
- Test voice quality and latency

---

## Phase 10: Deployment & Cutover

### 10.1 Staged Rollout

1. Deploy with mock providers (validation)
2. Enable real queue monitoring only (read-only)
3. Enable with limited candidate pool
4. Full production

### 10.2 Monitoring

- Queue polling success rate
- Call success/failure rates
- Outcome distribution
- Transfer success rate
- Average call duration

---

## Development Order Summary

| Step | Component | Dependencies | Mock Available |
|------|-----------|--------------|----------------|
| 1 | Provider interfaces | None | N/A |
| 2 | Mock providers | Interfaces | Yes |
| 3 | Configuration system | None | N/A |
| 4 | Database schema | None | N/A |
| 5 | Candidate selection | Database | Yes |
| 6 | Queue pressure calculator | Queue provider | Yes |
| 7 | Gating service | Pressure calculator | Yes |
| 8 | Outcome handlers | Notification providers | Yes |
| 9 | Call orchestration | All providers | Yes |
| 10 | Workflows | Orchestration | Yes |
| 11 | APIs & webhooks | Workflows | Yes |
| 12 | Dashboard | APIs | Yes |
| 13 | Integration tests | All mocks | Yes |
| 14 | Real Asterisk AMI | FreePBX available | No |
| 15 | Real Twilio | Account configured | No |
| 16 | Real OpenAI | API access | No |

---

## Mock Provider Configuration Examples

### Simulate Busy Queue Period
```
MOCK_QUEUE_CALLS_WAITING=5
MOCK_QUEUE_OLDEST_WAIT=60
MOCK_QUEUE_AGENTS_AVAILABLE=0
```

### Simulate Quiet Period (Outbound Allowed)
```
MOCK_QUEUE_CALLS_WAITING=0
MOCK_QUEUE_OLDEST_WAIT=0
MOCK_QUEUE_AGENTS_AVAILABLE=3
```

### Simulate Flaky AMI Connection
```
MOCK_QUEUE_FAILURE_RATE=0.2
MOCK_QUEUE_FAILURE_DURATION=30
```

### Simulate Various Call Outcomes
```
MOCK_CALL_OUTCOME_DISTRIBUTION=answered:0.6,no_answer:0.2,voicemail:0.1,failed:0.1
MOCK_TRANSFER_SUCCESS_RATE=0.9
MOCK_WRONG_NUMBER_RATE=0.05
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Mock behavior differs from production | Document assumptions, validate early with real systems |
| Queue state interpretation errors | Build comprehensive logging, compare mock vs real |
| Transfer mechanics complex | Test transfer flow in isolation before integration |
| Voice AI latency issues | Build timeout handling, test with simulated delays |
| Concurrent call prevention gaps | Use distributed locks, test race conditions |
