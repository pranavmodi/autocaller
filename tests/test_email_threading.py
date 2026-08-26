from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from app import cli
from app.services import email_notification_service
from app.services.action_execution import _update_action_draft_payload


runner = CliRunner()


def test_zoho_api_receives_thread_ancestry(monkeypatch):
    captured = {}
    monkeypatch.setattr(email_notification_service, "_zoho_account_id", lambda: "account-1")
    monkeypatch.setattr(
        email_notification_service,
        "_zoho_request",
        lambda method, path, json_body=None: captured.update(
            {"method": method, "path": path, "payload": json_body}
        ) or {"data": {"messageId": "zoho-message-1"}},
    )

    result = email_notification_service._send_via_zoho_api(
        subject="Re: Quick question",
        body="Following up.",
        from_addr="sender@example.com",
        to="lead@example.com",
        in_reply_to="<original@example.net>",
        references="<root@example.net> <original@example.net>",
    )

    assert result == "zoho-message-1"
    assert captured["payload"]["inReplyTo"] == "<original@example.net>"
    assert captured["payload"]["refHeader"] == "<root@example.net> <original@example.net>"


def test_thread_references_default_to_in_reply_to():
    assert email_notification_service._normalize_thread_headers(
        in_reply_to="<original@example.net>",
    ) == ("<original@example.net>", "<original@example.net>")


@pytest.mark.parametrize("value", ["provider-id", "<bad>", "<one@example.net> <two@example.net>", "x\nBcc: bad@example.net"])
def test_invalid_in_reply_to_is_rejected(value):
    with pytest.raises(RuntimeError, match="in_reply_to_must_be_one_rfc_message_id"):
        email_notification_service._normalize_thread_headers(in_reply_to=value)


def test_updating_scheduled_draft_binds_threading_to_approval():
    action = SimpleNamespace(
        input_json={
            "subject": "Old",
            "body": "Old body",
            "approval": {"approved_by": "operator"},
        },
        approved_by="operator",
        policy_result_json={"allowed": True},
        updated_at=None,
    )

    _update_action_draft_payload(
        action,
        subject="Re: Old",
        body="Following up.",
        actor="operator",
        transport="zoho_api",
        in_reply_to="<original@example.net>",
        references="<original@example.net>",
    )

    assert action.input_json["transport"] == "zoho_api"
    assert action.input_json["in_reply_to"] == "<original@example.net>"
    assert action.input_json["references"] == "<original@example.net>"
    assert action.input_json["approval"]["in_reply_to"] == "<original@example.net>"
    assert action.input_json["approval"]["references"] == "<original@example.net>"
    assert action.policy_result_json == {}


def test_cli_sends_threading_fields_for_approved_draft(monkeypatch):
    posted = {}

    def capture_post(path, json_body=None, timeout=30.0):
        posted.update({"path": path, "json_body": json_body, "timeout": timeout})
        return {"action": {"id": "action-1", "status": "approved"}}

    monkeypatch.setattr(cli, "_post", capture_post)
    result = runner.invoke(
        cli.actions_app,
        [
            "send-approved-lead-gen-draft",
            "--item", "item-1",
            "--subject", "Re: Quick question",
            "--body", "Following up.",
            "--transport", "zoho_api",
            "--in-reply-to", "<original@example.net>",
            "--no-execute",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert posted["json_body"]["in_reply_to"] == "<original@example.net>"
    assert posted["json_body"]["references"] == "<original@example.net>"
    assert posted["json_body"]["transport"] == "zoho_api"
