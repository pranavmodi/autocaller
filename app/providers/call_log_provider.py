"""Call log provider — DB-backed."""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, delete, func, case, extract, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AsyncSessionLocal
from app.db.models import CallLogRow
from app.models import (
    CallLog, CallOutcome, CallStatus, CallDisposition, TranscriptEntry,
    derive_status_and_disposition,
)


def _safe_enum(enum_cls, value, default):
    try:
        return enum_cls(value)
    except (ValueError, TypeError):
        return default


def _row_to_call_log(row: CallLogRow) -> CallLog:
    outcome = _safe_enum(CallOutcome, row.outcome, CallOutcome.IN_PROGRESS)
    call_status = _safe_enum(CallStatus, row.call_status, CallStatus.IN_PROGRESS)
    call_disposition = _safe_enum(CallDisposition, row.call_disposition, CallDisposition.IN_PROGRESS)

    cl = CallLog.__new__(CallLog)
    cl.call_id = row.call_id
    cl.patient_id = row.patient_id
    cl.patient_name = row.patient_name
    cl.phone = row.phone
    cl.order_id = row.order_id
    cl.priority_bucket = row.priority_bucket
    cl.started_at = row.started_at
    cl.ended_at = row.ended_at
    cl.duration_seconds = row.duration_seconds
    cl.outcome = outcome
    cl.call_status = call_status
    cl.call_disposition = call_disposition
    cl.mock_mode = bool(row.mock_mode)
    cl.transfer_attempted = row.transfer_attempted
    cl.transfer_success = row.transfer_success
    cl.voicemail_left = row.voicemail_left
    cl.takeover_used = bool(getattr(row, "takeover_used", False))
    cl.sms_sent = row.sms_sent
    cl.preferred_callback_time = row.preferred_callback_time
    cl.queue_snapshot = row.queue_snapshot
    cl.error_code = row.error_code
    cl.error_message = row.error_message
    cl.recording_sid = row.recording_sid
    cl.recording_path = row.recording_path
    cl.recording_size_bytes = row.recording_size_bytes
    cl.recording_duration_seconds = row.recording_duration_seconds
    cl.recording_format = row.recording_format

    # Attorney-era fields
    cl.pain_point_summary = getattr(row, "pain_point_summary", None)
    cl.interest_level = getattr(row, "interest_level", None)
    cl.is_decision_maker = getattr(row, "is_decision_maker", None)
    cl.was_gatekeeper = bool(getattr(row, "was_gatekeeper", False))
    cl.gatekeeper_contact = getattr(row, "gatekeeper_contact", None)
    cl.demo_booking_id = getattr(row, "demo_booking_id", None)
    cl.demo_scheduled_at = getattr(row, "demo_scheduled_at", None)
    cl.demo_meeting_url = getattr(row, "demo_meeting_url", None)
    cl.followup_email_sent = bool(getattr(row, "followup_email_sent", False))
    cl.firm_name = getattr(row, "firm_name", None)
    cl.lead_state = getattr(row, "lead_state", None)

    # Phase A: judge + GTM
    cl.judge_score = getattr(row, "judge_score", None)
    cl.judge_scores = getattr(row, "judge_scores", None)
    cl.judge_notes = getattr(row, "judge_notes", None)
    cl.judged_at = getattr(row, "judged_at", None)
    cl.prompt_version = getattr(row, "prompt_version", None)
    cl.prompt_text = getattr(row, "prompt_text", None)
    cl.tools_snapshot = getattr(row, "tools_snapshot", None)
    cl.gtm_disposition = getattr(row, "gtm_disposition", None)
    cl.follow_up_action = getattr(row, "follow_up_action", None)
    cl.follow_up_when = getattr(row, "follow_up_when", None)
    cl.follow_up_owner = getattr(row, "follow_up_owner", None)
    cl.follow_up_note = getattr(row, "follow_up_note", None)
    cl.call_summary = getattr(row, "call_summary", None)
    cl.signal_flags = getattr(row, "signal_flags", None)
    cl.pain_points_discussed = getattr(row, "pain_points_discussed", None)
    cl.objections_raised = getattr(row, "objections_raised", None)
    cl.captured_contacts = getattr(row, "captured_contacts", None)
    cl.dm_reachability = getattr(row, "dm_reachability", None)
    cl.dnc_reason = getattr(row, "dnc_reason", None)
    cl.voice_provider = getattr(row, "voice_provider", None)
    cl.voice_model = getattr(row, "voice_model", None)
    cl.carrier = getattr(row, "carrier", None)
    cl.call_mode = getattr(row, "call_mode", "twilio") or "twilio"
    cl.whisper_transcript = getattr(row, "whisper_transcript", None)
    cl.ivr_detected = bool(getattr(row, "ivr_detected", False))
    cl.ivr_outcome = getattr(row, "ivr_outcome", None)
    cl.ivr_menu_log = getattr(row, "ivr_menu_log", None)

    # Convert JSONB transcript list to TranscriptEntry objects
    raw = row.transcript or []
    cl.transcript = []
    for entry in raw:
        te = TranscriptEntry.__new__(TranscriptEntry)
        te.speaker = entry.get("speaker", "")
        te.text = entry.get("text", "")
        ts = entry.get("timestamp")
        if ts:
            try:
                te.timestamp = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                te.timestamp = datetime.now(timezone.utc)
        else:
            te.timestamp = datetime.now(timezone.utc)
        cl.transcript.append(te)

    return cl


class CallLogProvider:
    """Stores and retrieves call logs in PostgreSQL."""

    def __init__(self):
        self._active_call_id: Optional[str] = None

    async def create_call(
        self,
        patient_id: str,
        patient_name: str,
        phone: str,
        order_id: Optional[str] = None,
        priority_bucket: int = 0,
        queue_snapshot: Optional[dict] = None,
        mock_mode: bool = False,
        firm_name: Optional[str] = None,
        lead_state: Optional[str] = None,
        prompt_text: Optional[str] = None,
        prompt_version: Optional[str] = None,
        tools_snapshot: Optional[list] = None,
        voice_provider: Optional[str] = None,
        voice_model: Optional[str] = None,
        carrier: Optional[str] = None,
        call_mode: str = "twilio",
    ) -> CallLog:
        call_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as session:
            row = CallLogRow(
                call_id=call_id,
                patient_id=patient_id,
                patient_name=patient_name,
                phone=phone,
                order_id=order_id,
                priority_bucket=priority_bucket,
                started_at=now,
                outcome="in_progress",
                queue_snapshot=queue_snapshot,
                mock_mode=mock_mode,
                transcript=[],
                firm_name=firm_name,
                lead_state=lead_state,
                prompt_text=prompt_text,
                prompt_version=prompt_version,
                tools_snapshot=tools_snapshot,
                voice_provider=voice_provider,
                voice_model=voice_model,
                carrier=carrier,
                call_mode=call_mode,
            )
            session.add(row)
            await session.commit()

        self._active_call_id = call_id
        # Return as dataclass
        cl = CallLog.__new__(CallLog)
        cl.call_id = call_id
        cl.patient_id = patient_id
        cl.patient_name = patient_name
        cl.phone = phone
        cl.order_id = order_id
        cl.priority_bucket = priority_bucket
        cl.started_at = now
        cl.ended_at = None
        cl.duration_seconds = 0
        cl.outcome = CallOutcome.IN_PROGRESS
        cl.call_status = CallStatus.IN_PROGRESS
        cl.call_disposition = CallDisposition.IN_PROGRESS
        cl.mock_mode = mock_mode
        cl.transfer_attempted = False
        cl.transfer_success = False
        cl.voicemail_left = False
        cl.sms_sent = False
        cl.preferred_callback_time = None
        cl.queue_snapshot = queue_snapshot
        cl.transcript = []
        cl.error_code = None
        cl.error_message = None
        cl.recording_sid = None
        cl.recording_path = None
        cl.recording_size_bytes = None
        cl.recording_duration_seconds = None
        cl.recording_format = None
        cl.voice_provider = voice_provider
        cl.voice_model = voice_model
        cl.carrier = carrier
        cl.call_mode = call_mode
        return cl

    async def get_call(self, call_id: str) -> Optional[CallLog]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(CallLogRow).where(CallLogRow.call_id == call_id)
            )
            row = result.scalar_one_or_none()
            return _row_to_call_log(row) if row else None

    async def get_active_call(self) -> Optional[CallLog]:
        if self._active_call_id is None:
            return None
        return await self.get_call(self._active_call_id)

    async def get_all_calls(self, limit: int = 50, offset: int = 0) -> list[CallLog]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(CallLogRow)
                .order_by(CallLogRow.started_at.desc())
                .offset(offset)
                .limit(limit)
            )
            return [_row_to_call_log(r) for r in result.scalars().all()]

    async def get_total_call_count(self) -> int:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(func.count(CallLogRow.call_id)))
            return result.scalar() or 0

    async def get_calls_by_patient(self, patient_id: str) -> list[CallLog]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(CallLogRow)
                .where(CallLogRow.patient_id == patient_id)
                .order_by(CallLogRow.started_at.desc())
            )
            return [_row_to_call_log(r) for r in result.scalars().all()]

    async def add_transcript(self, call_id: str, speaker: str, text: str):
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(CallLogRow).where(CallLogRow.call_id == call_id)
            )
            row = result.scalar_one_or_none()
            if row:
                current = list(row.transcript or [])
                current.append({
                    "speaker": speaker,
                    "text": text,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                row.transcript = current
                await session.commit()

    async def end_call(self, call_id: str, outcome: CallOutcome):
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(CallLogRow).where(CallLogRow.call_id == call_id)
            )
            row = result.scalar_one_or_none()
            if row:
                row.ended_at = now
                row.outcome = outcome.value
                if row.started_at:
                    row.duration_seconds = int((now - row.started_at).total_seconds())

                # Derive call_status + call_disposition from the full context
                transcript = row.transcript or []
                had_patient_speech = any(
                    entry.get("speaker") == "patient" and (entry.get("text") or "").strip()
                    for entry in transcript
                )
                status, disposition = derive_status_and_disposition(
                    outcome=outcome,
                    error_code=row.error_code,
                    had_patient_speech=had_patient_speech,
                    duration_seconds=row.duration_seconds,
                    ivr_detected=bool(getattr(row, "ivr_detected", False)),
                    ivr_outcome=getattr(row, "ivr_outcome", None),
                )
                row.call_status = status.value
                row.call_disposition = disposition.value
                await session.commit()
        if self._active_call_id == call_id:
            self._active_call_id = None

    # Whitelist of columns update_call is allowed to set. Anything else is
    # ignored silently (safer than having callers accidentally set primary
    # keys, timestamps, or derived columns).
    _UPDATE_ALLOWED = {
        "transfer_attempted", "transfer_success", "voicemail_left",
        "takeover_used", "sms_sent",
        "preferred_callback_time", "error_code", "error_message",
        # Autocaller post-call capture
        "pain_point_summary", "interest_level", "is_decision_maker",
        "was_gatekeeper", "gatekeeper_contact",
        "demo_booking_id", "demo_scheduled_at", "demo_meeting_url",
        "followup_email_sent", "firm_name", "lead_state",
        "voice_provider", "voice_model", "carrier",
        "ivr_detected", "ivr_outcome", "ivr_menu_log",
        # Written by voicemail_followup_service + in-call send_followup_email
        "captured_contacts",
    }

    async def update_call(self, call_id: str, **fields):
        """Partial-update the call log row. Only whitelisted columns are touched."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(CallLogRow).where(CallLogRow.call_id == call_id)
            )
            row = result.scalar_one_or_none()
            if not row:
                return
            for key, value in fields.items():
                if value is None:
                    continue
                if key not in self._UPDATE_ALLOWED:
                    continue
                setattr(row, key, value)
            await session.commit()

    async def set_recording(
        self,
        call_id: str,
        recording_sid: str,
        recording_path: str,
        recording_size_bytes: int,
        recording_duration_seconds: int,
        recording_format: str = "mp3",
    ):
        """Attach a downloaded recording to a call log row."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(CallLogRow).where(CallLogRow.call_id == call_id)
            )
            row = result.scalar_one_or_none()
            if row:
                row.recording_sid = recording_sid
                row.recording_path = recording_path
                row.recording_size_bytes = recording_size_bytes
                row.recording_duration_seconds = recording_duration_seconds
                row.recording_format = recording_format
                await session.commit()

    def clear_active_call(self):
        self._active_call_id = None

    async def reset(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(CallLogRow))
            await session.commit()
        self._active_call_id = None

    def has_active_call(self) -> bool:
        return self._active_call_id is not None

    async def get_stats_for_date(self, target_date, tz_name: str = "America/Los_Angeles") -> dict:
        """Get a full disposition breakdown for a specific local date.

        Used by the daily Slack report.  `target_date` is a datetime.date
        interpreted in the given timezone; all calls started_at between
        local midnight and the next local midnight are counted.
        """
        from datetime import datetime as _dt, time as _time, timedelta as _td
        from zoneinfo import ZoneInfo

        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("America/Los_Angeles")
        local_start = _dt.combine(target_date, _time.min).replace(tzinfo=tz)
        local_end = local_start + _td(days=1)
        start_utc = local_start.astimezone(timezone.utc)
        end_utc = local_end.astimezone(timezone.utc)

        async with AsyncSessionLocal() as session:
            # Total
            total_result = await session.execute(
                select(func.count(CallLogRow.call_id))
                .where(CallLogRow.started_at >= start_utc)
                .where(CallLogRow.started_at < end_utc)
            )
            total = total_result.scalar() or 0

            # Disposition breakdown
            disp_result = await session.execute(
                select(CallLogRow.call_disposition, func.count(CallLogRow.call_id))
                .where(CallLogRow.started_at >= start_utc)
                .where(CallLogRow.started_at < end_utc)
                .group_by(CallLogRow.call_disposition)
            )
            dispositions = {row[0]: row[1] for row in disp_result.all()}

            # SMS count
            sms_result = await session.execute(
                select(func.count(CallLogRow.call_id))
                .where(CallLogRow.started_at >= start_utc)
                .where(CallLogRow.started_at < end_utc)
                .where(CallLogRow.sms_sent == True)  # noqa: E712
            )
            sms = sms_result.scalar() or 0

        return {
            "date": target_date.isoformat(),
            "timezone": tz_name,
            "total_calls": total,
            "dispositions": dispositions,
            "sms": sms,
        }

    async def get_today_kpis(self) -> dict:
        """Return today's headline numbers for the dashboard KPI row.

        'Today' is computed in the server's local timezone so the numbers
        line up with the operator's actual workday.
        """
        from datetime import datetime as _dt, time as _time
        # Midnight today in local time, then converted to an aware UTC datetime
        # to match how started_at is stored.
        local_midnight = _dt.combine(_dt.now().date(), _time.min).astimezone()
        start_utc = local_midnight.astimezone(timezone.utc)

        async with AsyncSessionLocal() as session:
            # Total calls placed today (any outcome)
            total_result = await session.execute(
                select(func.count(CallLogRow.call_id))
                .where(CallLogRow.started_at >= start_utc)
            )
            total_calls = total_result.scalar() or 0

            # Transferred today
            transferred_result = await session.execute(
                select(func.count(CallLogRow.call_id))
                .where(CallLogRow.started_at >= start_utc)
                .where(CallLogRow.transfer_success == True)  # noqa: E712
            )
            transferred = transferred_result.scalar() or 0

            # Voicemails left today
            vm_result = await session.execute(
                select(func.count(CallLogRow.call_id))
                .where(CallLogRow.started_at >= start_utc)
                .where(CallLogRow.voicemail_left == True)  # noqa: E712
            )
            voicemails = vm_result.scalar() or 0

            # SMS sent today
            sms_result = await session.execute(
                select(func.count(CallLogRow.call_id))
                .where(CallLogRow.started_at >= start_utc)
                .where(CallLogRow.sms_sent == True)  # noqa: E712
            )
            sms = sms_result.scalar() or 0

        return {
            "total_calls": total_calls,
            "transferred": transferred,
            "voicemails": voicemails,
            "sms": sms,
        }

    async def get_time_performance(self, days: int = 90, tz_name: str = "America/Los_Angeles") -> dict:
        """Aggregate call outcomes by day-of-week and hour-of-day over the last N days.

        Returns two breakdowns:
        - by_day: list of {day, day_name, total, transferred, no_answer, voicemail, transfer_rate, ...}
        - by_hour: list of {hour, label, total, transferred, no_answer, voicemail, transfer_rate, ...}
        """
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # Use PostgreSQL AT TIME ZONE to convert started_at to local time
        local_ts = func.timezone(tz_name, CallLogRow.started_at)
        dow = extract("dow", local_ts)  # 0=Sunday in PG
        hour = extract("hour", local_ts)

        transferred_count = func.count(case(
            (CallLogRow.call_disposition == "transferred", 1),
        ))
        no_answer_count = func.count(case(
            (CallLogRow.call_disposition == "no_answer", 1),
        ))
        voicemail_count = func.count(case(
            (CallLogRow.call_disposition == "voicemail_left", 1),
        ))
        callback_count = func.count(case(
            (CallLogRow.call_disposition == "callback_requested", 1),
        ))
        hung_up_count = func.count(case(
            (CallLogRow.call_disposition == "hung_up", 1),
        ))
        total_count = func.count(CallLogRow.call_id)

        async with AsyncSessionLocal() as session:
            # By day of week
            day_result = await session.execute(
                select(
                    dow.label("dow"),
                    total_count.label("total"),
                    transferred_count.label("transferred"),
                    no_answer_count.label("no_answer"),
                    voicemail_count.label("voicemail"),
                    callback_count.label("callback"),
                    hung_up_count.label("hung_up"),
                )
                .where(CallLogRow.started_at >= cutoff)
                .group_by(dow)
                .order_by(dow)
            )
            day_rows = day_result.all()

            # By hour of day
            hour_result = await session.execute(
                select(
                    hour.label("hour"),
                    total_count.label("total"),
                    transferred_count.label("transferred"),
                    no_answer_count.label("no_answer"),
                    voicemail_count.label("voicemail"),
                    callback_count.label("callback"),
                    hung_up_count.label("hung_up"),
                )
                .where(CallLogRow.started_at >= cutoff)
                .group_by(hour)
                .order_by(hour)
            )
            hour_rows = hour_result.all()

        # PG dow: 0=Sunday, 1=Monday, ...
        day_names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

        def _rate(n, total):
            return round(n / total * 100, 1) if total > 0 else 0.0

        by_day = []
        for r in day_rows:
            t = r.total
            by_day.append({
                "day": int(r.dow),
                "day_name": day_names[int(r.dow)],
                "total": t,
                "transferred": r.transferred,
                "no_answer": r.no_answer,
                "voicemail": r.voicemail,
                "callback": r.callback,
                "hung_up": r.hung_up,
                "transfer_rate": _rate(r.transferred, t),
                "no_answer_rate": _rate(r.no_answer, t),
                "voicemail_rate": _rate(r.voicemail, t),
            })

        by_hour = []
        for r in hour_rows:
            t = r.total
            h = int(r.hour)
            label = f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}"
            by_hour.append({
                "hour": h,
                "label": label,
                "total": t,
                "transferred": r.transferred,
                "no_answer": r.no_answer,
                "voicemail": r.voicemail,
                "callback": r.callback,
                "hung_up": r.hung_up,
                "transfer_rate": _rate(r.transferred, t),
                "no_answer_rate": _rate(r.no_answer, t),
                "voicemail_rate": _rate(r.voicemail, t),
            })

        # Grand totals
        grand_total = sum(d["total"] for d in by_day)
        grand_transferred = sum(d["transferred"] for d in by_day)
        grand_no_answer = sum(d["no_answer"] for d in by_day)
        grand_voicemail = sum(d["voicemail"] for d in by_day)

        return {
            "days": days,
            "timezone": tz_name,
            "total_calls": grand_total,
            "overall_transfer_rate": _rate(grand_transferred, grand_total),
            "overall_no_answer_rate": _rate(grand_no_answer, grand_total),
            "overall_voicemail_rate": _rate(grand_voicemail, grand_total),
            "by_day": by_day,
            "by_hour": by_hour,
        }

    async def get_statistics(self) -> dict:
        async with AsyncSessionLocal() as session:
            # Total count
            total_result = await session.execute(select(func.count(CallLogRow.call_id)))
            total = total_result.scalar() or 0

            if total == 0:
                return {
                    "total_calls": 0,
                    "outcomes": {},
                    "avg_duration_seconds": 0,
                    "transfer_rate": 0,
                }

            # Outcomes breakdown
            outcome_result = await session.execute(
                select(CallLogRow.outcome, func.count(CallLogRow.call_id))
                .group_by(CallLogRow.outcome)
            )
            outcomes = {row[0]: row[1] for row in outcome_result.all()}

            # Average duration
            avg_result = await session.execute(
                select(func.avg(CallLogRow.duration_seconds))
            )
            avg_duration = avg_result.scalar() or 0

            # Transfer rate
            transfer_result = await session.execute(
                select(func.count(CallLogRow.call_id))
                .where(CallLogRow.transfer_success == True)  # noqa: E712
            )
            transfers = transfer_result.scalar() or 0

            return {
                "total_calls": total,
                "outcomes": outcomes,
                "avg_duration_seconds": float(avg_duration),
                "transfer_rate": transfers / total if total > 0 else 0,
            }


# Global instance
_call_log_provider: Optional[CallLogProvider] = None


def get_call_log_provider() -> CallLogProvider:
    """Get the global call log provider instance."""
    global _call_log_provider
    if _call_log_provider is None:
        _call_log_provider = CallLogProvider()
    return _call_log_provider
