"""System settings models."""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class HolidayEntry:
    """Holiday calendar entry."""
    date: str  # YYYY-MM-DD
    name: str
    recurring: bool = True


@dataclass
class BusinessHours:
    """Business hours configuration."""
    start_time: str = "08:00"  # HH:MM format
    end_time: str = "17:00"    # HH:MM format
    enabled: bool = False
    timezone: str = "America/New_York"
    days_of_week: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])  # Mon-Fri (0=Mon, 6=Sun)
    holidays: List[HolidayEntry] = field(default_factory=list)


@dataclass
class QueueThresholds:
    """Queue gating thresholds for outbound calls."""
    calls_waiting_threshold: int = 1
    holdtime_threshold_seconds: int = 30
    stable_polls_required: int = 3


@dataclass
class DispatcherSettings:
    """Dispatcher configuration parameters."""
    poll_interval: int = 10
    dispatch_timeout: int = 30
    max_attempts: int = 3
    min_hours_between: int = 168  # 1 week — avoid re-calling a firm within 7 days
    cooldown_seconds: int = 0     # inter-call wait after a call ends before the next is placed
    verbose_logging: bool = False


@dataclass
class DailyReportConfig:
    """Daily Slack report configuration (posts yesterday's call summary)."""
    enabled: bool = False
    webhook_url: str = ""
    hour: int = 7  # 0-23 local time
    timezone: str = "America/Los_Angeles"


@dataclass
class CalComConfig:
    """Cal.com integration settings (API key lives in env, not DB)."""
    event_type_id: Optional[int] = None
    default_timezone: str = "America/New_York"


@dataclass
class SalesContext:
    """Per-operator sales-rep context injected into the AI system prompt."""
    rep_name: str = ""
    rep_company: str = ""
    rep_email: str = ""
    product_context: str = ""


@dataclass
class PerStateHours:
    """Default calling window enforced in each lead's local timezone."""
    start: str = "09:00"
    end: str = "17:00"
    days: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])


@dataclass
class SystemSettings:
    """Main system settings."""
    system_enabled: bool = True
    business_hours: BusinessHours = field(default_factory=BusinessHours)
    queue_thresholds: QueueThresholds = field(default_factory=QueueThresholds)
    dispatcher_settings: DispatcherSettings = field(default_factory=DispatcherSettings)
    allow_live_calls: bool = False
    allowed_phones: List[str] = field(default_factory=list)
    queue_source: str = "simulation"
    patient_source: str = "simulation"
    active_scenario_id: Optional[str] = None
    call_mode: str = "web"  # "web" or "twilio"
    mock_mode: bool = False
    mock_phone: str = ""  # redirect Twilio calls/SMS here when mock_mode=True
    daily_report: DailyReportConfig = field(default_factory=DailyReportConfig)
    # Autocaller fields
    calcom_config: CalComConfig = field(default_factory=CalComConfig)
    sales_context: SalesContext = field(default_factory=SalesContext)
    per_state_hours: PerStateHours = field(default_factory=PerStateHours)
    # Default realtime voice backend ("openai" or "gemini"). Override per-call
    # via CLI --voice flag or API body voice_provider field.
    voice_provider: str = "openai"
    voice_model: str = ""
    # Default telephony carrier ("twilio" or "telnyx"). Override per-call via
    # CLI --carrier flag or API body `carrier` field.
    default_carrier: str = "twilio"
    # When True, the orchestrator invokes IVRNavigator on IVR detection
    # (tries to press digits to reach a human) instead of hanging up.
    ivr_navigate_enabled: bool = False
