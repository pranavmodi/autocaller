"""Settings provider for system configuration — DB-backed."""
from datetime import datetime, date
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.db.models import SystemSettingsRow
from app.models import (
    BusinessHours,
    HolidayEntry,
    QueueThresholds,
    DispatcherSettings,
    DailyReportConfig,
    SystemSettings,
    CalComConfig,
    SalesContext,
    PerStateHours,
)
from typing import List


# Common timezones for selection
COMMON_TIMEZONES = [
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Phoenix",
    "America/Anchorage",
    "Pacific/Honolulu",
    "UTC",
]


def _normalize_holidays(raw_holidays) -> List[HolidayEntry]:
    items = raw_holidays if isinstance(raw_holidays, list) else []
    normalized: List[HolidayEntry] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        date_str = str(item.get("date", "")).strip()
        name = str(item.get("name", "")).strip()
        if not date_str or not name:
            continue
        recurring = bool(item.get("recurring", True))
        normalized.append(HolidayEntry(date=date_str, name=name, recurring=recurring))
    return normalized


def _is_holiday(today: date, holidays: List[HolidayEntry]) -> bool:
    for holiday in holidays:
        try:
            holiday_date = datetime.strptime(holiday.date, "%Y-%m-%d").date()
        except Exception:
            continue
        if holiday.recurring:
            if holiday_date.month == today.month and holiday_date.day == today.day:
                return True
        elif holiday_date == today:
            return True
    return False


def _matching_holiday(today: date, holidays: List[HolidayEntry]) -> Optional[HolidayEntry]:
    for holiday in holidays:
        try:
            holiday_date = datetime.strptime(holiday.date, "%Y-%m-%d").date()
        except Exception:
            continue
        if holiday.recurring:
            if holiday_date.month == today.month and holiday_date.day == today.day:
                return holiday
        elif holiday_date == today:
            return holiday
    return None


def _row_to_settings(row: SystemSettingsRow) -> SystemSettings:
    bh = row.business_hours
    qt = row.queue_thresholds
    settings = SystemSettings.__new__(SystemSettings)
    settings.system_enabled = row.system_enabled
    settings.business_hours = BusinessHours(
        start_time=bh.get("start_time", "08:00"),
        end_time=bh.get("end_time", "17:00"),
        enabled=bh.get("enabled", False),
        timezone=bh.get("timezone", "America/New_York"),
        days_of_week=bh.get("days_of_week", [0, 1, 2, 3, 4]),  # Default Mon-Fri
        holidays=_normalize_holidays(bh.get("holidays", [])),
    )
    settings.queue_thresholds = QueueThresholds(
        calls_waiting_threshold=qt.get("calls_waiting_threshold", 1),
        holdtime_threshold_seconds=qt.get("holdtime_threshold_seconds", 30),
        stable_polls_required=qt.get("stable_polls_required", 3),
    )
    ds = row.dispatcher_settings if row.dispatcher_settings else {}
    settings.dispatcher_settings = DispatcherSettings(
        poll_interval=ds.get("poll_interval", 10),
        dispatch_timeout=ds.get("dispatch_timeout", 30),
        max_attempts=ds.get("max_attempts", 3),
        min_hours_between=ds.get("min_hours_between", 6),
        cooldown_seconds=int(ds.get("cooldown_seconds", 0) or 0),
        default_batch_size=int(ds.get("default_batch_size", 5) or 5),
        verbose_logging=ds.get("verbose_logging", False),
    )
    settings.allow_live_calls = row.allow_live_calls if row.allow_live_calls is not None else False
    settings.allowed_phones = row.allowed_phones if row.allowed_phones is not None else []
    settings.queue_source = row.queue_source if row.queue_source is not None else "simulation"
    settings.patient_source = row.patient_source if row.patient_source is not None else "simulation"
    settings.active_scenario_id = row.active_scenario_id
    settings.call_mode = row.call_mode if row.call_mode is not None else "web"
    settings.mock_mode = row.mock_mode if row.mock_mode is not None else False
    settings.mock_phone = row.mock_phone if row.mock_phone is not None else ""
    dr = row.daily_report or {}
    settings.daily_report = DailyReportConfig(
        enabled=bool(dr.get("enabled", False)),
        webhook_url=str(dr.get("webhook_url", "")),
        hour=int(dr.get("hour", 7)),
        timezone=str(dr.get("timezone", "America/Los_Angeles")),
    )

    cc = getattr(row, "calcom_config", None) or {}
    event_type_id = cc.get("event_type_id")
    settings.calcom_config = CalComConfig(
        event_type_id=int(event_type_id) if event_type_id is not None else None,
        default_timezone=str(cc.get("default_timezone", "America/New_York")),
    )
    sc = getattr(row, "sales_context", None) or {}
    settings.sales_context = SalesContext(
        rep_name=str(sc.get("rep_name", "")),
        rep_company=str(sc.get("rep_company", "")),
        rep_email=str(sc.get("rep_email", "")),
        product_context=str(sc.get("product_context", "")),
    )
    psh = getattr(row, "per_state_hours", None) or {}
    settings.per_state_hours = PerStateHours(
        start=str(psh.get("start", "09:00")),
        end=str(psh.get("end", "17:00")),
        days=list(psh.get("days", [0, 1, 2, 3, 4])),
    )
    settings.voice_provider = str(getattr(row, "voice_provider", None) or "openai")
    settings.voice_model = str(getattr(row, "voice_model", None) or "")
    vc = getattr(row, "voice_config", None)
    settings.voice_config = dict(vc) if isinstance(vc, dict) else {}
    settings.default_carrier = str(getattr(row, "default_carrier", None) or "twilio")
    settings.ivr_navigate_enabled = bool(getattr(row, "ivr_navigate_enabled", False))
    return settings


class SettingsProvider:
    """Manages system settings with PostgreSQL storage."""

    async def get_settings(self) -> SystemSettings:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SystemSettingsRow).where(SystemSettingsRow.id == 1))
            row = result.scalar_one_or_none()
            if row is None:
                return SystemSettings()
            return _row_to_settings(row)

    async def update_settings(self, settings: SystemSettings) -> SystemSettings:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SystemSettingsRow).where(SystemSettingsRow.id == 1))
            row = result.scalar_one_or_none()
            if row is None:
                row = SystemSettingsRow(id=1)
                session.add(row)
            row.system_enabled = settings.system_enabled
            row.business_hours = {
                "start_time": settings.business_hours.start_time,
                "end_time": settings.business_hours.end_time,
                "enabled": settings.business_hours.enabled,
                "timezone": settings.business_hours.timezone,
                "days_of_week": settings.business_hours.days_of_week,
                "holidays": [
                    {
                        "date": h.date,
                        "name": h.name,
                        "recurring": h.recurring,
                    }
                    for h in settings.business_hours.holidays
                ],
            }
            row.queue_thresholds = {
                "calls_waiting_threshold": settings.queue_thresholds.calls_waiting_threshold,
                "holdtime_threshold_seconds": settings.queue_thresholds.holdtime_threshold_seconds,
                "stable_polls_required": settings.queue_thresholds.stable_polls_required,
            }
            row.dispatcher_settings = {
                "poll_interval": settings.dispatcher_settings.poll_interval,
                "dispatch_timeout": settings.dispatcher_settings.dispatch_timeout,
                "max_attempts": settings.dispatcher_settings.max_attempts,
                "min_hours_between": settings.dispatcher_settings.min_hours_between,
                "cooldown_seconds": settings.dispatcher_settings.cooldown_seconds,
                "verbose_logging": settings.dispatcher_settings.verbose_logging,
            }
            row.allow_live_calls = settings.allow_live_calls
            row.allowed_phones = settings.allowed_phones
            row.queue_source = settings.queue_source
            row.patient_source = settings.patient_source
            # NOTE: mock_mode, mock_phone, and daily_report are NOT updated
            # here — they have their own dedicated endpoints.  Overwriting
            # them from the generic settings payload would silently reset
            # them to defaults whenever any other setting is saved.
            await session.commit()
            return _row_to_settings(row)

    async def set_system_enabled(self, enabled: bool) -> SystemSettings:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SystemSettingsRow).where(SystemSettingsRow.id == 1))
            row = result.scalar_one_or_none()
            if row is None:
                row = SystemSettingsRow(id=1)
                session.add(row)
            row.system_enabled = enabled
            await session.commit()
            return _row_to_settings(row)

    async def update_business_hours(self, business_hours: BusinessHours) -> SystemSettings:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SystemSettingsRow).where(SystemSettingsRow.id == 1))
            row = result.scalar_one_or_none()
            if row is None:
                row = SystemSettingsRow(
                    id=1,
                    business_hours={},
                    queue_thresholds={
                        "calls_waiting_threshold": 1,
                        "holdtime_threshold_seconds": 30,
                        "stable_polls_required": 3,
                    },
                )
                session.add(row)
            row.business_hours = {
                "start_time": business_hours.start_time,
                "end_time": business_hours.end_time,
                "enabled": business_hours.enabled,
                "timezone": business_hours.timezone,
                "days_of_week": business_hours.days_of_week,
                "holidays": [
                    {
                        "date": h.date,
                        "name": h.name,
                        "recurring": h.recurring,
                    }
                    for h in business_hours.holidays
                ],
            }
            await session.commit()
            return _row_to_settings(row)

    async def update_queue_thresholds(self, thresholds: QueueThresholds) -> SystemSettings:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SystemSettingsRow).where(SystemSettingsRow.id == 1))
            row = result.scalar_one_or_none()
            if row is None:
                row = SystemSettingsRow(
                    id=1,
                    business_hours={
                        "start_time": "08:00",
                        "end_time": "17:00",
                        "enabled": False,
                        "timezone": "America/New_York",
                        "days_of_week": [0, 1, 2, 3, 4],
                        "holidays": [],
                    },
                    queue_thresholds={},
                )
                session.add(row)
            row.queue_thresholds = {
                "calls_waiting_threshold": thresholds.calls_waiting_threshold,
                "holdtime_threshold_seconds": thresholds.holdtime_threshold_seconds,
                "stable_polls_required": thresholds.stable_polls_required,
            }
            await session.commit()
            return _row_to_settings(row)

    async def update_dispatcher_settings(self, dispatcher_settings: DispatcherSettings) -> SystemSettings:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SystemSettingsRow).where(SystemSettingsRow.id == 1))
            row = result.scalar_one_or_none()
            if row is None:
                row = SystemSettingsRow(
                    id=1,
                    business_hours={
                        "start_time": "08:00",
                        "end_time": "17:00",
                        "enabled": False,
                        "timezone": "America/New_York",
                        "days_of_week": [0, 1, 2, 3, 4],
                        "holidays": [],
                    },
                    queue_thresholds={
                        "calls_waiting_threshold": 1,
                        "holdtime_threshold_seconds": 30,
                        "stable_polls_required": 3,
                    },
                    dispatcher_settings={},
                )
                session.add(row)
            row.dispatcher_settings = {
                "poll_interval": dispatcher_settings.poll_interval,
                "dispatch_timeout": dispatcher_settings.dispatch_timeout,
                "max_attempts": dispatcher_settings.max_attempts,
                "min_hours_between": dispatcher_settings.min_hours_between,
                "cooldown_seconds": dispatcher_settings.cooldown_seconds,
                "default_batch_size": dispatcher_settings.default_batch_size,
                "verbose_logging": dispatcher_settings.verbose_logging,
            }
            await session.commit()
            return _row_to_settings(row)

    async def set_allow_live_calls(self, allowed: bool) -> SystemSettings:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SystemSettingsRow).where(SystemSettingsRow.id == 1))
            row = result.scalar_one_or_none()
            if row is None:
                row = SystemSettingsRow(id=1, business_hours={}, queue_thresholds={})
                session.add(row)
            row.allow_live_calls = allowed
            await session.commit()
            return _row_to_settings(row)

    async def update_allowed_phones(self, phones: List[str]) -> SystemSettings:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SystemSettingsRow).where(SystemSettingsRow.id == 1))
            row = result.scalar_one_or_none()
            if row is None:
                row = SystemSettingsRow(id=1, business_hours={}, queue_thresholds={})
                session.add(row)
            row.allowed_phones = phones
            await session.commit()
            return _row_to_settings(row)

    async def is_phone_allowed(self, phone: str) -> bool:
        """Check if a phone number is in the allowlist. Empty list = block all."""
        settings = await self.get_settings()
        if not settings.allowed_phones:
            return False
        return phone in settings.allowed_phones

    async def is_within_business_hours(self) -> bool:
        reason = await self.get_business_hours_block_reason()
        return reason is None

    async def get_business_hours_block_reason(self) -> Optional[str]:
        settings = await self.get_settings()
        bh = settings.business_hours
        if not bh.enabled:
            return None
        try:
            tz = ZoneInfo(bh.timezone)
            now = datetime.now(tz)
            current_time = now.strftime("%H:%M")
            current_day = now.weekday()  # 0=Monday, 6=Sunday
            today = now.date()

            # Check holiday calendar first (blocks even during valid weekday/time).
            holiday = _matching_holiday(today, bh.holidays)
            if holiday:
                return f"Holiday configured: {holiday.name} ({holiday.date})"

            # Check if current day is in allowed days
            if current_day not in bh.days_of_week:
                return "Outside configured business days"

            # Check if current time is within hours
            if not (bh.start_time <= current_time <= bh.end_time):
                return f"Outside business hours ({bh.start_time}-{bh.end_time} {bh.timezone})"
            return None
        except Exception:
            return None

    async def can_make_outbound_call(self) -> bool:
        settings = await self.get_settings()
        if not settings.system_enabled:
            return False
        if not await self.is_within_business_hours():
            return False
        return True

    async def set_patient_source(self, source: str) -> SystemSettings:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SystemSettingsRow).where(SystemSettingsRow.id == 1))
            row = result.scalar_one_or_none()
            if row is None:
                row = SystemSettingsRow(id=1, business_hours={}, queue_thresholds={})
                session.add(row)
            row.patient_source = source
            await session.commit()
            return _row_to_settings(row)

    async def set_queue_source(self, source: str) -> SystemSettings:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SystemSettingsRow).where(SystemSettingsRow.id == 1))
            row = result.scalar_one_or_none()
            if row is None:
                row = SystemSettingsRow(id=1, business_hours={}, queue_thresholds={})
                session.add(row)
            row.queue_source = source
            await session.commit()
            return _row_to_settings(row)

    async def set_active_scenario_id(self, scenario_id: str) -> SystemSettings:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SystemSettingsRow).where(SystemSettingsRow.id == 1))
            row = result.scalar_one_or_none()
            if row is None:
                row = SystemSettingsRow(id=1, business_hours={}, queue_thresholds={})
                session.add(row)
            row.active_scenario_id = scenario_id
            await session.commit()
            return _row_to_settings(row)

    async def set_call_mode(self, call_mode: str) -> SystemSettings:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SystemSettingsRow).where(SystemSettingsRow.id == 1))
            row = result.scalar_one_or_none()
            if row is None:
                row = SystemSettingsRow(id=1, business_hours={}, queue_thresholds={})
                session.add(row)
            row.call_mode = call_mode
            await session.commit()
            return _row_to_settings(row)

    async def set_mock_mode(self, enabled: bool, mock_phone: str = "") -> SystemSettings:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SystemSettingsRow).where(SystemSettingsRow.id == 1))
            row = result.scalar_one_or_none()
            if row is None:
                row = SystemSettingsRow(id=1, business_hours={}, queue_thresholds={})
                session.add(row)
            row.mock_mode = enabled
            row.mock_phone = mock_phone
            await session.commit()
            return _row_to_settings(row)

    async def set_ivr_navigate_enabled(self, enabled: bool) -> SystemSettings:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SystemSettingsRow).where(SystemSettingsRow.id == 1))
            row = result.scalar_one_or_none()
            if row is None:
                row = SystemSettingsRow(id=1, business_hours={}, queue_thresholds={})
                session.add(row)
            row.ivr_navigate_enabled = bool(enabled)
            await session.commit()
            return _row_to_settings(row)

    async def set_default_carrier(self, carrier: str) -> SystemSettings:
        """Set the default telephony carrier ('twilio' | 'telnyx')."""
        c = (carrier or "").strip().lower()
        if c not in ("twilio", "telnyx"):
            raise ValueError(f"unsupported carrier: {carrier!r}")
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SystemSettingsRow).where(SystemSettingsRow.id == 1))
            row = result.scalar_one_or_none()
            if row is None:
                row = SystemSettingsRow(id=1, business_hours={}, queue_thresholds={})
                session.add(row)
            row.default_carrier = c
            await session.commit()
            return _row_to_settings(row)

    async def save_settings(self, settings: SystemSettings) -> SystemSettings:
        """Save a subset of the dataclass back to the DB — currently only
        fields the carrier UI toggles. Extend here if you add more writable
        top-level fields.
        """
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SystemSettingsRow).where(SystemSettingsRow.id == 1))
            row = result.scalar_one_or_none()
            if row is None:
                row = SystemSettingsRow(id=1, business_hours={}, queue_thresholds={})
                session.add(row)
            row.default_carrier = (settings.default_carrier or "twilio").strip().lower()
            await session.commit()
            return _row_to_settings(row)

    async def set_voice_provider(
        self, provider: str, model: str = ""
    ) -> SystemSettings:
        """Set the default realtime voice backend.

        `provider` must be one of 'openai' | 'gemini'. Empty `model` means
        the backend should fall back to its env-var default at call time.
        """
        if provider not in ("openai", "gemini"):
            raise ValueError(f"unsupported voice_provider: {provider!r}")
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SystemSettingsRow).where(SystemSettingsRow.id == 1))
            row = result.scalar_one_or_none()
            if row is None:
                row = SystemSettingsRow(id=1, business_hours={}, queue_thresholds={})
                session.add(row)
            row.voice_provider = provider
            row.voice_model = model or ""
            await session.commit()
            return _row_to_settings(row)

    # Allowlist of per-provider voice names to keep typos from silently
    # blowing up a call. If the backend ever adds a new voice, extend here.
    _OPENAI_VOICES = {
        "alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse",
    }
    _GEMINI_VOICES = {
        "Aoede", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Zephyr",
    }

    async def update_voice_config(self, provider: str, patch: dict) -> SystemSettings:
        """Merge `patch` into the per-provider voice_config dict.

        `provider` is "openai" or "gemini". `patch` is a dict of keys to
        set — missing keys are left untouched. Supported keys:

        - `voice` (str) — prebuilt voice name. Validated against the
          provider's allowlist.
        - `temperature` (float, 0.0-2.0) — sampling temperature.
        - `affective_dialog` (bool) — Gemini only. Model adjusts prosody
          to match the caller's emotional tone.
        - `proactive_audio` (bool) — Gemini only. Model emits non-verbal
          cues (short affirmations, etc.) at natural moments.

        Keys that aren't supported by the selected provider are rejected
        with ValueError so the caller knows a typo ended up in the DB.
        """
        if provider not in ("openai", "gemini"):
            raise ValueError(f"unsupported voice provider: {provider!r}")

        clean: dict = {}
        if "voice" in patch:
            v = str(patch["voice"] or "").strip()
            if provider == "openai" and v and v not in self._OPENAI_VOICES:
                raise ValueError(
                    f"unknown OpenAI voice {v!r}; expected one of "
                    f"{sorted(self._OPENAI_VOICES)}"
                )
            if provider == "gemini" and v and v not in self._GEMINI_VOICES:
                raise ValueError(
                    f"unknown Gemini voice {v!r}; expected one of "
                    f"{sorted(self._GEMINI_VOICES)}"
                )
            clean["voice"] = v
        if "temperature" in patch:
            try:
                t = float(patch["temperature"])
            except (TypeError, ValueError):
                raise ValueError("temperature must be a number")
            if not 0.0 <= t <= 2.0:
                raise ValueError("temperature must be between 0.0 and 2.0")
            clean["temperature"] = t
        if "affective_dialog" in patch:
            if provider != "gemini":
                raise ValueError("affective_dialog is Gemini-only")
            clean["affective_dialog"] = bool(patch["affective_dialog"])
        if "proactive_audio" in patch:
            if provider != "gemini":
                raise ValueError("proactive_audio is Gemini-only")
            clean["proactive_audio"] = bool(patch["proactive_audio"])
        if "speed" in patch:
            if provider != "openai":
                raise ValueError("speed is OpenAI-only")
            try:
                s = float(patch["speed"])
            except (TypeError, ValueError):
                raise ValueError("speed must be a number")
            if not 0.25 <= s <= 4.0:
                raise ValueError("speed must be between 0.25 and 4.0")
            clean["speed"] = s
        if "top_p" in patch:
            if provider != "gemini":
                raise ValueError("top_p is Gemini-only")
            try:
                p = float(patch["top_p"])
            except (TypeError, ValueError):
                raise ValueError("top_p must be a number")
            if not 0.0 <= p <= 1.0:
                raise ValueError("top_p must be between 0.0 and 1.0")
            clean["top_p"] = p

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SystemSettingsRow).where(SystemSettingsRow.id == 1))
            row = result.scalar_one_or_none()
            if row is None:
                row = SystemSettingsRow(id=1, business_hours={}, queue_thresholds={})
                session.add(row)
            current = dict(row.voice_config or {})
            per_provider = dict(current.get(provider) or {})
            per_provider.update(clean)
            current[provider] = per_provider
            # JSONB dirty-tracking — new dict object.
            row.voice_config = current
            await session.commit()
            return _row_to_settings(row)

    async def update_daily_report(self, config: DailyReportConfig) -> SystemSettings:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SystemSettingsRow).where(SystemSettingsRow.id == 1))
            row = result.scalar_one_or_none()
            if row is None:
                row = SystemSettingsRow(id=1, business_hours={}, queue_thresholds={})
                session.add(row)
            row.daily_report = {
                "enabled": config.enabled,
                "webhook_url": config.webhook_url,
                "hour": max(0, min(23, int(config.hour))),
                "timezone": config.timezone or "America/Los_Angeles",
            }
            await session.commit()
            return _row_to_settings(row)

    async def get_thresholds(self) -> QueueThresholds:
        settings = await self.get_settings()
        return settings.queue_thresholds


# Global instance
_settings_provider: Optional[SettingsProvider] = None


def get_settings_provider() -> SettingsProvider:
    """Get the global settings provider instance."""
    global _settings_provider
    if _settings_provider is None:
        _settings_provider = SettingsProvider()
    return _settings_provider
