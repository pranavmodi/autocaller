# Production Readiness — Switchover Checklist

Issues and fixes required before switching from simulation/mock mode to live production systems.

Last updated: 2026-03-23

---

## Critical Issues (will break things if not fixed)

### 1. Twilio webhook URLs may point to wrong host

**File:** `app/services/call_orchestrator.py:262-264`

**Issue:** When placing a Twilio call, the system builds webhook URLs (TwiML, status callbacks, media stream WebSocket) using `PUBLIC_BASE_URL`. If not set, it falls back to `NEXT_PUBLIC_API_URL`, then `http://localhost:8000`.

**Current .env state:** `PUBLIC_BASE_URL` is not set, but `NEXT_PUBLIC_API_URL=https://outbound.mediflow360.com` is set, so Twilio will use `https://outbound.mediflow360.com/api/twilio/twiml/...`. This works **only if that domain routes to the backend API**, not just the frontend. If the frontend and backend are served from different hosts, Twilio webhooks will hit the frontend and fail.

**What happens if not fixed:** Twilio places the call and the patient's phone rings, but when they answer there is no audio — the TwiML webhook fails, the media stream WebSocket never connects (30-second timeout), and the call is marked FAILED. AMD voicemail detection and carrier failure callbacks also silently stop working.

**Fix:** Set `PUBLIC_BASE_URL` explicitly to the backend's externally reachable URL. Verify that this URL can serve both HTTPS (for TwiML/status webhooks) and WSS (for media stream WebSocket at `/ws/twilio-media/`).

---

### 2. Live patient provider ignores retry controls

**File:** `app/providers/patient_provider.py:394-401`

**Issue:** `LivePatientProvider.get_outbound_queue()` accepts `max_attempts` and `min_hours_between` parameters but does not use them. It fetches the full patient list from RadFlow and only sorts by priority — no filtering.

**What happens if not fixed:** The system may call the same patient multiple times in rapid succession with no cooldown, and continue calling patients who have already reached the max attempt limit. This violates the retry controls in the requirements (max 3 attempts, 6-8 hours between).

**Fix:** After fetching from RadFlow, apply the same filters the simulation provider uses: skip patients where `attempt_count >= max_attempts`, and skip patients where `last_attempt_at` is within the cooldown window. This requires local state tracking (see issue #3).

---

### 3. Live patient provider is read-only — no state tracking

**File:** `app/providers/patient_provider.py:403-418`

**Issue:** `LivePatientProvider.update_patient_after_call()` and `mark_patient_invalid_number()` are no-ops — they log a message but don't persist anything. There is no local database table and no write-back to RadFlow.

**What happens if not fixed:**
- `ai_called_before` is never set to `True`, so patients never move from high-priority bucket 1 to lower bucket 2. The same patient keeps getting picked first.
- `attempt_count` is never incremented locally, compounding issue #2.
- `mark_patient_invalid_number()` has no effect — disconnected numbers are retried on the next poll.
- No record of what happened on each call outside of the local call log.

**Fix:** Add a local state table (e.g., `patient_call_state`) that tracks `patient_id`, `attempt_count`, `last_attempt_at`, `last_outcome`, `ai_called_before`, and `invalid_number`. The live provider should merge this local state with the RadFlow API data on each fetch, and persist outcomes after each call.

---

### 4. SSL verification disabled on RadFlow patient API

**File:** `app/providers/patient_provider.py:340`

**Issue:** The HTTP client is created with `verify=False`, which disables TLS certificate validation.

**What happens if not fixed:** Patient data (names, phone numbers, order IDs) travels over the network without verifying the server's identity. A man-in-the-middle could intercept or modify patient data.

**Fix:** Change to `verify=True` (the default). If RadFlow uses a self-signed or internal CA certificate, provide the CA bundle path via the `verify` parameter instead of disabling verification entirely.

---

## High Severity (will cause noticeable problems)

### 5. Email SMTP configured with development Gmail account

**File:** `.env`, `app/services/email_notification_service.py`

**Issue:** SMTP is configured using a personal/development Gmail account (`holisticreadsai@gmail.com`) with an app password. Emails to the scheduling team arrive from this unrecognized address.

**What happens if not fixed:**
- Emails from `holisticreadsai@gmail.com` may be caught by spam filters or ignored by staff who don't recognize the sender.
- Gmail has sending limits (500/day regular, 2000/day Workspace) which should be sufficient but aren't guaranteed.
- Using a personal Gmail for production alerts is unprofessional and fragile (account suspension, password rotation).

**Fix:** Use Precise Imaging's own SMTP or a transactional email service (SendGrid, AWS SES, etc.) with a domain-matched sender address (e.g., `outbound@precisemri.com` or `noreply@precisemri.com`). Need SMTP credentials from Danny.

---

### 6. SMS callback number not configured

**File:** `app/services/twilio_sms_service.py:59-77`

**Issue:** SMS messages are built using `PRECISE_CALLBACK_NUMBER` env var. If it's not set, the message falls back to: *"Please call our office using the number previously shared with you."*

**What happens if not fixed:** Patients who receive a voicemail follow-up SMS or a "not available" SMS get a message without a phone number to call back. For patients who have never contacted Precise Imaging before, this is confusing and unhelpful.

**Fix:** Set `PRECISE_CALLBACK_NUMBER` (e.g., `800-558-2223`) and optionally `PRECISE_MAIN_NUMBER` as a secondary number.

---

### 7. Database credentials are weak

**File:** `app/db/base.py`, `.env`

**Issue:** `DATABASE_URL` is set in `.env` and matches the hardcoded default: `postgresql://precise:password@10.254.99.40:5432/outboundvoice`. The password is `password`. The database is on an internal IP, which limits exposure, but the credentials are trivially guessable.

**What happens if not fixed:** Anyone with network access to `10.254.99.40` can connect to the database with `precise/password` and read/modify call logs, patient data, and system settings.

**Fix:** Change the database password to something strong. If this is the intended production database, update both the DB server and the `.env` file. If there's a separate production database, set the correct `DATABASE_URL`.

---

### 8. ~~CORS blocks production frontend~~ — RESOLVED

**File:** `app/main.py:60-68`

**Status:** `CORS_ORIGINS` is set in `.env` to `https://outbound.mediflow360.com,http://localhost:3002,http://127.0.0.1:3002`. Production domain is included. No action needed.

---

## Medium Severity (could cause intermittent issues)

### 9. Single FreePBX poll failure blocks all outbound for 30+ seconds

**File:** `app/providers/queue_provider.py:239-244`

**Issue:** When an HTTP request to FreePBX fails (timeout, network blip, 500 error), the provider immediately sets `ami_connected=False`, `outbound_allowed=False`, and resets the stable polls counter to 0. Recovery requires 3 consecutive successful polls (30 seconds at the default 10-second interval).

**What happens if not fixed:** A brief network hiccup causes outbound calling to pause for at least 30 seconds. If the network is flaky, outbound calling may rarely reach the stability threshold and effectively stay disabled.

**Fix:** Consider tolerating 1-2 consecutive failures before disabling outbound (a "failure hysteresis" to match the existing success hysteresis). Or reduce stable_polls_required for recovery vs. initial startup.

---

### 10. FreePBX polling timeout is tight (5 seconds)

**File:** `app/providers/queue_provider.py:212`

**Issue:** The HTTP client timeout is 5 seconds. Under network load or if FreePBX is slow to respond, polls may time out frequently.

**What happens if not fixed:** Frequent timeouts trigger issue #9, causing outbound calling to be paused repeatedly.

**Fix:** Increase timeout to 10-15 seconds, or use separate connect/read timeouts (e.g., connect=5s, read=15s).

---

### 11. RadFlow API failure serves stale patient data

**File:** `app/providers/patient_provider.py:385`

**Issue:** If the RadFlow API call fails, the provider returns the last cached response (up to 60 seconds old). If the API stays down, the cache eventually goes stale but is still served.

**What happens if not fixed:** During an API outage, the system continues calling patients from an increasingly stale list. New patients won't appear, and patients who should have been removed (e.g., already scheduled) may still be called.

**Fix:** Add a maximum staleness threshold. If the cache is older than a configurable limit (e.g., 5 minutes), stop returning it and treat the patient list as empty (which blocks outbound calling via the "no candidate" path).

---

### 12. Web-mode callbacks persist after switching to Twilio mode

**File:** `app/services/dispatcher.py:281-298`

**Issue:** When the dispatcher starts a call in web mode, it wires up orchestrator callbacks for WebSocket broadcasting to the dashboard. If the call mode is later switched to Twilio, these callbacks remain attached.

**What happens if not fixed:** Dashboard may receive unexpected updates or audio data from Twilio calls that was intended for the browser audio path. Unlikely to crash but may cause confusing UI behavior.

**Fix:** Clear and re-wire orchestrator callbacks when call mode changes, or ensure callbacks are mode-aware.

---

## Low Severity (minor issues)

### 13. FreePBX polled over HTTP, not HTTPS

**File:** `app/providers/queue_provider.py:16`

**Issue:** Queue status is fetched over plain HTTP (`http://10.254.99.40:2001/queuestatus.php`).

**What happens if not fixed:** Queue data (agent counts, call counts) is transmitted unencrypted on the network. Not a patient data risk, but a defense-in-depth concern.

**Fix:** Use HTTPS if FreePBX supports it. If it's strictly internal network with no exposure, this is acceptable.

---

### 14. Two separate gates required for live Twilio calls

**File:** `app/services/twilio_voice_service.py:139`, `app/services/call_orchestrator.py:198`

**Issue:** Two independent guards must both be enabled: the `ALLOW_TWILIO_CALLS=true` env var (checked in `twilio_voice_service.py`) and the `allow_live_calls` database setting (checked in `call_orchestrator.py`). There's also the `allowed_phones` whitelist.

**Current .env state:** `ALLOW_TWILIO_CALLS=true` is set. The `allow_live_calls` DB setting and `allowed_phones` list must still be configured via the Operator Console.

**What happens if not fixed:** Forgetting to enable one of the two gates results in calls failing with no obvious error message to the user. The env var gate produces a RuntimeError, while the settings gate produces a UI error.

**Fix:** Not a bug — this is defense in depth. But document it clearly so operators know both must be enabled. Consider surfacing a dashboard warning when one is enabled but not the other.

---

### 15. Provider sources default to "simulation" on fresh startup

**File:** `app/providers/queue_provider.py:253`, `app/providers/patient_provider.py:427`

**Issue:** Both `queue_source` and `patient_source` default to `"simulation"`. The setting is persisted in the database, so once switched to "live" it stays, but a fresh database will start in simulation mode.

**What happens if not fixed:** After a fresh deployment or database reset, the system uses mock queue data and sample patients instead of real FreePBX and RadFlow data. Calls may go out to test patients or not go out at all.

**Fix:** After deployment, switch both sources to "live" via the Operator Console or API. For fully automated deployments, seed the database with `queue_source="live"` and `patient_source="live"`.

---

## Production Environment Variables

| Variable | Required | .env Status | Action Needed |
|---|---|---|---|
| `PUBLIC_BASE_URL` | Yes | **NOT SET** — falls back to `NEXT_PUBLIC_API_URL` | Set explicitly to backend URL |
| `ALLOW_TWILIO_CALLS` | Yes | `true` | None |
| `TWILIO_ACCOUNT_SID` | Yes | Set (personal account) | Switch to Precise creds for production |
| `TWILIO_AUTH_TOKEN` | Yes | Set (personal account) | Switch to Precise creds for production |
| `TWILIO_FROM_NUMBER` | Yes | `+14437752452` (personal) | Switch to `+18005582223` for production |
| `OPENAI_API_KEY` | Yes | Set | None |
| `DATABASE_URL` | Yes | Set (`10.254.99.34`, password=`password`) | Strengthen password |
| `SMTP_HOST` | Yes | `smtp.gmail.com` (dev) | Replace with production SMTP |
| `SMTP_PORT` | No | `587` | Match production SMTP |
| `SMTP_USERNAME` | Yes | `holisticreadsai@gmail.com` (dev) | Replace with production credentials |
| `SMTP_PASSWORD` | Yes | Set (dev app password) | Replace with production credentials |
| `SMTP_FROM_EMAIL` | Yes | `holisticreadsai@gmail.com` (dev) | `outbound@precisemri.com` or similar |
| `EMAIL_NOTIFICATION_RECIPIENT` | Yes | `scheduling@precisemri.com` | Verify correct |
| `PRECISE_CALLBACK_NUMBER` | Yes | **NOT SET** | Set to `800-558-2223` |
| `PRECISE_MAIN_NUMBER` | No | **NOT SET** | Optional |
| `CORS_ORIGINS` | Yes | Set (includes production domain) | None |
| `FREEPBX_QUEUE_URL` | No | Uses default `10.254.99.40:2001` | Verify correct for production |
| `LANGUAGE_QUEUE_MAP` | Yes | Set: `{"en":"9006","es":"9009","zh":"9012"}` | None (defaults also updated to production IDs) |
| `QUEUE_TRANSFER_TARGETS` | Yes | Set: SIP URIs for 9006/9009/9012/9013 | None |
| `MONITORED_QUEUES` | Recommended | Set: `9006,9009,9012,9013` | None (filters non-scheduling queues from gating) |
| `CALLLIST_API_URL` | No | Set (`app.radflow360.com`) | None |
| `CALLLIST_API_USER` | Yes | Set (`Chatbot`) | None |
| `CALLLIST_API_PASSWORD` | Yes | Set | None |

## Database Settings (via API or Operator Console)

| Setting | Default | Production Value |
|---|---|---|
| `queue_source` | `simulation` | `live` |
| `patient_source` | `simulation` | `live` |
| `call_mode` | `web` | `twilio` |
| `allow_live_calls` | `false` | `true` |
| `allowed_phones` | `[]` | Whitelist of patient phones (or all) |
| `system_enabled` | `true` | `true` |
| `business_hours.enabled` | `false` | `true` |
| `mock_mode` | `false` | `false` |

---

## Questions for Danny

### FreePBX Queues — ANSWERED (2026-03-23)

Full queue mapping from Danny:

| Queue ID | Description |
|---|---|
| 9000 | Records and Images |
| 9001 | Funding Co Billing |
| 9002 | Workers Comp Billing |
| 9003 | Personal Injury Neg |
| 9004 | Personal Injury Billing All Others |
| 9005 | PI Status Updates and Collections |
| **9006** | **Scheduling (English)** |
| **9009** | **Scheduling - Spanish** |
| 9011 | Appointment Status |
| **9012** | **Scheduling - Mandarin (Chinese)** |
| **9013** | **Scheduling - Cantonese (Chinese)** |
| 9014 | Patient Intake (Eng) |
| 9015 | Patient Intake (Spanish) |
| 9016 | Patient Intake (Mandarin) |
| 9017 | Patient Intake (Cantonese) |

**Scheduling queues for language-based transfer:**
- English → 9006
- Spanish → 9009
- Mandarin → 9012
- Cantonese → 9013

**Code impact:** The current `Language` enum only has `en`, `es`, `zh`. The real system distinguishes Mandarin and Cantonese as separate queues. Either:
- Add `zh-cmn` (Mandarin) and `zh-yue` (Cantonese) to the Language enum and update RadFlow mapping, or
- Default `zh` → 9012 (Mandarin) and add Cantonese handling if RadFlow provides that distinction

**Transfer SIP destinations — ANSWERED (2026-03-23, Bill Simon):**

FreePBX has direct SIP access to each queue:
```
sip:9006@pbx.radflow360.com   # Scheduling English
sip:9009@pbx.radflow360.com   # Scheduling Spanish
sip:9012@pbx.radflow360.com   # Scheduling Mandarin
sip:9013@pbx.radflow360.com   # Scheduling Cantonese
```

Production env var:
```
QUEUE_TRANSFER_TARGETS={"9006":"sip:9006@pbx.radflow360.com","9009":"sip:9009@pbx.radflow360.com","9012":"sip:9012@pbx.radflow360.com","9013":"sip:9013@pbx.radflow360.com"}
```

Code already handles SIP URIs with `` — no changes needed (`twilio_voice_service.py:200`).

**Note:** Twilio's IP ranges may need to be whitelisted on the FreePBX firewall. Confirm with Bill whether Twilio can reach `pbx.radflow360.com` on SIP port.

**Still unanswered:**
- Is `http://10.254.99.40:2001/queuestatus.php` the correct production URL for queue monitoring? Does it support HTTPS?

### Twilio

5. **Production Twilio account:** The `.env` has Precise creds commented out (`AC05a8efa2...`, from number `+18005582223`). Should we switch to these for production? Is `+18005582223` the correct outbound caller ID?

6. **PUBLIC_BASE_URL:** Twilio needs to reach our backend for webhooks (TwiML, status callbacks, media streams). What is the externally reachable URL for the backend? Is `https://outbound.mediflow360.com` serving the backend API, or just the frontend?

### Email / Notifications

7. **Production SMTP:** We need production email credentials to replace the development Gmail account. Does Precise have an SMTP relay or email service we should use? What sender address should appear on notifications (e.g., `outbound@precisemri.com`)?

8. **Email recipient:** Notifications currently go to `scheduling@precisemri.com`. Is that the correct recipient for wrong-number and disconnected-number alerts?

### Patient Data

9. **RadFlow write-back:** Currently the system reads patient data from RadFlow but doesn't write call outcomes back. Should it? Is there a RadFlow API endpoint for updating call status (e.g., marking a patient as called, recording the outcome)?

10. **Retry controls:** Does the RadFlow CallListData API filter out patients who have already been called the maximum number of times, or does it return the full list and expect the caller to filter? We need to know if the API handles max_attempts and cooldown, or if we need to track this locally.

### SMS

11. **Callback number:** What phone number should be included in SMS messages sent to patients? Is it `800-558-2223`?

### Database

12. **Database password:** The current password is `password`. Should this be changed for production? Is `10.254.99.34` the correct production database host?

### General

13. **Business hours:** What are the production business hours? Current defaults are Mon-Fri 8AM-5PM Eastern. Are Saturday hours needed? What timezone?

14. **Holidays:** Which holidays should block outbound calling? Is there a standard list, or should we load a specific set?

15. **Phone whitelist:** In production, should the system be allowed to call any patient phone number, or should there be an `allowed_phones` whitelist? During initial rollout, do you want to restrict to a small test group first?
