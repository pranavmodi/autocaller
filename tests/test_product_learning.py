from datetime import datetime, timezone

from app.db.models import ImprovementFindingRow, LinkEventRow, OutreachCampaignRow, OutreachSendRow
from app.services.product_learning import (
    _eval_payload_for_finding,
    finding_to_dict,
    link_event_trace_kwargs,
)


def test_precise_opener_finding_creates_concrete_eval_payload():
    finding = ImprovementFindingRow(
        id="find_1",
        finding_key="email_composer.precise_opener_added_by_user",
        workflow="lead-gen",
        finding_type="email_composer_skill",
        summary="Precise opener missing",
        details="User keeps adding the Precise proof point.",
        evidence_trace_ids=["trace-1"],
        evidence_json={"count": 1},
        severity="normal",
        confidence=70,
        suggested_change_json={"target": "SKILL.md"},
        status="proposed",
    )

    input_json, expected_json = _eval_payload_for_finding(finding)

    assert input_json["scenario"] == "first_touch_precise_sourced_pi_firm"
    assert "Precise Imaging" in expected_json["must_include"]
    assert "—" in expected_json["must_not_include"]


def test_finding_to_dict_uses_public_field_names():
    finding = ImprovementFindingRow(
        id="find_2",
        finding_key="actions.email_drafts_need_frequent_manual_edits",
        workflow="actions",
        finding_type="draft_quality",
        summary="Drafts edited frequently",
        details="Inspect diffs.",
        evidence_trace_ids=["trace-2"],
        evidence_json={"edited_count": 3},
        severity="normal",
        confidence=60,
        suggested_change_json={"change_type": "diff_cluster_analysis"},
        status="accepted",
    )

    data = finding_to_dict(finding)

    assert data["evidence"] == {"edited_count": 3}
    assert data["suggested_change"] == {"change_type": "diff_cluster_analysis"}
    assert data["status"] == "accepted"


def test_link_event_trace_kwargs_includes_recipient_and_campaign_context():
    event = LinkEventRow(
        id=10,
        send_id=4,
        kind="click",
        url="https://getpossibleminds.com/blog/example",
        ip="203.0.113.4",
        user_agent="Example UA",
        referer="https://mail.example.test",
        ts=datetime(2026, 5, 31, tzinfo=timezone.utc),
    )
    send = OutreachSendRow(
        id=4,
        campaign_id=2,
        contact_id="contact_1",
        pif_id="pif_1",
        recipient_email="lead@example.test",
        recipient_name="Lead Example",
        recipient_title="COO",
        firm_name="Example Law",
        token="token_1",
        status="sent",
        sent_at=datetime(2026, 5, 31, tzinfo=timezone.utc),
        message_id="msg_1",
    )
    campaign = OutreachCampaignRow(
        id=2,
        name="Blog share",
        post_slug="example",
        post_url="https://getpossibleminds.com/blog/example",
        post_title="Example post",
        sender_name="Pranav",
        sender_email="pranav@example.test",
    )

    payload = link_event_trace_kwargs(event, send=send, campaign=campaign)

    assert payload["input_json"]["observed_link"] == "https://getpossibleminds.com/blog/example"
    assert payload["context_json"]["recipient_email"] == "lead@example.test"
    assert payload["context_json"]["recipient_name"] == "Lead Example"
    assert payload["context_json"]["firm_name"] == "Example Law"
    assert payload["context_json"]["campaign_post_title"] == "Example post"
