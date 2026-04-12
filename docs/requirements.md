# AI Outbound Call Orchestrator - Requirements Document

## Overview

An AI-powered system that automatically places outbound scheduling calls to patients, prioritizing based on call history and queue status, while ensuring inbound call capacity is never compromised.

---

## Core Business Rules

### 1. Queue Protection (Never Steal Inbound Capacity)

- Outbound calls may only be placed when scheduling queues have sufficient capacity
- If queue monitoring fails, outbound calling must be disabled (fail-closed)
- Only one outbound call may be active at any time globally

### 2. Business Hours Enforcement

- Outbound calls only during configured business hours
- Administrators can enable/disable the system, configure hours, and view logs via dashboard
- Holiday calendar support required

---

## Call Prioritization

Candidates are selected in priority order (highest priority first):

| Priority | Description |
|----------|-------------|
| 1 | Patient abandoned queue + never received AI call |
| 2 | Patient abandoned queue + previously received AI call |
| 3 | Patient never received AI call + has called in before |
| 4 | Patient never received AI call + never called in |

Within each priority bucket, order by:
1. Oldest due date first (2 business day SLA)
2. Oldest order creation date
3. Lowest attempt count

### Retry Controls

- Maximum total attempts per patient (configurable, e.g., 3)
- Minimum hours between attempts (configurable, e.g., 6-8 hours)
- Respect do-not-call windows

---

## Queue Monitoring Requirements

The system must monitor all scheduling queues and track:

- Calls waiting per queue
- Longest wait time
- Available agents (logged in, not paused, not on a call)

### Outbound Gating Conditions

All conditions must be true before placing an outbound call:

1. At least one agent available
2. Calls waiting below threshold (configurable, default: 0-1)
3. Oldest wait time below threshold (configurable, default: 20-45 seconds)
4. Conditions stable for multiple polling cycles (hysteresis)

---

## Call Outcomes

Every call must result in one of these outcomes:

### Outcome 1: No Answer / Voicemail
- Leave voicemail message (no PHI)
- Send SMS with callback information (no PHI)

### Outcome 2: Answered and Transferred
- AI confirms patient readiness to schedule
- Transfer to appropriate language-specific scheduling queue
- Only transfer if queue conditions still favorable

### Outcome 3: Answered but Not Available Now
- AI offers assistance with other questions
- Invite patient to reply with preferred callback time
- Send SMS with callback info and main number

### Outcome 4: Wrong Number
- AI apologizes and ends call quickly
- Email notification to scheduling team with patient/order details

### Outcome 5: Invalid/Disconnected Number
- Detected via carrier failure codes
- Email notification to scheduling team

---

## Language-Based Routing

- Patient language preference from patient records determines transfer destination
- Each language maps to a specific scheduling queue
- Unknown/null language defaults to English queue

---

## AI Agent Capabilities

### Allowed Topics
- Business hours and locations
- What to bring to appointments
- How to upload ID/documents
- How to reschedule
- Portal access instructions
- What happens next

### Prohibited Topics
- Medical discussions
- Diagnosis information
- Exam results
- Any clinical content

### Escalation Behavior
- If question is out of scope and transfer is safe: offer to connect to scheduling
- If transfer not safe: provide number via SMS and promise follow-up

---

## Transfer Safety

Before transferring a patient to a live agent:

1. Re-verify queue conditions are still favorable
2. Confirm at least one agent is available
3. Confirm correct language queue exists

If transfer is not safe:
- Do not transfer
- Inform patient scheduling team is busy
- Offer callback window
- Send SMS with information

---

## Notifications

### Email Notifications (to scheduling@precisemri.com)

**Wrong Number:**
- Subject: "Scheduling Call Issue - Wrong Number (Patient ID: {ID})"
- Include: Patient ID, Order ID, Phone, Timestamp, Call ID

**Disconnected/Invalid:**
- Subject: "Scheduling Call Issue - Invalid/Disconnected Number (Patient ID: {ID})"
- Include: Patient ID, Order ID, Phone, Timestamp, Call ID, Error/Status

### SMS Notifications
- Must not contain PHI
- Include callback number
- Sent for voicemail and "not available now" outcomes

---

## Data Requirements

### Per-Patient Tracking
- Order and patient identifiers
- Phone number
- Language preference
- Call history (has called in, has abandoned, has received AI call)
- Attempt count and timing
- Last outcome
- Due date for SLA tracking

### Call Logging
- Unique call identifier
- Timestamps
- Priority bucket used
- Queue snapshot at dial time
- Outcome
- Transfer attempt status
- Voicemail/SMS sent status
- Error codes if applicable

---

## Dashboard Requirements

### Features
- View all AI agent types
- Select specific agent to view logs and settings
- Enable/disable outbound calling
- Configure business hours rules
- View complete call log history
- Real-time queue status visibility

---

## Configurable Parameters

| Parameter | Description | Example Default |
|-----------|-------------|-----------------|
| Calls waiting threshold | Max calls in queue to allow outbound | 0-1 |
| Oldest wait threshold | Max wait time to allow outbound | 20-45 seconds |
| Stability polls required | Consecutive good polls before outbound | 3 |
| Max attempts per patient | Total call attempts allowed | 3 |
| Min hours between attempts | Cooldown between retries | 6-8 hours |
| Polling interval | Queue check frequency | 10 seconds |
