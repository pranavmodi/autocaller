from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from app import cli
from app.api.review_alerts import router
from app.db.models import EmailLogRow, FirmContactRow, PifFirmRow, ReviewAlertDeliveryRow, ReviewAlertSubscriptionRow
from app.services import review_alerts as alerts


def corpus(**changes):
    review = {"reviewer_name": "Client A", "text": "They answered every question.\nThank you for your help!", "rating": 5,
              "review_date": "2026-09-20", "collected_at": "2026-09-20", **changes}
    return {"sources": [{"source": "google", "listing_url": "https://www.google.com/maps?cid=1", "reviews": [review]}]}


@pytest.mark.parametrize("value,expected", [("2026-09-07", True), ("2026-09-20", True),
    ("2026-09-06", False), ("2026-09-21", False), (None, False), ("2 days ago", False), ("2026-02-30", False)])
def test_exact_publication_window(value, expected):
    assert alerts.recent_date(value, date(2026, 9, 20)) is expected


def test_review_alert_worker_has_no_independent_research_producer():
    assert not hasattr(alerts, "queue_research")


def test_collection_date_does_not_make_old_or_unknown_review_eligible():
    for value in (None, "2026-08-01"):
        assert alerts.eligible_reviews(corpus(review_date=value), date(2026, 9, 20)) == []


def test_review_edit_does_not_change_identity():
    a = alerts.eligible_reviews(corpus(), date(2026, 9, 20))
    b = alerts.eligible_reviews(corpus(text="Edited", rating=1), date(2026, 9, 20))
    assert a[0]["key"] == b[0]["key"]


def test_shared_listing_does_not_collapse_different_reviewers():
    data = corpus()
    data["sources"][0]["reviews"].append({**data["sources"][0]["reviews"][0], "reviewer_name": "Client B"})
    assert len(alerts.eligible_reviews(data, date(2026, 9, 20))) == 2


@pytest.mark.parametrize("url", ["https://google.com.evil.test/review", "javascript:alert(1)", "https://user@google.com/maps", "http://google.com/maps", "https://127.0.0.1/review"])
def test_bad_platform_links_not_emailed(url):
    assert alerts.eligible_reviews(corpus(review_url=url), date(2026, 9, 20)) == []


def contact(title, email="alex@firm.test"):
    return SimpleNamespace(id="c", full_name="Alex Founder", email=email, title=title,
                           research_title=None, source="pif_leadership")


def test_leader_order_and_no_staff_or_cross_firm_leakage():
    decisions = {title: {"role": role, "confidence": 99, "evidence": title} for title, role in (
        ("Founder", "founder_owner"), ("Managing Partner", "managing_partner"), ("Chief Operating Officer", "coo"),
        ("Medical Records Coordinator", "other"), ("Assistant to Founder", "other"))}
    assert alerts.leader_candidate(contact("Founder"), "firm.test", decisions)[0] == 0
    assert alerts.leader_candidate(contact("Managing Partner"), "firm.test", decisions)[0] == 1
    assert alerts.leader_candidate(contact("Chief Operating Officer"), "firm.test", decisions)[0] == 2
    for candidate in (contact("Medical Records Coordinator"), contact("Assistant to Founder"), contact("Office Manager"), contact("Partner"), contact("Founder", "jaklin@precisemri.com"), contact("Founder", "info@firm.test")):
        assert alerts.leader_candidate(candidate, "firm.test", decisions) is None
    assert alerts.leader_candidate(contact("Founder"), "firm.test", {}) is None
    fake = contact("Founder")
    fake.full_name = fake.email
    assert alerts.leader_candidate(fake, "firm.test", decisions) is None


def test_message_contains_verbatim_review_reviewer_source_and_optout():
    sub = SimpleNamespace(recipient_name="Alex Founder", firm_name="Example Law")
    subject, body = alerts.compose(sub, alerts.eligible_reviews(corpus(), date(2026, 9, 20)), {"postal_address": "TEST ADDRESS"})
    assert "Example Law" in subject and "Hi Alex," in body
    assert "Posted 2026-09-20" in body and "https://www.google.com/maps?cid=1" in body
    assert "reply to this email" in body and "TEST ADDRESS" in body
    assert '"They answered every question.\nThank you for your help!"' in body
    assert "Reviewer: Client A" in body
    assert body.index("They answered") < body.index("https://www.google.com/maps?cid=1")


@pytest.mark.parametrize("standard_lead_gen", [False, True])
def test_review_response_advice_is_conditional_and_precedes_feedback_request(standard_lead_gen):
    sub = SimpleNamespace(recipient_name="Alex Founder", firm_name="Example Law")
    _, body = alerts.compose(sub, alerts.eligible_reviews(corpus(), date(2026, 9, 20)), {}, standard_lead_gen=standard_lead_gen)
    assert "prospective clients read how a firm replies" in body
    assert "If you haven't replied yet" in body
    assert "thank the reviewer personally" in body
    assert "invite a private conversation rather than arguing publicly" in body
    assert "Keep client and case details out of public replies." in body
    assert body.count("Your response matters too:") == 1
    assert body.index("Source:") < body.index("Your response matters too:") < body.index("Would a heads-up")
    assert "reply to this email" in body


@pytest.mark.parametrize("value", [None, "", "  ", 123, {"summary": "Great firm"}])
def test_missing_or_invalid_review_text_is_not_eligible(value):
    assert alerts.eligible_reviews(corpus(text=value), date(2026, 9, 20)) == []


def test_compose_never_falls_back_to_link_only_or_summarizes_long_text():
    sub = SimpleNamespace(recipient_name="Alex", firm_name="Example Law")
    text = "Full review, with original punctuation!\n" * 100
    reviews = alerts.eligible_reviews(corpus(text=text), date(2026, 9, 20))
    assert reviews[0]["text"] == text
    assert text in alerts.compose(sub, reviews, {}, standard_lead_gen=True)[1]
    del reviews[0]["text"]
    with pytest.raises(ValueError, match="Review text is missing"):
        alerts.compose(sub, reviews, {}, standard_lead_gen=True)


def fake_session(monkeypatch, rows, scalars=()):
    session = AsyncMock()
    session.add = MagicMock()
    async def get(model, key, **kwargs):
        return rows.get(model)
    session.get.side_effect = get
    session.scalar.side_effect = list(scalars)
    session.__aenter__.return_value = session
    monkeypatch.setattr(alerts, "AsyncSessionLocal", lambda: session)
    return session


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_send_is_claimed_before_provider_logged_and_never_retried(monkeypatch, failed):
    from app.services import email_notification_service as sender
    async def in_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr(alerts.asyncio, "to_thread", in_thread)
    d = SimpleNamespace(id="delivery", pif_id="f", recipient_email="alex@firm.test", recipient_name="Alex Founder", status="queued", reviews=alerts.eligible_reviews(corpus(), date(2026, 9, 20)), started_at=None)
    sub = SimpleNamespace(pif_id="f", status="active", recipient_email=d.recipient_email, recipient_name=d.recipient_name, contact_id="c", domain="firm.test", firm_name="Example Law", created_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    firm = SimpleNamespace(source_json={}, canonical_website="firm.test")
    log = SimpleNamespace()
    s = fake_session(monkeypatch, {ReviewAlertDeliveryRow: d, ReviewAlertSubscriptionRow: sub, PifFirmRow: firm, FirmContactRow: contact("Founder"), EmailLogRow: log}, [None, 0, None])
    monkeypatch.setattr(alerts, "now", lambda: datetime(2026, 9, 20, 12, tzinfo=timezone.utc))
    monkeypatch.setattr(alerts, "settings", AsyncMock(return_value={**alerts.DEFAULTS, "enabled": True, "auto_send": True, "postal_address": "TEST", "sender": "sender@test.com", "title_decisions": {"Founder": {"role": "founder_owner", "confidence": 99, "evidence": "Founder"}}}))
    monkeypatch.setattr(alerts, "readiness", lambda config: [])
    monkeypatch.setattr(alerts, "suppression", AsyncMock(return_value=None))
    calls = []
    def send(*args, **kwargs):
        assert d.status == "sending" and s.commit.await_count == 1
        logged = s.add.call_args.args[0]
        assert logged.message_type == "review_alert" and logged.body_excerpt == args[1]
        assert kwargs["source_id"] == "delivery"
        calls.append(kwargs)
        if failed:
            raise TimeoutError("Provider response lost")
        return "message-1"
    monkeypatch.setattr(sender, "_send_email", send)
    assert await alerts.send_one("delivery") == ("uncertain" if failed else "sent")
    assert d.status == log.status
    assert await alerts.send_one("delivery") == "skipped"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_unsubscribed_queue_never_reaches_provider(monkeypatch):
    from app.services import email_notification_service as sender
    d = SimpleNamespace(id="d", pif_id="f", status="queued", recipient_email="alex@firm.test")
    sub = SimpleNamespace(status="unsubscribed", recipient_email=d.recipient_email, contact_id="c")
    s = fake_session(monkeypatch, {ReviewAlertDeliveryRow: d, ReviewAlertSubscriptionRow: sub})
    monkeypatch.setattr(alerts, "settings", AsyncMock(return_value={**alerts.DEFAULTS, "enabled": True, "auto_send": True}))
    monkeypatch.setattr(alerts, "readiness", lambda config: [])
    send = MagicMock()
    monkeypatch.setattr(sender, "_send_email", send)
    assert await alerts.send_one("d") == "cancelled"
    assert d.status == "cancelled" and s.commit.await_count == 1
    send.assert_not_called()


@pytest.mark.asyncio
async def test_reenrollment_cannot_undo_optout(monkeypatch):
    sub = SimpleNamespace(status="unsubscribed")
    fake_session(monkeypatch, {ReviewAlertSubscriptionRow: sub})
    with pytest.raises(ValueError, match="fresh documented consent"):
        await alerts.set_subscription("f", "active")


def test_activation_requires_address_and_monitored_inbox(monkeypatch):
    monkeypatch.setattr(alerts, "settings", AsyncMock(return_value=alerts.DEFAULTS))
    monkeypatch.setattr(alerts, "readiness", lambda config: ["Business postal address is required"])
    save = AsyncMock()
    monkeypatch.setattr(alerts, "configure", save)
    app = FastAPI()
    app.include_router(router)
    result = TestClient(app).post("/api/review-alerts/config", json={"auto_send": True})
    assert result.status_code == 400
    save.assert_not_awaited()


def test_cli_dry_run_default_and_explicit_execution(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "_post", lambda path, *a, **kw: calls.append(path) or {"selected": 2})
    runner = CliRunner()
    assert runner.invoke(cli.app, ["review-alerts", "enroll"]).exit_code == 0
    assert runner.invoke(cli.app, ["review-alerts", "enroll", "--execute"]).exit_code == 0
    assert calls == ["/api/review-alerts/enroll?dry_run=true", "/api/review-alerts/enroll?dry_run=false"]


def test_common_sender_blocks_optout_and_records_source(monkeypatch):
    from app.services import email_notification_service as sender
    monkeypatch.setattr(sender, "_resolve_sender_address", lambda value: "sender@test.com")
    monkeypatch.setattr(sender, "_choose_email_transport", lambda value: "zoho_api")
    monkeypatch.setattr(alerts, "outgoing_suppression", lambda *args: True)
    send, logs = MagicMock(), []
    monkeypatch.setattr(sender, "_send_via_zoho_api", send)
    monkeypatch.setattr(sender, "log_email", lambda **kwargs: logs.append(kwargs))
    with pytest.raises(RuntimeError, match="opted out"):
        sender._send_email("Subject", "Full body", to="alex@firm.test", source_type="review_alert", source_id="delivery")
    send.assert_not_called()
    assert logs[0]["source_id"] == "delivery" and logs[0]["status"] == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("quote,valid", [("Founder", True), ("Chief founder", False)])
async def test_title_decisions_require_exact_evidence_and_persist_usage(monkeypatch, quote, valid):
    from app.services import llm_gateway
    s = fake_session(monkeypatch, {})
    result = MagicMock()
    result.all.return_value = [(contact("Founder"), "firm.test"), (contact("Founder"), "firm.test")]
    s.execute.return_value = result
    monkeypatch.setattr(alerts, "settings", AsyncMock(return_value=alerts.DEFAULTS))
    save = AsyncMock()
    monkeypatch.setattr(alerts, "configure", save)
    gateway = AsyncMock(return_value=SimpleNamespace(parsed={"decisions": [
        {"id": "0", "role": "founder_owner", "confidence": 99, "evidence": quote, "reason": "Explicit role"}]},
        model="openclaw/main", raw_response="decision", usage={"prompt_tokens": 123}))
    monkeypatch.setattr(llm_gateway, "call_skill_json", gateway)
    if valid:
        assert await alerts.classify_leader_titles() == 0
        data = save.call_args.args[0]
        assert data["title_decisions"]["Founder"]["evidence"] == "Founder"
        assert data["last_title_classification"]["usage"]["prompt_tokens"] == 123
    else:
        with pytest.raises(ValueError, match="exact substring"):
            await alerts.classify_leader_titles()
        save.assert_not_awaited()
    assert len(gateway.call_args.kwargs["payload"]["titles"]) == 1
    assert gateway.call_args.kwargs["prompt_cache_key"]


@pytest.mark.asyncio
async def test_reply_is_paused_and_queue_cancelled_before_classifier_failure(monkeypatch):
    from app.db.models import ReviewAlertReplyRow
    from app.services import lead_feedback_classifier
    reply = SimpleNamespace(id="inbound", subject="Stop", body_text="Please stop", from_email="alex@firm.test")
    sub = SimpleNamespace(pif_id="f", contact_id="c", recipient_email="alex@firm.test", recipient_name="Alex Founder", firm_name="Example Law", status="active")
    audit = SimpleNamespace(decision={})
    s = fake_session(monkeypatch, {ReviewAlertReplyRow: audit})
    result = MagicMock()
    result.all.return_value = [(reply, sub)]
    s.execute.return_value = result
    async def classify(**kwargs):
        assert sub.status == "paused"
        assert s.commit.await_count == 1
        assert "cancelled" in str(s.execute.call_args.args[0].compile(compile_kwargs={"literal_binds": True}))
        raise RuntimeError("Gateway unavailable")
    monkeypatch.setattr(lead_feedback_classifier, "classify_feedback_event", classify)
    assert await alerts.pause_replies() == 1
    assert sub.status == "paused" and audit.decision["held"] is True
