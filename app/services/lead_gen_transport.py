"""Provider-aware lead-gen email transport routing."""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.db import AsyncSessionLocal
from app.db.models import EmailLogRow


PT = ZoneInfo("America/Los_Angeles")
ZOHO_API = "zoho_api"
RESEND = "resend"
SUPPORTED_LEAD_GEN_TRANSPORTS = (ZOHO_API, RESEND)
DEFAULT_LEAD_GEN_TRANSPORT_STRATEGY = "zoho_first_then_resend"
DEFAULT_ZOHO_DAILY_CAP = 20
COUNTED_SEND_STATUSES = (
    "sent",
    "delivered",
    "delayed",
    "bounced",
    "failed",
    "complained",
    "suppressed",
    "opened",
    "clicked",
)


def _today_pt() -> date:
    return datetime.now(timezone.utc).astimezone(PT).date()


def _pt_day_bounds(target: date) -> tuple[datetime, datetime]:
    start = datetime.combine(target, time.min, tzinfo=PT)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _int_value(value: Any, default: int, *, minimum: int = 0, maximum: int = 10_000) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def lead_gen_transport_strategy(weights: dict[str, Any] | None) -> str:
    strategy = str((weights or {}).get("lead_gen_transport_strategy") or "").strip().lower()
    return strategy or DEFAULT_LEAD_GEN_TRANSPORT_STRATEGY


def provider_daily_caps_from_weights(
    weights: dict[str, Any] | None,
    *,
    total_daily_budget: int | None = None,
) -> dict[str, int]:
    weights = weights or {}
    raw_caps = weights.get("provider_daily_caps")
    raw_caps = raw_caps if isinstance(raw_caps, dict) else {}
    total = _int_value(
        total_daily_budget if total_daily_budget is not None else weights.get("daily_send_budget"),
        50,
        minimum=0,
        maximum=200,
    )
    zoho_cap = _int_value(raw_caps.get(ZOHO_API), DEFAULT_ZOHO_DAILY_CAP, minimum=0, maximum=total)
    resend_default = max(0, total - zoho_cap)
    resend_cap = _int_value(raw_caps.get(RESEND), resend_default, minimum=0, maximum=200)
    return {ZOHO_API: zoho_cap, RESEND: resend_cap}


def configured_lead_gen_transports() -> set[str]:
    configured: set[str] = set()
    if os.getenv("ZOHO_MAIL_REFRESH_TOKEN", "").strip():
        configured.add(ZOHO_API)
    if os.getenv("RESEND_API_KEY", "").strip():
        configured.add(RESEND)
    return configured


async def sent_counts_by_transport_for_day(
    *,
    run_date: date | None = None,
) -> dict[str, int]:
    start_utc, end_utc = _pt_day_bounds(run_date or _today_pt())
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(EmailLogRow.transport, func.count(EmailLogRow.id))
            .where(EmailLogRow.status.in_(COUNTED_SEND_STATUSES))
            .where(EmailLogRow.sent_at >= start_utc)
            .where(EmailLogRow.sent_at < end_utc)
            .where(EmailLogRow.transport.in_(SUPPORTED_LEAD_GEN_TRANSPORTS))
            .group_by(EmailLogRow.transport)
        )).all()
    return {str(transport): int(count or 0) for transport, count in rows}


def lead_gen_transport_snapshot_from_counts(
    weights: dict[str, Any] | None,
    *,
    counts: dict[str, int],
    configured: set[str] | None = None,
    total_daily_budget: int | None = None,
) -> dict[str, Any]:
    configured = configured_lead_gen_transports() if configured is None else configured
    caps = provider_daily_caps_from_weights(weights, total_daily_budget=total_daily_budget)
    providers = []
    for transport in SUPPORTED_LEAD_GEN_TRANSPORTS:
        cap = caps.get(transport, 0)
        sent_today = int(counts.get(transport, 0) or 0)
        remaining = max(0, cap - sent_today)
        providers.append({
            "transport": transport,
            "configured": transport in configured,
            "sent_today": sent_today,
            "cap": cap,
            "remaining": remaining,
            "available": transport in configured and remaining > 0,
        })
    return {
        "strategy": lead_gen_transport_strategy(weights),
        "providers": providers,
        "available": any(provider["available"] for provider in providers),
    }


def choose_lead_gen_transport_from_counts(
    weights: dict[str, Any] | None,
    *,
    counts: dict[str, int],
    configured: set[str] | None = None,
    total_daily_budget: int | None = None,
) -> str:
    snapshot = lead_gen_transport_snapshot_from_counts(
        weights,
        counts=counts,
        configured=configured,
        total_daily_budget=total_daily_budget,
    )
    providers_by_name = {provider["transport"]: provider for provider in snapshot["providers"]}
    strategy = snapshot["strategy"]
    if strategy == "resend_first_then_zoho":
        order = (RESEND, ZOHO_API)
    else:
        order = (ZOHO_API, RESEND)
    for transport in order:
        provider = providers_by_name[transport]
        if provider["available"]:
            return transport
    detail = ", ".join(
        f"{provider['transport']} configured={provider['configured']} "
        f"sent={provider['sent_today']}/{provider['cap']}"
        for provider in snapshot["providers"]
    )
    raise RuntimeError(f"lead_gen_email_transport_unavailable: {detail}")


async def lead_gen_transport_availability(
    weights: dict[str, Any] | None,
    *,
    run_date: date | None = None,
    total_daily_budget: int | None = None,
) -> dict[str, Any]:
    counts = await sent_counts_by_transport_for_day(run_date=run_date)
    return lead_gen_transport_snapshot_from_counts(
        weights,
        counts=counts,
        total_daily_budget=total_daily_budget,
    )


async def choose_lead_gen_transport(
    weights: dict[str, Any] | None,
    *,
    run_date: date | None = None,
    total_daily_budget: int | None = None,
) -> str:
    counts = await sent_counts_by_transport_for_day(run_date=run_date)
    return choose_lead_gen_transport_from_counts(
        weights,
        counts=counts,
        total_daily_budget=total_daily_budget,
    )
