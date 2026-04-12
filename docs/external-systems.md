# External Systems Integration Guide

## Overview

The AI Outbound Call Orchestrator integrates with multiple external systems to monitor queues, place calls, conduct AI conversations, and send notifications. This document describes each system, its role, and the integration requirements.

---

## 1. FreePBX / Asterisk

### What It Is
FreePBX is an open-source web GUI for managing Asterisk, a PBX (Private Branch Exchange) system. Asterisk handles all inbound and outbound phone calls, call routing, queues, and agent management.

### Role in This System

**Queue Monitoring:**
- Provides real-time visibility into scheduling queue status
- Reports how many calls are waiting, how long they've been waiting, and which agents are available
- Enables the "never steal inbound capacity" rule by exposing queue pressure data

**Call Transfer Destination:**
- When the AI successfully engages a patient ready to schedule, the call is transferred into a FreePBX queue
- Different queues exist for different languages (English, Spanish, etc.)
- Human scheduling agents pick up transferred calls from these queues

**Historical Data Source:**
- Queue logs and CDR (Call Detail Records) can indicate if a patient has called in before or abandoned a queue
- This data feeds into the priority bucket assignment

### Integration Method
- **Asterisk Manager Interface (AMI)**: TCP-based protocol for real-time queue status polling
- Polling frequency: Every 10 seconds
- Connection: Internal network only

### Key Data Points
| Metric | Description |
|--------|-------------|
| `calls_waiting` | Number of callers in queue |
| `oldest_wait_seconds` | How long the longest-waiting caller has been holding |
| `agents_available` | Agents logged in, not paused, not on a call |
| `agents_logged_in` | Total agents in the queue |

### Failure Behavior
If AMI connection fails, the system must disable outbound calling (fail-closed).

---

## 2. Twilio

### What It Is
Twilio is a cloud communications platform providing APIs for voice calls, SMS, and other communication channels.

### Role in This System

**Outbound Call Initiation:**
- Places outbound calls to patients on behalf of the AI agent
- Manages the call lifecycle (ringing, answered, no-answer, busy, failed)

**Call Status Webhooks:**
- Notifies our system of call state changes via HTTP webhooks
- Reports carrier-level errors (disconnected numbers, invalid numbers)

**Voicemail Detection:**
- Detects when a call is answered by voicemail/answering machine
- Allows the system to leave a pre-recorded message

**SMS Delivery:**
- Sends text messages to patients (callback info, appointment reminders)
- Used after voicemail, "can't talk now" scenarios, and other outcomes

**Call Transfer:**
- Executes the transfer to FreePBX when the AI determines patient is ready
- Uses SIP/PSTN bridging to connect the patient to the appropriate queue

### Integration Method
- **Twilio REST API**: For initiating calls and sending SMS
- **Twilio Webhooks**: For receiving call status updates
- **Twilio Media Streams**: For real-time audio streaming to/from AI

### Key APIs
| API | Purpose |
|-----|---------|
| `Calls.create()` | Initiate outbound call |
| `Messages.create()` | Send SMS |
| `<Dial>` TwiML | Transfer call to another number/SIP |
| Status Callback | Receive call state changes |
| Media Streams | Bi-directional audio for AI |

### Configuration Required
- Account SID and Auth Token
- Phone number(s) for caller ID
- Webhook endpoint URLs
- SIP trunk or DID for FreePBX transfers

---

## 3. OpenAI Realtime API

### What It Is
OpenAI's Realtime API enables low-latency, multi-modal conversations with AI. It supports real-time audio input/output for voice-based interactions.

### Role in This System

**Voice Conversation:**
- Conducts the actual phone conversation with the patient
- Listens to patient speech, understands intent, and responds naturally

**Intent Detection:**
- Determines what the patient wants (schedule now, call back later, wrong number)
- Identifies when patient asks questions the AI can answer vs. needs escalation

**Conversation Flow Management:**
- Follows scripted flows while adapting to patient responses
- Knows when to offer transfer, when to end call, when to send SMS

**Knowledge-Based Responses:**
- Answers operational questions (hours, locations, what to bring)
- Refuses to discuss medical topics appropriately

### Integration Method
- **WebSocket Connection**: Real-time bi-directional audio streaming
- **Audio Format**: PCM audio at 24kHz or 16kHz
- Connects via Twilio Media Streams or direct audio bridge

### Conversation Capabilities
| Capability | Description |
|------------|-------------|
| Speech-to-text | Understands patient speech |
| Natural language understanding | Interprets intent |
| Text-to-speech | Generates natural voice responses |
| Context management | Maintains conversation state |
| Function calling | Triggers actions (transfer, end call, send SMS) |

### Configuration Required
- API key
- System prompt / conversation instructions
- Knowledge base content
- Function definitions for actions

---

## 4. Email Service (SMTP / Email API)

### What It Is
An email delivery service for sending notifications to internal teams.

### Role in This System

**Wrong Number Notifications:**
- Alerts scheduling team when a patient reports wrong number
- Includes patient ID, order ID, phone number, and call details

**Disconnected Number Notifications:**
- Alerts scheduling team when a call fails due to invalid/disconnected number
- Includes carrier error codes for diagnosis

### Integration Method
- SMTP relay, or
- Email API (SendGrid, AWS SES, etc.)

### Recipient
- `scheduling@precisemri.com`

### Configuration Required
- SMTP host/port/credentials, or
- API key for email service
- From address
- Email templates

---

## 5. Patient Data System (PatientModule)

### What It Is
The existing internal system that stores patient demographic and contact information.

### Role in This System

**Patient Information:**
- Provides phone number to call
- Provides patient ID for tracking and notifications

**Language Preference:**
- Stores patient's preferred language
- Determines which FreePBX queue to transfer to

**Order Information:**
- Order ID for tracking
- Order creation date for SLA calculation (2 business day due date)

### Integration Method
- Database query (SQL)
- Internal API call
- Shared database access

### Key Data Points
| Field | Purpose |
|-------|---------|
| `PatientId` | Unique patient identifier |
| `Phone` | Phone number to call |
| `Language` / `LanguageCode` | Preferred language for queue routing |
| `OrderId` | Associated order |
| `OrderCreatedDate` | For SLA calculation |

---

## 6. Radflow Call Log

### What It Is
The existing system for logging and viewing all calls (inbound and outbound) across the organization.

### Role in This System

**Call Logging:**
- All outbound AI calls and their outcomes are logged here
- Provides unified view of call activity for scheduling team

**Tracking & Reporting:**
- Historical record of all AI call attempts
- Enables reporting on AI calling effectiveness

### Integration Method
- Database insert
- API call
- Shared logging infrastructure

### Data to Log
| Field | Description |
|-------|-------------|
| Call SID | Twilio's unique call identifier |
| Patient ID | Who was called |
| Order ID | Associated order |
| Timestamp | When call occurred |
| Outcome | Which of the 5 outcomes |
| Duration | Call length |
| Transfer status | If transfer was attempted/successful |
| Notes | Additional context |

---

## 7. Temporal

### What It Is
Temporal is a workflow orchestration platform that manages long-running, stateful workflows with built-in reliability, retries, and observability.

### Role in This System

**Queue Polling Workflow:**
- Runs continuously, polling queue status every 10 seconds
- Persists state across restarts
- Handles failures gracefully

**Outbound Dispatcher Workflow:**
- Manages the decision loop for when to place outbound calls
- Ensures only one call at a time (distributed mutex)
- Selects next candidate based on priority

**Outbound Call Workflow:**
- Manages individual call lifecycle from dial to outcome
- Coordinates with Twilio webhooks and AI events
- Handles timeouts and retries
- Guarantees exactly-once execution

### Integration Method
- Temporal SDK (Go, TypeScript, Python, etc.)
- Temporal Server (self-hosted or cloud)

### Key Benefits
| Feature | Benefit |
|---------|---------|
| Durable execution | Survives crashes, restarts |
| Automatic retries | Handles transient failures |
| Workflow visibility | Debug and monitor running workflows |
| Distributed locks | Ensures single outbound call |
| Timeouts | Prevents hung calls |

### Configuration Required
- Temporal server address
- Namespace
- Task queue names
- Worker configuration

---

## 8. Knowledge Base System

### What It Is
An existing system that stores scripts, FAQs, and versioned content for AI training.

### Role in This System

**AI Training Content:**
- Provides answers to common scheduling questions
- Scripts for voicemail messages
- Guidelines for conversation handling

**Version Control:**
- Tracks changes to AI knowledge over time
- Enables rollback if needed

### Content Includes
- Business hours and locations
- What to bring to appointments
- How to upload documents
- Portal access instructions
- Rescheduling procedures
- Standard greetings and closings

### Integration Method
- Content is loaded into OpenAI system prompt
- May be fetched at startup or periodically refreshed
- API or file-based access

---

## System Integration Diagram

```
                                    ┌─────────────────┐
                                    │   Dashboard     │
                                    │   (Admin UI)    │
                                    └────────┬────────┘
                                             │
                                             ▼
┌─────────────────┐              ┌─────────────────────┐              ┌─────────────────┐
│   FreePBX /     │◄────AMI─────►│                     │◄────SQL─────►│  Patient Data   │
│   Asterisk      │              │                     │              │  (PatientModule)│
│                 │◄───Transfer──│   AI Outbound       │              └─────────────────┘
│  - Queues       │              │   Call              │
│  - Agents       │              │   Orchestrator      │              ┌─────────────────┐
│  - CDR/Logs     │              │                     │◄────SQL─────►│  Radflow        │
└─────────────────┘              │                     │              │  Call Log       │
                                 │                     │              └─────────────────┘
┌─────────────────┐              │                     │
│   Twilio        │◄───REST/WS──►│                     │              ┌─────────────────┐
│                 │              │                     │◄────SDK─────►│  Temporal       │
│  - Voice API    │              │                     │              │  (Workflows)    │
│  - SMS API      │              └──────────┬──────────┘              └─────────────────┘
│  - Webhooks     │                         │
└─────────────────┘                         │
                                            ▼
┌─────────────────┐              ┌─────────────────────┐              ┌─────────────────┐
│   OpenAI        │◄───WebSocket─│   Voice AI          │              │  Email Service  │
│   Realtime API  │              │   Session           │              │  (SMTP/API)     │
│                 │              └─────────────────────┘              └─────────────────┘
│  - Audio I/O    │                                                            ▲
│  - Conversation │                                                            │
└─────────────────┘                                                   ─────────┘

                                 ┌─────────────────────┐
                                 │   Knowledge Base    │
                                 │   (Scripts/FAQs)    │
                                 └─────────────────────┘
```

---

## Summary Table

| System | Type | Protocol | Direction | Critical Path |
|--------|------|----------|-----------|---------------|
| FreePBX/Asterisk | PBX | AMI (TCP) | Bidirectional | Yes - queue monitoring |
| Twilio | Cloud Telephony | REST/WebSocket | Bidirectional | Yes - call execution |
| OpenAI Realtime | AI Service | WebSocket | Bidirectional | Yes - conversation |
| Email Service | Notification | SMTP/API | Outbound | No - notification only |
| PatientModule | Database | SQL | Read | Yes - candidate data |
| Radflow Call Log | Database | SQL | Write | No - logging only |
| Temporal | Orchestration | gRPC | Bidirectional | Yes - workflow engine |
| Knowledge Base | Content | API/File | Read | No - configuration |

---

## Availability Requirements

| System | If Unavailable |
|--------|----------------|
| FreePBX/Asterisk | Disable outbound calling (fail-closed) |
| Twilio | Cannot place or manage calls |
| OpenAI Realtime | Cannot conduct AI conversations |
| Email Service | Queue notifications for retry |
| PatientModule | Cannot select candidates |
| Radflow Call Log | Queue logs for retry (non-blocking) |
| Temporal | Workflows pause until recovered |
| Knowledge Base | Use cached content |
