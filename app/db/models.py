"""SQLAlchemy ORM table models."""
from datetime import date, datetime, timezone
from sqlalchemy import (
    String, Integer, BigInteger, Boolean, Text, Float, Date, Index, CheckConstraint,
    ForeignKey, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PatientRow(Base):
    """Lead record. Table name retained as `patients` from the original
    medical build; treated as attorney leads in the autocaller."""
    __tablename__ = "patients"

    patient_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)

    # -- Attorney / lead fields --
    firm_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    practice_area: Mapped[str | None] = mapped_column(String(128), nullable=True)
    website: Mapped[str | None] = mapped_column(String(512), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    name_is_person: Mapped[bool] = mapped_column(Boolean, default=True)

    # -- Legacy medical columns (nullable, unused by autocaller) --
    language: Mapped[str] = mapped_column(String(5), default="en")
    order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    order_created: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    intake_status: Mapped[str] = mapped_column(String(20), default="complete")
    has_called_in_before: Mapped[bool] = mapped_column(Boolean, default=False)
    has_abandoned_before: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_called_before: Mapped[bool] = mapped_column(Boolean, default=False)

    # -- Retry / attempt tracking (shared) --
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    last_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    due_by: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    priority_bucket: Mapped[int] = mapped_column(Integer, default=4)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_patients_priority_due", "priority_bucket", "due_by"),
        Index("ix_patients_phone", "phone"),
        Index("ix_patients_state", "state"),
    )


class CallLogRow(Base):
    __tablename__ = "call_logs"

    call_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    patient_id: Mapped[str] = mapped_column(String(64), nullable=False)
    patient_name: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    priority_bucket: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    outcome: Mapped[str] = mapped_column(String(32), default="in_progress")
    call_status: Mapped[str] = mapped_column(String(32), default="in_progress")
    call_disposition: Mapped[str] = mapped_column(String(32), default="in_progress")
    mock_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    # Audio recording (stored on disk, metadata only in DB)
    recording_sid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recording_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    recording_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recording_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recording_format: Mapped[str | None] = mapped_column(String(16), nullable=True)
    transfer_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    transfer_success: Mapped[bool] = mapped_column(Boolean, default=False)
    voicemail_left: Mapped[bool] = mapped_column(Boolean, default=False)
    # True if the operator pressed "Take over" at any point during the
    # call. Triggers segment-level Whisper backfill post-call (live
    # transcript is incomplete when takeover is active because the
    # operator's side isn't fed to the voice backend).
    takeover_used: Mapped[bool] = mapped_column(Boolean, default=False)
    sms_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    preferred_callback_time: Mapped[str | None] = mapped_column(String(255), nullable=True)
    queue_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    transcript: Mapped[list] = mapped_column(JSONB, default=list)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # -- Autocaller post-call capture --
    pain_point_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    interest_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_decision_maker: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    was_gatekeeper: Mapped[bool] = mapped_column(Boolean, default=False)
    gatekeeper_contact: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    demo_booking_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    demo_scheduled_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    demo_meeting_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    followup_email_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    firm_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lead_state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    # -- Phase A: judge scoring + GTM disposition --
    judge_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    judge_scores: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    judge_notes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    judged_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # GTM disposition (see docs/DISPOSITIONS.md)
    gtm_disposition: Mapped[str | None] = mapped_column(String(64), nullable=True)
    follow_up_action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    follow_up_when: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    follow_up_owner: Mapped[str | None] = mapped_column(String(32), nullable=True)
    follow_up_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    call_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    signal_flags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    pain_points_discussed: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    objections_raised: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    captured_contacts: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    dm_reachability: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dnc_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Raw prompt + tools sent to OpenAI for this call — for debugging AI behavior
    prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    tools_snapshot: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Which realtime voice backend handled this call.
    # voice_provider = "openai" | "gemini"; voice_model is the exact model ID
    # (e.g. "gpt-realtime-2025-08-28" or "gemini-3.1-flash-live").
    voice_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    voice_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Telephony carrier that placed this call ("twilio" | "telnyx").
    # Null on legacy rows — treat null as twilio.
    carrier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    call_mode: Mapped[str] = mapped_column(String(16), default="twilio")
    # Post-call Whisper transcription (more accurate than live Gemini STT).
    whisper_transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    # IVR navigation (populated only when the phone tree was hit).
    # ivr_outcome values: reached_human | dead_end | timed_out | skipped | not_ivr
    ivr_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    ivr_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ivr_menu_log: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Who ended the call. Set once, at call teardown. Values:
    #   ai_tool            — model invoked the end_call tool
    #   vm_detect          — caller-audio VM/IVR phrase matcher
    #   ivr_navigator      — IVR navigator hit dead_end/timed_out/not_ivr
    #   silence_watchdog   — no caller speech inside the silence timeout
    #   stream_closed      — carrier WS closed first (they hung up / network drop)
    #   error              — early-failure path during start_call()
    #   manual             — operator hang-up from the UI
    # Null on legacy rows.
    ended_by: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Carrier teardown invariant: `ended_at IS NOT NULL` iff the carrier has
    # acknowledged the call is terminal. Before that, a row is in one of
    # the non-terminal `termination_state` values and `ended_at` stays NULL.
    # The reconciler sweeps any non-terminal row to re-verify via carrier API.
    carrier_call_sid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    termination_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="live", server_default="live",
    )
    termination_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    termination_last_checked_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True,
    )

    __table_args__ = (
        Index("ix_call_logs_patient_id", "patient_id"),
        Index("ix_call_logs_started_at", "started_at"),
        Index("ix_call_logs_outcome", "outcome"),
        Index("ix_call_logs_call_status", "call_status"),
        Index("ix_call_logs_call_disposition", "call_disposition"),
        Index("ix_call_logs_voice_provider", "voice_provider"),
        Index("ix_call_logs_carrier", "carrier"),
        Index("ix_call_logs_ivr_outcome", "ivr_outcome"),
    )


class IntakeCallSessionRow(Base):
    """Inbound after-hours PI intake calls.

    Kept separate from outbound `call_logs` because these calls are product
    demos / client intake sessions, not Possible Minds sales touches.
    """
    __tablename__ = "intake_call_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    stream_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    carrier: Mapped[str] = mapped_column(String(16), nullable=False, default="telnyx")
    carrier_call_control_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    caller_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dialed_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="started")
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    consent_recording: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    transcript: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    intake_packet: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    urgency_flags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    notification_recipient: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notification_sent_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    notification_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow,
    )

    __table_args__ = (
        Index("ix_intake_call_sessions_started_at", "started_at"),
        Index("ix_intake_call_sessions_status", "status"),
        Index("ix_intake_call_sessions_caller_number", "caller_number"),
        Index("ix_intake_call_sessions_stream_id", "stream_id"),
    )


class SystemSettingsRow(Base):
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    system_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    business_hours: Mapped[dict] = mapped_column(JSONB, nullable=False)
    queue_thresholds: Mapped[dict] = mapped_column(JSONB, nullable=False)
    dispatcher_settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    allow_live_calls: Mapped[bool] = mapped_column(Boolean, default=False)
    allowed_phones: Mapped[list] = mapped_column(JSONB, default=list)
    queue_source: Mapped[str] = mapped_column(String(20), default="simulation")
    patient_source: Mapped[str] = mapped_column(String(20), default="simulation")
    active_scenario_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("simulation_scenarios.id", ondelete="SET NULL"), nullable=True
    )
    call_mode: Mapped[str] = mapped_column(String(20), default="web")
    mock_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    mock_phone: Mapped[str] = mapped_column(String(32), default="")
    daily_report: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    agent_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # -- Autocaller-specific configuration --
    calcom_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    sales_context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    per_state_hours: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Default realtime voice backend. Overridden per call via CLI flag or API body.
    voice_provider: Mapped[str] = mapped_column(String(32), default="openai")
    voice_model: Mapped[str] = mapped_column(String(64), default="")
    # Per-provider voice knobs (voice name, affective-dialog flag,
    # proactive-audio flag, temperature). Schema docs in the Alembic
    # migration x8y9z0a1b2c3_add_voice_config.py. Missing keys fall back
    # to env-var defaults at connect time.
    voice_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Default telephony carrier ("twilio" | "telnyx"). Per-call override via
    # CLI --carrier / API body. See app/services/carrier.py.
    default_carrier: Mapped[str] = mapped_column(String(16), default="twilio")
    # Whether the AI should try to navigate phone trees (press digits to reach
    # a human) instead of hanging up as soon as an IVR is detected.
    ivr_navigate_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Active voice-AI prompt style. "current" = the long Sobczak-style
    # cold-call prompt; "minimal" = trimmed-down variant. Persisted
    # here so operators can flip from CLI/UI without a daemon restart;
    # PROMPT_STYLE env var, if set, takes precedence at boot only.
    prompt_style: Mapped[str] = mapped_column(String(32), default="current")

    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        CheckConstraint("id = 1", name="singleton_settings"),
    )


class DispatcherEventRow(Base):
    __tablename__ = "dispatcher_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    decision: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        Index("ix_dispatcher_events_timestamp", "timestamp"),
        Index("ix_dispatcher_events_decision", "decision"),
    )


class ConsultBookingRow(Base):
    """Free 30-minute consult bookings from getpossibleminds.com/consult.

    Created by the public booking endpoint (no auth — rate-limited by IP)
    and surfaced in the autocaller admin UI at `/consults`. A Telnyx SMS
    fires on create to NOTIFY_NUMBER so the operator is pinged in real time.
    """
    __tablename__ = "consult_bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    firm_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    slot_start: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    slot_end: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="booked")
    source: Mapped[str] = mapped_column(String(32), default="website")
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    # Operator ack timestamp. NULL = the UI popup hasn't been dismissed
    # yet; set once acknowledged so the popup never fires again for this
    # booking. One popup per consult, ever.
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True,
    )

    __table_args__ = (
        Index("ix_consult_bookings_slot_start", "slot_start"),
        Index("ix_consult_bookings_created_at", "created_at"),
        Index("ix_consult_bookings_email", "email"),
    )


class OperatorNotificationRow(Base):
    """Persisted operator-facing notifications surfaced as dashboard modals.

    These are durable control-loop alerts: a backend worker creates one when a
    stimulus needs human attention, the UI polls for unacknowledged rows, and
    acknowledgement prevents repeat popups after reloads or restarts.
    """
    __tablename__ = "operator_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    notification_type: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    stimulus_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    context_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    suggested_action_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow,
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True,
    )
    acknowledged_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "notification_type", "source_type", "source_id",
            name="uq_operator_notifications_source",
        ),
        Index("ix_operator_notifications_pending", "status", "acknowledged_at"),
        Index("ix_operator_notifications_created_at", "created_at"),
        Index("ix_operator_notifications_type", "notification_type"),
    )


class TodoRow(Base):
    """Editable operator/project todos stored in the database."""
    __tablename__ = "todos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    area: Mapped[str] = mapped_column(String(64), nullable=False, default="general")
    section: Mapped[str] = mapped_column(String(64), nullable=False, default="Not Started")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_started")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow,
    )

    __table_args__ = (
        UniqueConstraint("area", "title", name="uq_todos_area_title"),
        Index("ix_todos_area_status", "area", "status"),
        Index("ix_todos_updated_at", "updated_at"),
    )


class DataReturnedRow(Base):
    """Append-only payloads received by the public /datareturned endpoint."""
    __tablename__ = "data_returned_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    payload_json: Mapped[dict | list] = mapped_column(JSONB, nullable=False)
    headers_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    received_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("ix_data_returned_events_received_at", "received_at"),
        Index("ix_data_returned_events_source_ip", "source_ip"),
    )


class DataReturnedScriptRow(Base):
    """Singleton operator-edited shell script served by /datareturned/script."""
    __tablename__ = "data_returned_script"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    script_text: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow,
    )


class ProductTraceRow(Base):
    """Append-only AI-legible trace ledger for user and system actions."""
    __tablename__ = "product_traces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    surface: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    entity_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parent_trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    output_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    diff_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    context_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("ix_product_traces_trace_id", "trace_id"),
        Index("ix_product_traces_session_id", "session_id"),
        Index("ix_product_traces_request_id", "request_id"),
        Index("ix_product_traces_event_type", "event_type"),
        Index("ix_product_traces_surface", "surface"),
        Index("ix_product_traces_entity", "entity_type", "entity_id"),
        Index("ix_product_traces_created_at", "created_at"),
    )


class AgentTaskRow(Base):
    """Durable task packet delegated by the Possible OS master agent."""
    __tablename__ = "agent_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    parent_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assigned_agent: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    context_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    allowed_tools_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    forbidden_actions_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    expected_output_schema_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    acceptance_criteria_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    verification_commands_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    artifacts_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    requires_human_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    heartbeat_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'accepted', 'running', 'waiting_on_tool', "
            "'waiting_on_user', 'blocked', 'completed', 'failed', 'cancelled', 'stale')",
            name="ck_agent_tasks_status",
        ),
        Index("ix_agent_tasks_status", "status"),
        Index("ix_agent_tasks_agent_status", "assigned_agent", "status"),
        Index("ix_agent_tasks_updated_at", "updated_at"),
        Index("ix_agent_tasks_last_heartbeat", "last_heartbeat_at"),
    )


class AgentTaskEventRow(Base):
    """Append-only lifecycle events for master/subagent task coordination."""
    __tablename__ = "agent_task_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("agent_tasks.id", ondelete="CASCADE"), nullable=True,
    )
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    output_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("ix_agent_task_events_task_id", "task_id"),
        Index("ix_agent_task_events_agent_type", "agent_id", "event_type"),
        Index("ix_agent_task_events_created_at", "created_at"),
    )


class AgentReportRow(Base):
    """Structured report-back artifact created by a subagent or master heartbeat."""
    __tablename__ = "agent_reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("agent_tasks.id", ondelete="CASCADE"), nullable=True,
    )
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="reported")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    key_findings_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    actions_taken_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    artifacts_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    evidence_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    verification_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    risks_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    open_questions_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    recommended_next_actions_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("ix_agent_reports_task_id", "task_id"),
        Index("ix_agent_reports_agent_status", "agent_id", "status"),
        Index("ix_agent_reports_created_at", "created_at"),
    )


class AgentActionRow(Base):
    """Durable execution request for a bounded Possible OS action."""
    __tablename__ = "agent_actions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    action_type: Mapped[str] = mapped_column(String(96), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    requested_by: Mapped[str] = mapped_column(String(128), nullable=False, default="operator")
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    policy_result_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    execution_result_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed', 'waiting_for_approval', 'approved', 'queued', "
            "'running', 'succeeded', 'failed', 'cancelled', 'expired', 'blocked', 'observed')",
            name="ck_agent_actions_status",
        ),
        Index("ix_agent_actions_status", "status"),
        Index("ix_agent_actions_type_status", "action_type", "status"),
        Index("ix_agent_actions_entity", "entity_type", "entity_id"),
        Index("ix_agent_actions_created_at", "created_at"),
    )


class AgentActionEventRow(Base):
    """Append-only event timeline for durable action execution."""
    __tablename__ = "agent_action_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_actions.id", ondelete="CASCADE"), nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False, default="system")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    output_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("ix_agent_action_events_action_id", "action_id"),
        Index("ix_agent_action_events_type", "event_type"),
        Index("ix_agent_action_events_created_at", "created_at"),
    )


class AgentCapabilityRow(Base):
    """Discovered or declared tool/capability available to the master agent."""
    __tablename__ = "agent_capabilities"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    capability_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    purpose: Mapped[str] = mapped_column(Text, nullable=False, default="")
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    autonomous_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    command_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    last_verified_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow,
    )

    __table_args__ = (
        UniqueConstraint("name", "source", name="uq_agent_capabilities_name_source"),
        Index("ix_agent_capabilities_type", "capability_type"),
        Index("ix_agent_capabilities_risk", "risk_level"),
        Index("ix_agent_capabilities_status", "last_status"),
    )


class MasterGoalRow(Base):
    """Durable adaptive operating goal synthesized by the master agent."""
    __tablename__ = "master_goals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    why: Mapped[str] = mapped_column(Text, nullable=False, default="")
    time_horizon: Mapped[str] = mapped_column(String(64), nullable=False, default="current heartbeat")
    success_metric: Mapped[str] = mapped_column(Text, nullable=False, default="")
    next_actions_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    source_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    confidence: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="master-agent")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_master_goals_status_created", "status", "created_at"),
    )


class ImprovementFindingRow(Base):
    """Repeated trace/outcome pattern that may justify changing the system."""
    __tablename__ = "improvement_findings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    finding_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    workflow: Mapped[str] = mapped_column(String(64), nullable=False)
    finding_type: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_trace_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    evidence_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suggested_change_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="proposed")
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed', 'accepted', 'rejected', 'implemented')",
            name="ck_improvement_findings_status",
        ),
        Index("ix_improvement_findings_workflow", "workflow"),
        Index("ix_improvement_findings_type", "finding_type"),
        Index("ix_improvement_findings_status", "status"),
        Index("ix_improvement_findings_created_at", "created_at"),
    )


class EvalCaseRow(Base):
    """Small behavior test derived from an accepted improvement finding."""
    __tablename__ = "eval_cases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    finding_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("improvement_findings.id", ondelete="SET NULL"), nullable=True,
    )
    workflow: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    input_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    expected_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_eval_cases_status",
        ),
        Index("ix_eval_cases_finding_id", "finding_id"),
        Index("ix_eval_cases_workflow", "workflow"),
        Index("ix_eval_cases_created_at", "created_at"),
    )


class CodexTaskPacketRow(Base):
    """Focused implementation packet generated from a reviewed finding."""
    __tablename__ = "codex_task_packets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    finding_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("improvement_findings.id", ondelete="SET NULL"), nullable=True,
    )
    eval_case_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("eval_cases.id", ondelete="SET NULL"), nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    packet_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    traces_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    eval_cases_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    relevant_files_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    validation_commands_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    exported_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'approved', 'exported')",
            name="ck_codex_task_packets_status",
        ),
        Index("ix_codex_task_packets_finding_id", "finding_id"),
        Index("ix_codex_task_packets_status", "status"),
        Index("ix_codex_task_packets_created_at", "created_at"),
    )


class FirmReviewRow(Base):
    """Operator-pasted reviews for a firm, keyed on Mediflow pif_id.

    The /firms/[id] detail page is backed by an external service that
    doesn't store anything we can dump reviews into, so autocaller
    holds a local free-form text blob — pasted from Google Maps, Yelp,
    avvo, etc. One row per firm; overwriting the content is the
    update path.
    """
    __tablename__ = "firm_reviews"

    pif_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Legacy combined-blob column from the original single-textarea
    # version. The API no longer reads or writes it; kept in-schema
    # so existing rows aren't wiped. Drop in a later migration once
    # we're confident nothing else references it.
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    google_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    yelp_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow,
    )


class EmailLogRow(Base):
    """Outbound-email send log. One row per `_send_email` call that
    reached the provider (success or failure). Calls live in
    `call_logs`; SMS lives in `sms_logs`; the dashboard assembler
    unions all three by `pif_id` + timestamp. Engagement events
    (opens, clicks, replies) are out of scope for v1."""
    __tablename__ = "email_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pif_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    call_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False)
    recipient_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str] = mapped_column(Text, default="")
    body_excerpt: Mapped[str] = mapped_column(Text, default="")
    message_type: Mapped[str] = mapped_column(String(64), default="other")
    transport: Mapped[str] = mapped_column(String(16), default="resend")
    message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="sent")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    brief_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow,
    )

    __table_args__ = (
        Index("ix_email_logs_pif_id", "pif_id"),
        Index("ix_email_logs_call_id", "call_id"),
        Index("ix_email_logs_sent_at", "sent_at"),
    )


class InboundEmailRow(Base):
    """Normalized inbound mailbox messages read from Zoho IMAP.

    This is the incoming-email sensor for the lead-gen loop. Rows are
    append-only/idempotent by provider account + mailbox UID; processing can
    match a message to a contact, sequence, and lead-gen batch item.
    """
    __tablename__ = "inbound_emails"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="zoho_imap")
    account_email: Mapped[str] = mapped_column(String(320), nullable=False)
    mailbox: Mapped[str] = mapped_column(String(255), nullable=False, default="INBOX")
    uid: Mapped[str] = mapped_column(String(64), nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    in_reply_to: Mapped[str | None] = mapped_column(String(512), nullable=True)
    references_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_email: Mapped[str] = mapped_column(String(320), nullable=False)
    from_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    to_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    cc_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    subject: Mapped[str] = mapped_column(Text, nullable=False, default="")
    text_excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    raw_headers_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    matched_contact_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("firm_contacts.id", ondelete="SET NULL"), nullable=True,
    )
    matched_pif_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    matched_batch_item_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("lead_gen_batch_items.id", ondelete="SET NULL"), nullable=True,
    )
    matched_sequence_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("email_sequences.id", ondelete="SET NULL"), nullable=True,
    )
    lead_gen_observation_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("lead_gen_observations.id", ondelete="SET NULL"), nullable=True,
    )
    classification_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    received_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint(
            "provider", "account_email", "mailbox", "uid",
            name="uq_inbound_emails_provider_account_mailbox_uid",
        ),
        Index("ix_inbound_emails_from_email", "from_email"),
        Index("ix_inbound_emails_received_at", "received_at"),
        Index("ix_inbound_emails_matched_contact", "matched_contact_id"),
        Index("ix_inbound_emails_matched_batch_item", "matched_batch_item_id"),
        Index("ix_inbound_emails_classification_status", "classification_status"),
    )


class SmsLogRow(Base):
    """Outbound-SMS send log. Same shape philosophy as `email_logs`:
    a row per Twilio `messages.create` attempt, with status reflecting
    what we knew at submission time. Async delivery callbacks
    (`delivered`/`undelivered`) are not wired in v1."""
    __tablename__ = "sms_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pif_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    call_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recipient_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    recipient_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str] = mapped_column(Text, default="")
    message_sid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="sent")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow,
    )

    __table_args__ = (
        Index("ix_sms_logs_pif_id", "pif_id"),
        Index("ix_sms_logs_call_id", "call_id"),
        Index("ix_sms_logs_sent_at", "sent_at"),
    )


class FirmContactRow(Base):
    """One row per known person at a PI firm. Backfilled from PIF Stats
    `leadership[]` plus the autocaller `patients` DM. `email` is the
    natural key alongside `pif_id` — the unique constraint blocks
    duplicate (firm, email) pairs."""
    __tablename__ = "firm_contacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pif_id: Mapped[str] = mapped_column(String(64), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    first_name: Mapped[str] = mapped_column(String(128), default="")
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="manual")
    front_contact_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    front_last_seen: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    tech_signals: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    persona: Mapped[str | None] = mapped_column(String(32), nullable=True)
    persona_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    persona_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    research_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow,
    )

    __table_args__ = (
        Index("ix_firm_contacts_pif_id", "pif_id"),
        Index("ix_firm_contacts_email", "email"),
        Index("ix_firm_contacts_front_contact_id", "front_contact_id"),
    )


class FrontContactRow(Base):
    """Read-only mirror of Front contacts used for person-level freshness."""
    __tablename__ = "front_contacts"

    front_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    handles: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    primary_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_synced_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    front_updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    raw_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_front_contacts_domain", "domain"),
        Index("ix_front_contacts_primary_email", "primary_email"),
        Index("ix_front_contacts_front_updated_at", "front_updated_at"),
    )


class FrontFirmActivityRow(Base):
    """Domain-level Front activity rollup with no message bodies."""
    __tablename__ = "front_firm_activity"

    domain: Mapped[str] = mapped_column(String(255), primary_key=True)
    pif_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_seen_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    last_referral_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    last_records_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    inbox_breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    tech_signals: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    behavioral_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    warm_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    synced_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("ix_front_firm_activity_pif_id", "pif_id"),
        Index("ix_front_firm_activity_warm_score", "warm_score"),
        Index("ix_front_firm_activity_last_seen", "last_seen_at"),
    )


class FrontSyncStateRow(Base):
    """Cursor/watermark state for budgeted Front API sync runs."""
    __tablename__ = "front_sync_state"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    watermark: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow)


class ResearchTaskRow(Base):
    """PIF Stats async research task tracked for polling and resume."""
    __tablename__ = "research_tasks"

    task_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    pif_id: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    requested_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    result_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('research', 'research_staff', 'analyze_behavior')",
            name="ck_research_tasks_kind",
        ),
        Index("ix_research_tasks_pif_id", "pif_id"),
        Index("ix_research_tasks_status", "status"),
        Index("ix_research_tasks_kind_status", "kind", "status"),
    )


class FirmCompetitiveFeatureRow(Base):
    """Local-cache-derived firm features used to score PI competitors."""
    __tablename__ = "firm_competitive_features"

    pif_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    firm_name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metro: Mapped[str | None] = mapped_column(String(64), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    case_mix: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    value_tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    volume_proxy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    computed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("ix_firm_competitive_features_domain", "domain"),
        Index("ix_firm_competitive_features_metro", "metro"),
        Index("ix_firm_competitive_features_value_tier", "value_tier"),
    )


class CompetitorEdgeRow(Base):
    """Undirected firm-vs-firm competition edge, stored once with a < b."""
    __tablename__ = "competitor_edges"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    firm_a_pif_id: Mapped[str] = mapped_column(String(64), nullable=False)
    firm_b_pif_id: Mapped[str] = mapped_column(String(64), nullable=False)
    metro: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    components: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    computed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint("firm_a_pif_id", "firm_b_pif_id", name="uq_competitor_edges_pair"),
        Index("ix_competitor_edges_firm_a", "firm_a_pif_id"),
        Index("ix_competitor_edges_firm_b", "firm_b_pif_id"),
        Index("ix_competitor_edges_metro", "metro"),
        Index("ix_competitor_edges_score", "score"),
    )


class EmailSequenceRow(Base):
    """Email sequence state for one (contact, template_key) pair.
    Strict v1 invariant: at most one sequence per template per contact.
    Restarts unsupported. The personalization fields (`frozen_*`) are
    captured at start-time so re-extracting Yelp reviews mid-sequence
    can't change what already-sent steps quoted."""
    __tablename__ = "email_sequences"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    contact_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("firm_contacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active")
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    steps_total: Mapped[int] = mapped_column(Integer, default=4)
    variant: Mapped[str] = mapped_column(String(32), default="with_quote")
    last_sent_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True,
    )
    next_step_due_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True,
    )
    paused_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    pain_point_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    frozen_pain_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    frozen_reviewer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    frozen_review_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_by: Mapped[str] = mapped_column(String(255), default="operator")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow,
    )

    __table_args__ = (
        Index("ix_email_sequences_due", "status", "next_step_due_at"),
    )


class QueueStateSnapshotRow(Base):
    __tablename__ = "queue_state_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    global_calls_waiting: Mapped[int] = mapped_column(Integer, default=0)
    global_max_holdtime: Mapped[int] = mapped_column(Integer, default=0)
    global_agents_available: Mapped[int] = mapped_column(Integer, default=0)
    outbound_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    stable_polls_count: Mapped[int] = mapped_column(Integer, default=0)
    ami_connected: Mapped[bool] = mapped_column(Boolean, default=True)
    queues: Mapped[list] = mapped_column(JSONB, default=list)

    __table_args__ = (
        Index("ix_queue_state_snapshots_timestamp", "timestamp"),
    )


class PatientCallStateRow(Base):
    """Local call state for live-mode patients (RadFlow is read-only)."""
    __tablename__ = "patient_call_state"

    patient_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    last_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ai_called_before: Mapped[bool] = mapped_column(Boolean, default=False)
    invalid_number: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_patient_call_state_updated", "updated_at"),
    )


class SimulationScenarioRow(Base):
    __tablename__ = "simulation_scenarios"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    ami_connected: Mapped[bool] = mapped_column(Boolean, default=True)
    queues: Mapped[list] = mapped_column(JSONB, default=list)
    patients: Mapped[list] = mapped_column(JSONB, default=list)
    dispatcher: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow)


class CadenceEntryRow(Base):
    """Tracks a firm through the multi-day outreach cadence."""
    __tablename__ = "cadence_entries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pif_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    firm_name: Mapped[str] = mapped_column(String(255), nullable=False)
    cadence_stage: Mapped[str] = mapped_column(String(32), nullable=False, default="signal_detected")
    stage_entered_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    next_action: Mapped[str | None] = mapped_column(String(128), nullable=True)
    next_action_due: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    owner: Mapped[str | None] = mapped_column(String(32), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="in_progress")
    call_ids: Mapped[list] = mapped_column(JSONB, default=list)
    contacts_tried: Mapped[list] = mapped_column(JSONB, default=list)
    available_contacts: Mapped[list] = mapped_column(JSONB, default=list)
    intel: Mapped[dict] = mapped_column(JSONB, default=dict)
    icp_tier: Mapped[str | None] = mapped_column(String(1), nullable=True)
    icp_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_cadence_stage", "cadence_stage"),
        Index("ix_cadence_outcome", "outcome"),
        Index("ix_cadence_next_due", "next_action_due"),
    )


class OutreachCampaignRow(Base):
    """One blog-post blast. Holds the post snapshot + sender + composer
    settings. Recipients live in OutreachSendRow joined by campaign_id."""
    __tablename__ = "outreach_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    post_slug: Mapped[str] = mapped_column(String(255), nullable=False)
    post_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    post_title: Mapped[str] = mapped_column(String(512), nullable=False)
    post_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    post_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    post_tags: Mapped[list] = mapped_column(JSONB, default=list)
    post_excerpts: Mapped[list] = mapped_column(JSONB, default=list)
    intent: Mapped[str] = mapped_column(String(32), nullable=False, default="share")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    sender_name: Mapped[str] = mapped_column(String(128), nullable=False)
    sender_email: Mapped[str] = mapped_column(String(320), nullable=False)
    sender_title: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bcc_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    composer_model: Mapped[str] = mapped_column(String(64), nullable=False, default="openclaw/proxy")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow,
    )

    __table_args__ = (
        Index("ix_outreach_campaigns_status", "status"),
        Index("ix_outreach_campaigns_post_slug", "post_slug"),
        Index("ix_outreach_campaigns_created_at", "created_at"),
    )


class OutreachSendRow(Base):
    """One row per (campaign, contact). Caches the LLM-composed email so
    preview + send always see the same content; the operator can also
    hand-edit (edited_* fields override composed_* at send time)."""
    __tablename__ = "outreach_sends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("outreach_campaigns.id", ondelete="CASCADE"), nullable=False,
    )
    contact_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("firm_contacts.id", ondelete="SET NULL"), nullable=True,
    )
    pif_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False)
    recipient_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recipient_first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    recipient_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    firm_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    token: Mapped[str] = mapped_column(String(64), nullable=False)

    composed_subject: Mapped[str | None] = mapped_column(String(512), nullable=True)
    composed_preheader: Mapped[str | None] = mapped_column(String(512), nullable=True)
    composed_body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    composed_plaintext: Mapped[str | None] = mapped_column(Text, nullable=True)
    composed_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    composed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    composer_model: Mapped[str | None] = mapped_column(String(64), nullable=True)

    edited_subject: Mapped[str | None] = mapped_column(String(512), nullable=True)
    edited_body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_plaintext: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    edited_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    send_attempted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transport: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint("campaign_id", "contact_id", name="uq_outreach_sends_campaign_contact"),
        UniqueConstraint("token", name="uq_outreach_sends_token"),
        Index("ix_outreach_sends_campaign_id", "campaign_id"),
        Index("ix_outreach_sends_status", "status"),
        Index("ix_outreach_sends_recipient_email", "recipient_email"),
        Index("ix_outreach_sends_sent_at", "sent_at"),
    )


class LinkEventRow(Base):
    """Append-only event log for email opens (pixel fetches) and clicks
    (link redirects). Joined to outreach_sends by send_id. Opens are
    soft signals (Apple Mail Privacy Protection pre-fetches); clicks
    are trustworthy."""
    __tablename__ = "link_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    send_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("outreach_sends.id", ondelete="CASCADE"), nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    referer: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    ts: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)

    __table_args__ = (
        CheckConstraint("kind IN ('open', 'click')", name="ck_link_events_kind"),
        Index("ix_link_events_send_id", "send_id"),
        Index("ix_link_events_kind_ts", "kind", "ts"),
    )


class AuditLinkClickRow(Base):
    """Append-only click log for contact-attributed freeware links."""
    __tablename__ = "audit_link_clicks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    contact_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("firm_contacts.id", ondelete="CASCADE"), nullable=False,
    )
    batch_item_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("lead_gen_batch_items.id", ondelete="SET NULL"), nullable=True,
    )
    pif_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    referer: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    clicked_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("ix_audit_link_clicks_contact_id", "contact_id"),
        Index("ix_audit_link_clicks_clicked_at", "clicked_at"),
    )


class AuditLinkRow(Base):
    """Short, clickable redirect codes used in plaintext lead-gen email.

    Reused for two destinations: the AI Audit page (kind="audit", the
    historical default) and the consult page (kind="consult"). Both record
    a click + lead-gen observation on resolve; only the redirect target and
    the observation channel differ.
    """
    __tablename__ = "audit_links"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    contact_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("firm_contacts.id", ondelete="CASCADE"), nullable=False,
    )
    batch_item_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("lead_gen_batch_items.id", ondelete="SET NULL"), nullable=True,
    )
    pif_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="audit", server_default="audit",
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("ix_audit_links_contact_id", "contact_id"),
        Index("ix_audit_links_created_at", "created_at"),
    )


class VisibilityLinkRow(Base):
    """Short, clickable AI Visibility report redirect codes used in plaintext email."""
    __tablename__ = "visibility_links"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    contact_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("firm_contacts.id", ondelete="CASCADE"), nullable=False,
    )
    batch_item_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("lead_gen_batch_items.id", ondelete="SET NULL"), nullable=True,
    )
    pif_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scan_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("ix_visibility_links_contact_id", "contact_id"),
        Index("ix_visibility_links_created_at", "created_at"),
    )


class LeadGenPolicyVersionRow(Base):
    """Versioned, auditable scoring policy for cybernetic lead generation.

    LLMs can propose changes, but the active policy is always explicit JSON
    read by deterministic recommendation code.
    """
    __tablename__ = "lead_gen_policy_versions"

    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    target_metric: Mapped[str] = mapped_column(
        String(64), nullable=False, default="booked_qualified_conversations",
    )
    weights_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    suppressions_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("ix_lead_gen_policy_versions_active", "active"),
        Index("ix_lead_gen_policy_versions_created_at", "created_at"),
    )


class LeadGenBatchRow(Base):
    """One recommendation/execution batch for the lead-generation loop."""
    __tablename__ = "lead_gen_batches"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_metric: Mapped[str] = mapped_column(
        String(64), nullable=False, default="booked_qualified_conversations",
    )
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(
        String(64), ForeignKey("lead_gen_policy_versions.version", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="recommended")
    counts_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    experiment_status: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    experiment_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    experiment_updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    experiment_closed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('recommended', 'approved', 'sequencing', 'observing', 'completed', 'archived')",
            name="ck_lead_gen_batches_status",
        ),
        CheckConstraint(
            "experiment_status IN ('none', 'draft', 'ready', 'scheduled', 'measuring', 'awaiting_verdict', 'closed', 'superseded')",
            name="ck_lead_gen_batches_experiment_status",
        ),
        Index("ix_lead_gen_batches_status", "status"),
        Index("ix_lead_gen_batches_experiment_status", "experiment_status"),
        Index("ix_lead_gen_batches_template", "template_key"),
        Index("ix_lead_gen_batches_created_at", "created_at"),
    )


class LeadGenBatchItemRow(Base):
    """One recommended contact in a lead-generation batch."""
    __tablename__ = "lead_gen_batch_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    batch_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("lead_gen_batches.id", ondelete="CASCADE"), nullable=False,
    )
    contact_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("firm_contacts.id", ondelete="CASCADE"), nullable=False,
    )
    pif_id: Mapped[str] = mapped_column(String(64), nullable=False)
    firm_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    contact_email: Mapped[str] = mapped_column(String(320), nullable=False)
    contact_title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    persona: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    approval_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    sequence_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("email_sequences.id", ondelete="SET NULL"), nullable=True,
    )
    outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome_confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow,
    )

    __table_args__ = (
        CheckConstraint(
            "approval_status IN ('pending', 'approved', 'rejected', 'started', 'skipped')",
            name="ck_lead_gen_batch_items_approval_status",
        ),
        UniqueConstraint("batch_id", "contact_id", name="uq_lead_gen_batch_items_batch_contact"),
        Index("ix_lead_gen_batch_items_batch_id", "batch_id"),
        Index("ix_lead_gen_batch_items_contact_id", "contact_id"),
        Index("ix_lead_gen_batch_items_pif_id", "pif_id"),
        Index("ix_lead_gen_batch_items_outcome", "outcome"),
    )


class LeadGenDailyRunRow(Base):
    """Checkpointed daily lead-selection and drafting pipeline run."""
    __tablename__ = "lead_gen_daily_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    stage: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    stages_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    batch_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("lead_gen_batches.id", ondelete="SET NULL"), nullable=True,
    )
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'partial', 'completed', 'failed', 'skipped')",
            name="ck_lead_gen_daily_runs_status",
        ),
        Index("ix_lead_gen_daily_runs_run_date", "run_date"),
        Index("ix_lead_gen_daily_runs_status", "status"),
        Index("ix_lead_gen_daily_runs_created_at", "created_at"),
    )


class LeadGenObservationRow(Base):
    """Append-only observation log for feedback entering the loop."""
    __tablename__ = "lead_gen_observations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    batch_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("lead_gen_batches.id", ondelete="SET NULL"), nullable=True,
    )
    batch_item_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("lead_gen_batch_items.id", ondelete="SET NULL"), nullable=True,
    )
    contact_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("firm_contacts.id", ondelete="SET NULL"), nullable=True,
    )
    pif_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_event_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    classified_outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    llm_raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint("event_type", "dedupe_key", name="uq_lead_gen_observations_event_dedupe"),
        Index("ix_lead_gen_observations_batch_id", "batch_id"),
        Index("ix_lead_gen_observations_contact_id", "contact_id"),
        Index("ix_lead_gen_observations_dedupe_key", "dedupe_key"),
        Index("ix_lead_gen_observations_event_type", "event_type"),
        Index("ix_lead_gen_observations_outcome", "classified_outcome"),
        Index("ix_lead_gen_observations_created_at", "created_at"),
    )


class LeadGenPolicyProposalRow(Base):
    """Human-reviewed policy/copy/scoring change proposal."""
    __tablename__ = "lead_gen_policy_proposals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_batch_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("lead_gen_batches.id", ondelete="SET NULL"), nullable=True,
    )
    proposal_type: Mapped[str] = mapped_column(String(64), nullable=False)
    proposed_change_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    evidence_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'applied')",
            name="ck_lead_gen_policy_proposals_status",
        ),
        Index("ix_lead_gen_policy_proposals_status", "status"),
        Index("ix_lead_gen_policy_proposals_source_batch", "source_batch_id"),
        Index("ix_lead_gen_policy_proposals_created_at", "created_at"),
    )


class PifFirmRow(Base):
    """Native mirror of emailtag's PifInfo — the PI-firm directory.

    Pulled directly from the emailtag pif-info API into possibleos Postgres so
    the lead-gen matching universe no longer depends on mission.db (whose
    Mission Control sync stopped running in March 2026). Captures every
    extracted field; `raw_json` holds the curated firm-intel profile and
    `source_json` holds the complete EmailTag pif_info source record so no
    future field is ever lost. Population is gated by PIF_DIRECTORY_NATIVE.

    Note: `extraction_notes` (and conversation context) can contain patient
    names (PHI). This data is for internal selection/targeting only and must
    never be emitted in outreach — the PHI egress guard remains authoritative.
    """
    __tablename__ = "pif_directory_firms"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # emailtag uuid
    firm_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    website: Mapped[str | None] = mapped_column(String(512), nullable=True)
    canonical_website: Mapped[str | None] = mapped_column(String(512), nullable=True)
    metro: Mapped[str | None] = mapped_column(String(128), nullable=True)
    warm_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    vendor_stack: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    profile_source: Mapped[str | None] = mapped_column(String(8), nullable=True)
    manually_added: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fax: Mapped[str | None] = mapped_column(String(64), nullable=True)
    icp_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    icp_tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    research_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    staff_research_status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Full extracted data (kept as JSONB to mirror emailtag exactly).
    emails: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    phones: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    addresses: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    contacts: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    leadership: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    staff: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    contact_profiles: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    research_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    behavioral_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    score_breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    conversation_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    extraction_notes: Mapped[str | None] = mapped_column(Text, nullable=True)  # PHI-bearing; internal only
    raw_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # curated firm-intel profile
    source_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # full EmailTag pif_info row

    # Source timestamps (from emailtag).
    source_created_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    first_contacted_precise_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    last_researched_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    icp_scored_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    # Local bookkeeping.
    synced_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("ix_pif_directory_firms_icp_score", "icp_score"),
        Index("ix_pif_directory_firms_website", "website"),
        Index("ix_pif_directory_firms_canonical_website", "canonical_website"),
        Index("ix_pif_directory_firms_manually_added", "manually_added"),
        Index("ix_pif_directory_firms_source_updated_at", "source_updated_at"),
        Index("ix_pif_directory_firms_first_contacted_precise_at", "first_contacted_precise_at"),
    )


class SavedLeadSearchRow(Base):
    """Reusable server-persisted criteria for the Leads workspace."""
    __tablename__ = "saved_lead_searches"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    view: Mapped[str] = mapped_column(String(32), nullable=False, default="contacts")
    criteria_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="operator")
    updated_by: Mapped[str] = mapped_column(String(128), nullable=False, default="operator")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=_utcnow, onupdate=_utcnow,
    )

    __table_args__ = (
        CheckConstraint("view IN ('contacts')", name="ck_saved_lead_searches_view"),
        UniqueConstraint("view", "name", name="uq_saved_lead_searches_view_name"),
        Index("ix_saved_lead_searches_view_updated", "view", "updated_at"),
    )


class FirmAliasRow(Base):
    """Local alias index for resolving firm-intel domains, emails, and legacy IDs."""
    __tablename__ = "firm_intel_aliases"

    alias_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    alias_value: Mapped[str] = mapped_column(String(512), primary_key=True)
    firm_id: Mapped[str] = mapped_column(String(64), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint("alias_type", "alias_value", name="uq_firm_intel_alias_type_value"),
        Index("ix_firm_intel_alias_value", "alias_value"),
        Index("ix_firm_intel_alias_firm_id", "firm_id"),
    )


class FirmIntelSyncStateRow(Base):
    """Singleton state row for the v2 firm-intel mirror watermark."""
    __tablename__ = "firm_intel_sync_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_updated_since: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    last_result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint("id = 1", name="singleton_firm_intel_sync_state"),
    )
