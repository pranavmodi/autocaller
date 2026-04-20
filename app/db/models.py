"""SQLAlchemy ORM table models."""
from datetime import datetime, timezone
from sqlalchemy import (
    String, Integer, Boolean, Text, Index, CheckConstraint,
    ForeignKey,
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

    # -- Autocaller-specific configuration --
    calcom_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    sales_context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    per_state_hours: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Default realtime voice backend. Overridden per call via CLI flag or API body.
    voice_provider: Mapped[str] = mapped_column(String(32), default="openai")
    voice_model: Mapped[str] = mapped_column(String(64), default="")
    # Default telephony carrier ("twilio" | "telnyx"). Per-call override via
    # CLI --carrier / API body. See app/services/carrier.py.
    default_carrier: Mapped[str] = mapped_column(String(16), default="twilio")
    # Whether the AI should try to navigate phone trees (press digits to reach
    # a human) instead of hanging up as soon as an IVR is detected.
    ivr_navigate_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

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
