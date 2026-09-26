from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from typer.testing import CliRunner

from app import cli
from app.db.models import ReviewAlertDeliveryRow, ReviewAlertSubscriptionRow, FirmContactRow, PifFirmRow, AgentActionRow
from app.services import review_alerts, review_alert_lead_gen as bridge


def test_expiring_reviews_sort_first():
    deliveries = [SimpleNamespace(reviews=[{"review_date": date}]) for date in ("2026-09-19", "2026-09-07", "2026-09-12")]
    assert [bridge.oldest_review(d) for d in sorted(deliveries, key=bridge.oldest_review)] == ["2026-09-07", "2026-09-12", "2026-09-19"]


def test_standard_signature_has_no_invented_address_or_placeholder():
    subject, body = review_alerts.compose(SimpleNamespace(recipient_name="Nicole", firm_name="Example Firm"),
        [{"source": "google", "rating": 5, "review_date": "2026-09-10", "url": "https://google.com/maps", "text": "Helpful team."}], {}, standard_lead_gen=True)
    assert "postal address required" not in body
    assert "https://getpossibleminds.com" in body and "reply to this email" in body


def test_schedule_cli_uses_normal_queue_endpoint_and_bounded_limit(monkeypatch):
    call = {}
    start = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    monkeypatch.setattr(cli, "_post", lambda path, json_body=None, **kw: call.update(path=path, body=json_body) or {"scheduled": []})
    result = CliRunner().invoke(cli.app, ["review-alerts", "schedule", "--start", start, "--limit", "20", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert call["path"] == "/api/review-alerts/schedule" and call["body"]["limit"] == 20
    assert call["body"]["dry_run"] is True
    result = CliRunner().invoke(cli.app, ["review-alerts", "schedule", "--start", start, "--limit", "21"])
    assert result.exit_code != 0


def test_auto_schedule_config_cli(monkeypatch):
    call = {}
    monkeypatch.setattr(cli, "_post", lambda path, json_body=None, **kw: call.update(path=path, body=json_body) or json_body)
    result = CliRunner().invoke(cli.app, ["review-alerts", "config", "--auto-schedule",
        "--auto-schedule-time", "09:15", "--auto-schedule-limit", "20"])
    assert result.exit_code == 0, result.output
    assert call == {"path": "/api/review-alerts/config", "body": {
        "auto_schedule": True, "auto_schedule_time": "09:15", "auto_schedule_limit": 20}}


def test_automatic_start_waits_runs_once_and_rounds_forward():
    base = {"enabled": True, "auto_schedule": True, "delivery_mode": "lead_gen",
            "auto_schedule_time": "09:15"}
    before = datetime(2026, 9, 21, 16, 0, tzinfo=timezone.utc)  # 09:00 PDT
    assert bridge.automatic_start(base, before) is None
    after = datetime(2026, 9, 21, 16, 17, tzinfo=timezone.utc)  # 09:17 PDT
    assert bridge.automatic_start(base, after) == datetime(2026, 9, 21, 16, 35, tzinfo=timezone.utc)
    assert bridge.automatic_start({**base, "last_auto_schedule_day": "2026-09-21"}, after) is None
    assert bridge.automatic_start({**base, "auto_schedule_retry_at": "2026-09-21T17:00:00+00:00"}, after) is None


@pytest.mark.asyncio
async def test_automatic_schedule_records_success(monkeypatch):
    current = datetime(2026, 9, 21, 17, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(review_alerts, "now", lambda: current)
    scheduled = AsyncMock(return_value={"scheduled": [{"action_id": "a"}], "skipped": []})
    monkeypatch.setattr(bridge, "schedule", scheduled)
    save = AsyncMock()
    monkeypatch.setattr(review_alerts, "configure", save)
    config = {"enabled": True, "auto_schedule": True, "delivery_mode": "lead_gen",
              "auto_schedule_time": "09:15", "auto_schedule_limit": 20}
    result = await bridge.run_automatic_schedule(config)
    assert result["scheduled"][0]["action_id"] == "a"
    assert scheduled.call_args.kwargs["automatic"] is True
    assert scheduled.call_args.kwargs["actor"] == "review-alerts-auto"
    assert save.call_args.args[0]["last_auto_schedule_day"] == "2026-09-21"


@pytest.mark.asyncio
async def test_automatic_schedule_failure_sets_retry_without_marking_day(monkeypatch):
    current = datetime(2026, 9, 21, 17, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(review_alerts, "now", lambda: current)
    monkeypatch.setattr(bridge, "schedule", AsyncMock(side_effect=RuntimeError("mailbox unavailable")))
    save = AsyncMock()
    monkeypatch.setattr(review_alerts, "configure", save)
    config = {"enabled": True, "auto_schedule": True, "delivery_mode": "lead_gen",
              "auto_schedule_time": "09:15", "auto_schedule_limit": 20}
    with pytest.raises(RuntimeError, match="mailbox unavailable"):
        await bridge.run_automatic_schedule(config)
    changes = save.call_args.args[0]
    assert changes["last_auto_schedule_error"] == "mailbox unavailable"
    assert changes["auto_schedule_retry_at"] == "2026-09-21T17:30:00+00:00"
    assert "last_auto_schedule_day" not in changes


def setup_guard(monkeypatch, *, posted="2026-09-10", subscription="active", delivery_status="scheduled"):
    current = datetime(2026, 9, 20, 18, tzinfo=timezone.utc)
    monkeypatch.setattr(review_alerts, "now", lambda: current)
    d = SimpleNamespace(id="d", pif_id="f", status=delivery_status, lead_gen_action_id="a", lead_gen_item_id="i", recipient_email="alex@example.com", reviews=[{"review_date": posted, "url": "https://google.com/maps"}])
    sub = SimpleNamespace(pif_id="f", status=subscription, recipient_email=d.recipient_email, contact_id="c", domain="example.com", created_at=current-timedelta(days=10))
    action = SimpleNamespace(id="a", scheduled_for=current+timedelta(minutes=30), input_json={"review_alert_delivery_id": "d", "to": d.recipient_email, "batch_item_id": "i", "subject": "A new review", "body": "https://google.com/maps", "transport": "resend"})
    objects = {ReviewAlertDeliveryRow: d, ReviewAlertSubscriptionRow: sub, AgentActionRow: action,
               PifFirmRow: SimpleNamespace(source_json={}, canonical_website="example.com"),
               FirmContactRow: SimpleNamespace(email=d.recipient_email)}
    session = AsyncMock()
    session.get.side_effect = lambda model, key, **kw: objects.get(model)
    session.scalar.return_value = None
    session.__aenter__.return_value = session
    monkeypatch.setattr(bridge, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(review_alerts, "settings", AsyncMock(return_value={"mailbox_checked_at": current.isoformat()}))
    monkeypatch.setattr(review_alerts, "leader_candidate", lambda *args: (0, "alex@example.com", "c"))
    monkeypatch.setattr(review_alerts, "suppression", AsyncMock(return_value=None))
    monkeypatch.setattr(bridge, "reply_readiness", lambda transport: None)
    monkeypatch.setattr(bridge, "conflict", AsyncMock(return_value=None))
    return session, d, action


@pytest.mark.asyncio
@pytest.mark.parametrize("posted,status,delivery_status,reason", [
    ("2026-09-06", "active", "scheduled", "14-day"),
    ("2026-09-10", "unsubscribed", "scheduled", "Subscription"),
    ("2026-09-10", "active", "sent", "not scheduled"),
])
async def test_send_time_guards(monkeypatch, posted, status, delivery_status, reason):
    session, d, action = setup_guard(monkeypatch, posted=posted, subscription=status, delivery_status=delivery_status)
    assert reason in await bridge.action_guard(session, action)


@pytest.mark.asyncio
async def test_claim_is_durable_and_second_claim_cannot_send(monkeypatch):
    session, d, action = setup_guard(monkeypatch)
    await bridge.claim("a", "d")
    assert d.status == "sending" and session.commit.await_count == 1
    assert d.body == action.input_json["body"]
    with pytest.raises(ValueError, match="not scheduled"):
        await bridge.claim("a", "d")


@pytest.mark.asyncio
async def test_stale_mailbox_blocks_scheduled_review(monkeypatch):
    session, d, action = setup_guard(monkeypatch)
    monkeypatch.setattr(review_alerts, "settings", AsyncMock(return_value={"mailbox_checked_at": "2026-09-20T12:00:00+00:00"}))
    assert "stale" in await bridge.action_guard(session, action)


def test_review_resend_failure_does_not_fall_back_to_smtp(monkeypatch):
    from app.services import email_notification_service as email
    monkeypatch.setattr(email, "_resolve_sender_address", lambda value: "sender@example.com")
    monkeypatch.setattr(email, "_choose_email_transport", lambda value: "resend")
    monkeypatch.setattr(review_alerts, "outgoing_suppression", lambda *args: False)
    monkeypatch.setattr(email, "_send_via_resend", MagicMock(side_effect=TimeoutError("unknown acceptance")))
    smtp = MagicMock()
    monkeypatch.setattr(email, "_send_via_smtp", smtp)
    monkeypatch.setattr(email, "log_email", lambda **kw: None)
    with pytest.raises(TimeoutError):
        email._send_email("Review", "Body", to="alex@example.com", source_type="review_alert", source_id="d")
    smtp.assert_not_called()
