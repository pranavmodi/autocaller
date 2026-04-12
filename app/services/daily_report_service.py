"""Daily Slack report — posts yesterday's AI call summary to a Slack webhook.

Configuration is stored in the database (SystemSettings.daily_report) and
editable via the dashboard UI.  A few legacy env var fallbacks are kept so
the webhook URL can still be supplied outside the DB for secrecy if desired.
"""
import asyncio
import logging
import os
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TZ = "America/Los_Angeles"
DEFAULT_HOUR = 7


async def _load_config() -> dict:
    """Resolve the runtime config, preferring DB settings and falling back to env vars."""
    from app.providers.settings_provider import get_settings_provider
    try:
        settings = await get_settings_provider().get_settings()
        dr = settings.daily_report
        return {
            "enabled": bool(dr.enabled),
            "webhook_url": dr.webhook_url or os.getenv("SLACK_DAILY_REPORT_WEBHOOK_URL", "").strip(),
            "hour": int(dr.hour),
            "timezone": dr.timezone or DEFAULT_TZ,
        }
    except Exception as e:
        logger.warning("Failed to load daily report config from DB, using env vars: %s", e)
        return {
            "enabled": os.getenv("SLACK_DAILY_REPORT_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on"),
            "webhook_url": os.getenv("SLACK_DAILY_REPORT_WEBHOOK_URL", "").strip(),
            "hour": int(os.getenv("SLACK_DAILY_REPORT_HOUR", str(DEFAULT_HOUR)) or DEFAULT_HOUR),
            "timezone": os.getenv("SLACK_DAILY_REPORT_TIMEZONE", DEFAULT_TZ).strip() or DEFAULT_TZ,
        }


def _format_slack_message(stats: dict) -> dict:
    """Format the stats dict as a Slack webhook payload."""
    disp = stats.get("dispositions", {}) or {}
    total = stats.get("total_calls", 0)
    transferred = disp.get("transferred", 0)
    transfer_rate = f"{round(100 * transferred / total)}%" if total else "—"

    lines = [
        f"*Precise Imaging — AI Call Summary for {stats.get('date', 'unknown')}*",
        "",
        f"• Calls placed: *{total}*",
        f"• Transferred to scheduler: *{transferred}* ({transfer_rate})",
        f"• Voicemails left: *{disp.get('voicemail_left', 0)}*",
        f"• No answers: *{disp.get('no_answer', 0)}*",
        f"• Callback requested: *{disp.get('callback_requested', 0)}*",
        f"• Hung up: *{disp.get('hung_up', 0)}*",
        f"• Wrong number: *{disp.get('wrong_number', 0)}*",
        f"• Invalid/disconnected number: *{disp.get('disconnected_number', 0)}*",
        f"• Technical errors: *{disp.get('technical_error', 0)}*",
        "",
        f"SMS messages sent: *{stats.get('sms', 0)}*",
    ]
    return {"text": "\n".join(lines)}


async def send_daily_report(for_date: Optional[date] = None) -> bool:
    """Send the daily report for the given local date (default: yesterday).

    Returns True on success, False on any failure (config missing, HTTP error).
    Bypasses the enabled toggle — intended for manual test triggers.
    """
    config = await _load_config()
    webhook_url = config["webhook_url"]
    if not webhook_url:
        logger.warning("Daily report skipped: webhook URL not configured")
        return False

    tz_name = config["timezone"]
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz_name = DEFAULT_TZ
        tz = ZoneInfo(DEFAULT_TZ)

    if for_date is None:
        now_local = datetime.now(tz)
        for_date = (now_local - timedelta(days=1)).date()

    from app.providers.call_log_provider import get_call_log_provider
    provider = get_call_log_provider()
    stats = await provider.get_stats_for_date(for_date, tz_name=tz_name)
    payload = _format_slack_message(stats)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
        logger.info(
            "Daily report sent to Slack for %s (total=%s, transferred=%s)",
            stats.get("date"), stats.get("total_calls", 0),
            stats.get("dispositions", {}).get("transferred", 0),
        )
        return True
    except Exception as e:
        logger.warning("Failed to send daily report to Slack: %s", e)
        return False


async def daily_report_loop():
    """Background loop that checks the DB config hourly and sends the report at the configured hour.

    Checking every hour (instead of sleeping until next run) means UI changes
    to the config take effect without restarting the backend.
    """
    logger.info("Daily Slack report loop started — will check config each hour")
    last_sent_date: Optional[date] = None

    while True:
        try:
            config = await _load_config()
            enabled = config["enabled"]
            tz_name = config["timezone"]
            hour = max(0, min(23, int(config["hour"])))

            try:
                tz = ZoneInfo(tz_name)
            except Exception:
                tz = ZoneInfo(DEFAULT_TZ)

            now_local = datetime.now(tz)
            today = now_local.date()

            if enabled and now_local.hour == hour and last_sent_date != today:
                logger.info("Daily report window reached (%02d:00 %s) — sending", hour, tz_name)
                ok = await send_daily_report()
                if ok:
                    last_sent_date = today
        except asyncio.CancelledError:
            logger.info("Daily report loop cancelled")
            return
        except Exception as e:
            logger.warning("Daily report loop error: %s", e)

        # Sleep until the start of the next clock hour + a 30s buffer
        try:
            now = datetime.now()
            next_hour = now.replace(minute=0, second=30, microsecond=0) + timedelta(hours=1)
            await asyncio.sleep(max(60, (next_hour - now).total_seconds()))
        except asyncio.CancelledError:
            logger.info("Daily report loop cancelled")
            return
