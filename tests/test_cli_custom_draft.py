from pathlib import Path

import pytest
from typer.testing import CliRunner

from app import cli
from app.cli import _load_custom_draft_inputs


runner = CliRunner()


def test_custom_draft_inputs_preserve_legacy_path_without_options():
    assert _load_custom_draft_inputs(
        subject="",
        body="",
        body_file="",
        draft_file="",
    ) is None


def test_custom_draft_inputs_load_complete_draft_file(tmp_path: Path):
    draft = tmp_path / "draft.txt"
    draft.write_text("Subject: Precise imaging - quick question\n\nHi Khalif,\n\nCustom body.\n", encoding="utf-8")

    assert _load_custom_draft_inputs(
        subject="",
        body="",
        body_file="",
        draft_file=str(draft),
    ) == ("Precise imaging - quick question", "Hi Khalif,\n\nCustom body.")


def test_custom_draft_inputs_load_subject_and_body_file(tmp_path: Path):
    body = tmp_path / "body.txt"
    body.write_text("Hi Wesley,\n\nCustom body.\n", encoding="utf-8")

    assert _load_custom_draft_inputs(
        subject="Custom subject",
        body="",
        body_file=str(body),
        draft_file="",
    ) == ("Custom subject", "Hi Wesley,\n\nCustom body.")


@pytest.mark.parametrize(
    ("subject", "body", "body_file", "draft_file", "message"),
    [
        ("", "body", "", "", "--subject is required"),
        ("subject", "", "", "", "provide --body or --body-file"),
        ("subject", "body", "body.txt", "", "use only one"),
        ("subject", "body", "", "draft.txt", "--draft-file cannot be combined"),
    ],
)
def test_custom_draft_inputs_reject_ambiguous_options(subject, body, body_file, draft_file, message):
    with pytest.raises(ValueError, match=message):
        _load_custom_draft_inputs(
            subject=subject,
            body=body,
            body_file=body_file,
            draft_file=draft_file,
        )


def test_edit_draft_custom_file_bypasses_existing_draft_loader(monkeypatch, tmp_path: Path):
    draft = tmp_path / "draft.txt"
    draft.write_text("Subject: Custom subject\n\nCustom body.\n", encoding="utf-8")
    posted = {}

    def fail_get(*args, **kwargs):
        raise AssertionError("custom draft path must not load a composer draft")

    def capture_post(path, json_body=None, timeout=30.0):
        posted.update({"path": path, "json_body": json_body, "timeout": timeout})
        return {
            "action": {"id": "action_test", "status": "approved"},
            "created": True,
            "updated_existing": False,
            "executed": False,
        }

    monkeypatch.setattr(cli, "_get", fail_get)
    monkeypatch.setattr(cli, "_post", capture_post)

    result = runner.invoke(
        cli.lead_gen_app,
        [
            "edit-draft",
            "item_test",
            "--draft-file",
            str(draft),
            "--actor",
            "codex",
            "--action-type",
            "follow_up",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert posted["path"] == "/api/lead-gen/batch-items/item_test/edit-draft"
    assert posted["json_body"]["subject"] == "Custom subject"
    assert posted["json_body"]["body"] == "Custom body."
    assert posted["json_body"]["lead_gen_action_type"] == "follow_up"
