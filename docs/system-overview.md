# AI Outbound Voice System - Plain Language Overview

## The Big Picture

This is an **AI phone system** for a medical imaging company (Precise Imaging) that automatically calls patients to help them schedule their MRI appointments. Think of it as a helpful robot that makes outbound calls so human schedulers don't have to.

---

## The Core Problem It Solves

Patients need to schedule MRI appointments, but:
- Sometimes they call in and hang up (abandon the queue) before talking to anyone
- Sometimes they never call at all
- Human schedulers are busy handling inbound calls

**Solution**: Have an AI automatically call these patients when the scheduling team isn't busy.

---

## The #1 Rule: Never Steal Inbound Capacity

The most important rule is: **never let the AI call interfere with real patients calling in**.

Before the AI makes any call, it must check:
1. Are there agents available to take calls?
2. Is the queue empty (or nearly empty)?
3. Has the queue been calm for a while (not just a momentary lull)?

If any of these fail, don't call. If the monitoring system breaks, don't call (fail safe).

---

## Who Gets Called First (Priority System)

Not all patients are equal. The system prioritizes who to call:

| Priority | Who |
|----------|-----|
| **Highest** | Patient who hung up waiting + never got an AI call before |
| **High** | Patient who hung up waiting + already got an AI call |
| **Medium** | Patient who has called before + never got an AI call |
| **Lowest** | Patient who never called in + never got an AI call |

Within each group, sort by: oldest due date, then oldest order, then fewest call attempts.

---

## What Happens During a Call

### When the AI calls a patient:

1. **Greets them** by first name, says it's calling from Precise Imaging
2. **Asks if now is a good time** to help schedule their MRI
3. Based on response:
   - **"Yes, I can talk now"** - Transfer to a human scheduler
   - **"Not a good time"** - Offer to call back later, send a text with the number
   - **No answer** - Leave a voicemail (no personal health info), send a text
   - **"Wrong number"** - Apologize, hang up, email the scheduling team
   - **Disconnected number** - Log it, email the scheduling team

### What the AI can answer:
- Business hours and locations
- What to bring to appointments
- How to upload documents
- General scheduling questions

### What the AI cannot discuss:
- Medical advice
- Test results
- Diagnoses
- Anything clinical

---

## The Transfer Safety Check

Before transferring a patient to a human:
1. Re-check that the queue is still calm
2. Confirm an agent is available
3. Route to the right language queue (English, Spanish, etc.)

If conditions changed, don't transfer. Apologize and offer to have someone call them back.

---

## External Systems Involved

| System | What It Does |
|--------|--------------|
| **FreePBX/Asterisk** | The phone system - monitors queue status, where transfers go |
| **Twilio** | Cloud service that actually places/receives calls and sends texts |
| **OpenAI Realtime API** | The AI brain that talks to patients |
| **Patient Database** | Where patient info and phone numbers come from |
| **Radflow** | Where call logs get recorded |
| **Email** | Sends alerts to scheduling team for wrong/bad numbers |

---

## Business Rules

- Only call during business hours
- Respect holidays
- Maximum 3 attempts per patient
- Wait at least 6-8 hours between attempts
- Only one AI call can be active at a time globally
- Log everything

---

## The Dashboard

Admins can:
- See real-time queue status
- See which patients are in the call queue
- Watch live transcripts of calls
- View call history
- Enable/disable the system
- Configure business hours

---

## Summary

An AI automatically calls patients who need to schedule MRIs, but only when the human scheduling team isn't busy, and either transfers them to a human or handles simple questions itself.
