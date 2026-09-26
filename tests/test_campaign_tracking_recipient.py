import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from typer.testing import CliRunner

from app.db.models import EngagementCampaignRow, EngagementCampaignLinkRow, FirmContactRow, PifFirmRow
from app.services import engagement_campaigns as service


@pytest.fixture
def session(monkeypatch):
    session = AsyncMock()
    session.add = MagicMock()
    session.campaign = EngagementCampaignRow(id="campaign", name="Test", campaign_date=date(2026, 9, 11), status="draft", destination_url="https://getpossibleminds.com/blog/test")
    session.contacts = []

    async def get(model, key):
        if model is EngagementCampaignRow:
            return session.campaign
        if model is FirmContactRow:
            return next((c for c in session.contacts if c.id == key), None)
        if model is PifFirmRow:
            return SimpleNamespace(id="firm") if key == "firm" else None
        return None

    async def refresh(row):
        row.created_at = datetime.now(timezone.utc)

    session.get.side_effect = get
    session.refresh.side_effect = refresh
    result = MagicMock()
    result.scalars.return_value.all.side_effect = lambda: session.contacts
    session.execute.return_value = result
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    monkeypatch.setattr(service, "AsyncSessionLocal", factory)
    return session


def create(**kwargs):
    return asyncio.run(service.create_tracking_link(campaign_id="campaign", channel="linkedin", **kwargs))


def test_name_only_recipient_is_contact_and_link_in_one_commit(session):
    result = create(recipient_name="  Tim Miley  ")
    rows = [c.args[0] for c in session.add.call_args_list]
    contact = next(row for row in rows if isinstance(row, FirmContactRow))
    link = next(row for row in rows if isinstance(row, EngagementCampaignLinkRow))
    assert contact.full_name == "Tim Miley"
    assert contact.pif_id == ""
    assert contact.email is None
    assert contact.source == "campaign_manual"
    assert link.contact_id == result["contact_id"] == contact.id
    assert link.pif_id is None
    assert link.sent_at is None
    session.commit.assert_awaited_once()


def test_new_email_recipient_is_normalized_and_associated_with_verified_firm(session):
    result = create(recipient_name="Tim", recipient_email=" Tim@Example.com ", recipient_firm_id="firm")
    contact = session.add.call_args_list[0].args[0]
    assert contact.email == "tim@example.com"
    assert result["pif_id"] == "firm"
    assert "pg_advisory_xact_lock" in str(session.execute.call_args_list[0].args[0])


def test_known_email_reuses_contact_without_overwriting_identity(session):
    known = FirmContactRow(id="known", pif_id="firm", full_name="Verified name", email="tim@example.com")
    session.contacts = [known]
    result = create(recipient_name="Different typing", recipient_email="TIM@example.com")
    assert result["contact_id"] == "known"
    assert known.full_name == "Verified name"
    assert all(not isinstance(call.args[0], FirmContactRow) for call in session.add.call_args_list)


@pytest.mark.parametrize("payload,error", [
    ({"recipient_name": "Tim", "recipient_email": "broken"}, "recipient_email_invalid"),
    ({"recipient_name": "Tim", "recipient_email": "a@"}, "recipient_email_invalid"),
    ({"recipient_name": "Tim", "recipient_email": "a\nb@example.com"}, "recipient_email_invalid"),
    ({"recipient_email": "tim@example.com"}, "recipient_name_required"),
    ({"recipient_name": "Tim", "recipient_firm_id": "missing"}, "recipient_firm_not_found"),
    ({"recipient_name": "Tim", "contact_id": "known"}, "choose_existing_contact_or_new_recipient"),
    ({"recipient_name": "Tim", "destination_url": "https://example.org"}, "destination_must_be_possible_minds"),
])
def test_invalid_requests_never_commit_contacts_or_links(session, payload, error):
    with pytest.raises(service.EngagementCampaignError, match=error):
        create(**payload)
    session.commit.assert_not_awaited()
    session.add.assert_not_called()


def test_ambiguous_or_conflicting_email_requires_existing_contact_selection(session):
    session.contacts = [FirmContactRow(id="known", pif_id="other", email="a@example.com")]
    with pytest.raises(service.EngagementCampaignError, match="firm_mismatch"):
        create(recipient_name="A", recipient_email="a@example.com", recipient_firm_id="firm")
    session.contacts.append(FirmContactRow(id="another", pif_id="firm", email="a@example.com"))
    with pytest.raises(service.EngagementCampaignError, match="multiple_contacts"):
        create(recipient_name="A", recipient_email="a@example.com")
    session.commit.assert_not_awaited()


def test_existing_contact_and_public_link_paths_remain_available(session):
    session.contacts = [FirmContactRow(id="known", pif_id="firm", full_name="Tim")]
    assert create(contact_id="known")["contact_id"] == "known"
    result = asyncio.run(service.create_tracking_link(campaign_id="campaign", channel="public", label="Public post"))
    assert result["contact_id"] is None
    with pytest.raises(service.EngagementCampaignError, match="choose_existing"):
        asyncio.run(service.create_tracking_link(campaign_id="campaign", channel="public", recipient_name="Tim"))


def test_cli_and_api_forward_inline_fields(monkeypatch):
    from app import cli
    from app.api.engagement_campaigns import CampaignLinkCreateRequest, create_campaign_link_endpoint
    post = MagicMock(return_value={"tracking_url": "https://getpossibleminds.com/t/test"})
    monkeypatch.setattr(cli, "_post", post)
    result = CliRunner().invoke(cli.app, ["campaigns", "link", "campaign", "--channel", "linkedin", "--recipient-name", "Tim", "--recipient-email", "tim@example.com", "--recipient-firm-id", "firm", "--json"])
    assert result.exit_code == 0
    body = post.call_args.args[1]
    assert body["recipient_name"] == "Tim"
    assert body["recipient_email"] == "tim@example.com"
    assert body["recipient_firm_id"] == "firm"
    mock = AsyncMock(return_value={"contact_id": "new"})
    monkeypatch.setattr("app.api.engagement_campaigns.create_tracking_link", mock)
    asyncio.run(create_campaign_link_endpoint("campaign", CampaignLinkCreateRequest(**body)))
    assert mock.call_args.kwargs["recipient_name"] == "Tim"
