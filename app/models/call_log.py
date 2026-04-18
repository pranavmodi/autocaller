"""Call log model."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum
import uuid


class CallOutcome(str, Enum):
    IN_PROGRESS = "in_progress"
    NO_ANSWER = "no_answer"
    VOICEMAIL = "voicemail"
    TRANSFERRED = "transferred"                  # legacy; unused in autocaller
    CALLBACK_REQUESTED = "callback_requested"
    WRONG_NUMBER = "wrong_number"
    DISCONNECTED = "disconnected"
    COMPLETED = "completed"
    FAILED = "failed"
    # -- Autocaller outcomes --
    DEMO_SCHEDULED = "demo_scheduled"
    NOT_INTERESTED = "not_interested"
    GATEKEEPER_ONLY = "gatekeeper_only"


class CallStatus(str, Enum):
    """High-level attempt status: did we successfully place the call?"""
    IN_PROGRESS = "in_progress"
    CALLED = "called"      # Call went out and reached the patient's phone
    FAILED = "failed"      # Call could not be placed (no carrier connection)


class CallDisposition(str, Enum):
    """Detailed disposition: what actually happened during or to the call."""
    IN_PROGRESS = "in_progress"
    TRANSFERRED = "transferred"              # legacy
    VOICEMAIL_LEFT = "voicemail_left"        # Reached voicemail
    NO_ANSWER = "no_answer"                  # Rang out, no one answered
    HUNG_UP = "hung_up"                      # Lead answered then disconnected
    CALLBACK_REQUESTED = "callback_requested"
    WRONG_NUMBER = "wrong_number"
    COMPLETED = "completed"                  # Call ended normally
    DISCONNECTED_NUMBER = "disconnected_number"
    TECHNICAL_ERROR = "technical_error"
    # -- Autocaller dispositions --
    DEMO_SCHEDULED = "demo_scheduled"
    NOT_INTERESTED = "not_interested"
    GATEKEEPER_ONLY = "gatekeeper_only"
    # -- IVR-specific --
    # Main line routed to a phone tree and we gave up (navigation off, or
    # navigator hit dead_end / timed_out). Actionable: operator should find
    # the lead's direct line or enable IVR navigation.
    IVR_UNREACHED = "ivr_unreached"
    # Hit a phone tree and successfully navigated it to a human. Combined
    # with the outcome (completed, demo_scheduled, not_interested, …) to
    # distinguish "first-contact-via-IVR" calls from direct dials.
    IVR_NAVIGATED = "ivr_navigated"


def derive_status_and_disposition(
    outcome: "CallOutcome",
    error_code: Optional[str] = None,
    had_patient_speech: bool = False,
    duration_seconds: int = 0,
    ivr_detected: bool = False,
    ivr_outcome: Optional[str] = None,
) -> tuple["CallStatus", "CallDisposition"]:
    """Derive CallStatus + CallDisposition from the outcome + IVR state + context.

    Rules:
    - No answer is NOT a fail — Called + NoAnswer.
    - Hang-up after answering is NOT a fail — Called + HungUp.
    - Only real carrier/technical failures (couldn't reach the phone at all)
      are Failed.
    - IVR overlay: if we hit a phone tree and didn't reach a human, the
      disposition is IVR_UNREACHED (not voicemail_left — that would confuse
      retry logic). If we DID reach a human via navigation, the disposition
      is IVR_NAVIGATED regardless of what happened in the downstream convo
      (the outcome enum carries the conversational result separately).
    """
    # IVR-first overrides — these are the most actionable signal for
    # follow-up routing so we short-circuit the rest.
    if ivr_detected:
        if ivr_outcome in ("reached_human", "queue_wait"):
            # queue_wait = navigator bridged us through a "please hold"
            # tree to a human pickup. Count as navigated.
            return CallStatus.CALLED, CallDisposition.IVR_NAVIGATED
        # skipped / dead_end / timed_out all collapse to "we hit a tree
        # and didn't get through".
        if ivr_outcome in ("skipped", "dead_end", "timed_out"):
            return CallStatus.CALLED, CallDisposition.IVR_UNREACHED
    # Pre-connect failures
    if outcome == CallOutcome.FAILED:
        if error_code == "media_stream_timeout":
            # Twilio call was placed but the media stream never connected.
            # Typically means the call rang out without being answered.
            return CallStatus.CALLED, CallDisposition.NO_ANSWER
        if error_code in ("twilio_no-answer", "twilio_busy"):
            # Twilio reported the call rang out or was busy — the call was
            # placed successfully, the patient just didn't pick up.
            return CallStatus.CALLED, CallDisposition.NO_ANSWER
        if error_code and error_code.isdigit():
            code = int(error_code)
            if code in (32005, 32009):  # invalid/disconnected number
                return CallStatus.FAILED, CallDisposition.DISCONNECTED_NUMBER
        # Everything else (openai_connect_failed, twilio_place_failed, etc.)
        return CallStatus.FAILED, CallDisposition.TECHNICAL_ERROR

    if outcome == CallOutcome.DISCONNECTED:
        # Media stream closed mid-call.  If patient spoke or call had real
        # duration, they answered then hung up.  Otherwise treat as a bad
        # number / carrier failure.
        if had_patient_speech or duration_seconds >= 5:
            return CallStatus.CALLED, CallDisposition.HUNG_UP
        return CallStatus.FAILED, CallDisposition.DISCONNECTED_NUMBER

    if outcome == CallOutcome.TRANSFERRED:
        return CallStatus.CALLED, CallDisposition.TRANSFERRED
    if outcome == CallOutcome.DEMO_SCHEDULED:
        return CallStatus.CALLED, CallDisposition.DEMO_SCHEDULED
    if outcome == CallOutcome.NOT_INTERESTED:
        return CallStatus.CALLED, CallDisposition.NOT_INTERESTED
    if outcome == CallOutcome.GATEKEEPER_ONLY:
        return CallStatus.CALLED, CallDisposition.GATEKEEPER_ONLY
    if outcome == CallOutcome.VOICEMAIL:
        return CallStatus.CALLED, CallDisposition.VOICEMAIL_LEFT
    if outcome == CallOutcome.CALLBACK_REQUESTED:
        return CallStatus.CALLED, CallDisposition.CALLBACK_REQUESTED
    if outcome == CallOutcome.WRONG_NUMBER:
        return CallStatus.CALLED, CallDisposition.WRONG_NUMBER
    if outcome == CallOutcome.NO_ANSWER:
        return CallStatus.CALLED, CallDisposition.NO_ANSWER
    if outcome == CallOutcome.COMPLETED:
        return CallStatus.CALLED, CallDisposition.COMPLETED

    return CallStatus.IN_PROGRESS, CallDisposition.IN_PROGRESS


@dataclass
class TranscriptEntry:
    """Single transcript entry."""
    speaker: str  # "ai" or "patient"
    text: str
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "speaker": self.speaker,
            "text": self.text,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class CallLog:
    """Record of an outbound call."""
    call_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    patient_id: str = ""
    patient_name: str = ""
    phone: str = ""
    order_id: Optional[str] = None
    priority_bucket: int = 0

    # Timing
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None
    duration_seconds: int = 0

    # Outcome
    outcome: CallOutcome = CallOutcome.IN_PROGRESS
    call_status: CallStatus = CallStatus.IN_PROGRESS
    call_disposition: CallDisposition = CallDisposition.IN_PROGRESS
    mock_mode: bool = False  # True if the call was redirected to mock_phone instead of the patient
    transfer_attempted: bool = False
    transfer_success: bool = False
    voicemail_left: bool = False
    sms_sent: bool = False
    preferred_callback_time: Optional[str] = None

    # Audio recording metadata
    recording_sid: Optional[str] = None
    recording_path: Optional[str] = None
    recording_size_bytes: Optional[int] = None
    recording_duration_seconds: Optional[int] = None
    recording_format: Optional[str] = None

    # Queue state at dial time
    queue_snapshot: Optional[dict] = None

    # Transcript
    transcript: list[TranscriptEntry] = field(default_factory=list)

    # Error info
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    # -- Autocaller post-call capture --
    pain_point_summary: Optional[str] = None
    interest_level: Optional[int] = None
    is_decision_maker: Optional[bool] = None
    was_gatekeeper: bool = False
    gatekeeper_contact: Optional[dict] = None
    demo_booking_id: Optional[str] = None
    demo_scheduled_at: Optional[datetime] = None
    demo_meeting_url: Optional[str] = None
    followup_email_sent: bool = False
    firm_name: Optional[str] = None
    lead_state: Optional[str] = None

    # Phase A: judge + GTM disposition (populated post-call by judge.py)
    judge_score: Optional[int] = None
    judge_scores: Optional[dict] = None
    judge_notes: Optional[dict] = None
    judged_at: Optional[datetime] = None
    prompt_version: Optional[str] = None
    prompt_text: Optional[str] = None
    tools_snapshot: Optional[list] = None
    gtm_disposition: Optional[str] = None
    follow_up_action: Optional[str] = None
    follow_up_when: Optional[datetime] = None
    follow_up_owner: Optional[str] = None
    follow_up_note: Optional[str] = None
    call_summary: Optional[str] = None
    signal_flags: Optional[list] = None
    pain_points_discussed: Optional[list] = None
    objections_raised: Optional[list] = None
    captured_contacts: Optional[list] = None
    dm_reachability: Optional[str] = None
    dnc_reason: Optional[str] = None

    # Which realtime voice backend + model handled this call.
    voice_provider: Optional[str] = None  # "openai" | "gemini"
    voice_model: Optional[str] = None     # exact model ID
    # Which telephony carrier placed this call ("twilio" | "telnyx").
    carrier: Optional[str] = None
    # "twilio" (PSTN via carrier) or "web" (browser mic, no phone).
    call_mode: str = "twilio"
    # Post-call Whisper transcript (more accurate than live Gemini STT).
    whisper_transcript: Optional[str] = None
    # IVR navigation record (populated if the phone tree was hit).
    ivr_detected: bool = False
    ivr_outcome: Optional[str] = None     # reached_human | dead_end | timed_out | skipped | not_ivr
    ivr_menu_log: Optional[list] = None

    def add_transcript(self, speaker: str, text: str):
        """Add a transcript entry."""
        self.transcript.append(TranscriptEntry(speaker=speaker, text=text))

    def end_call(self, outcome: CallOutcome):
        """Mark call as ended."""
        self.ended_at = datetime.now()
        self.outcome = outcome
        if self.started_at:
            self.duration_seconds = int((self.ended_at - self.started_at).total_seconds())

    def to_dict(self) -> dict:
        return {
            "call_id": self.call_id,
            "patient_id": self.patient_id,
            "patient_name": self.patient_name,
            "phone": self.phone,
            "order_id": self.order_id,
            "priority_bucket": self.priority_bucket,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_seconds": self.duration_seconds,
            "outcome": self.outcome.value,
            "call_status": self.call_status.value,
            "call_disposition": self.call_disposition.value,
            "mock_mode": self.mock_mode,
            "transfer_attempted": self.transfer_attempted,
            "transfer_success": self.transfer_success,
            "voicemail_left": self.voicemail_left,
            "sms_sent": self.sms_sent,
            "preferred_callback_time": self.preferred_callback_time,
            "queue_snapshot": self.queue_snapshot,
            "transcript": [t.to_dict() for t in self.transcript],
            "error_code": self.error_code,
            "error_message": self.error_message,
            "recording_sid": self.recording_sid,
            "recording_path": self.recording_path,
            "recording_size_bytes": self.recording_size_bytes,
            "recording_duration_seconds": self.recording_duration_seconds,
            "recording_format": self.recording_format,
            "has_recording": bool(self.recording_path),
            "pain_point_summary": self.pain_point_summary,
            "interest_level": self.interest_level,
            "is_decision_maker": self.is_decision_maker,
            "was_gatekeeper": self.was_gatekeeper,
            "gatekeeper_contact": self.gatekeeper_contact,
            "demo_booking_id": self.demo_booking_id,
            "demo_scheduled_at": self.demo_scheduled_at.isoformat() if self.demo_scheduled_at else None,
            "demo_meeting_url": self.demo_meeting_url,
            "followup_email_sent": self.followup_email_sent,
            "firm_name": self.firm_name,
            "lead_state": self.lead_state,
            "judge_score": self.judge_score,
            "judge_scores": self.judge_scores,
            "judge_notes": self.judge_notes,
            "judged_at": self.judged_at.isoformat() if self.judged_at else None,
            "prompt_version": self.prompt_version,
            "prompt_text": self.prompt_text,
            "tools_snapshot": self.tools_snapshot,
            "gtm_disposition": self.gtm_disposition,
            "follow_up_action": self.follow_up_action,
            "follow_up_when": self.follow_up_when.isoformat() if self.follow_up_when else None,
            "follow_up_owner": self.follow_up_owner,
            "follow_up_note": self.follow_up_note,
            "call_summary": self.call_summary,
            "signal_flags": self.signal_flags,
            "pain_points_discussed": self.pain_points_discussed,
            "objections_raised": self.objections_raised,
            "captured_contacts": self.captured_contacts,
            "dm_reachability": self.dm_reachability,
            "dnc_reason": self.dnc_reason,
            "voice_provider": self.voice_provider,
            "voice_model": self.voice_model,
            "ivr_detected": self.ivr_detected,
            "ivr_outcome": self.ivr_outcome,
            "ivr_menu_log": self.ivr_menu_log,
            "whisper_transcript": self.whisper_transcript,
            "call_mode": self.call_mode,
        }
