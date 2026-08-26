from typer.testing import CliRunner

from app import cli


runner = CliRunner()


def test_research_job_postings_queues_through_local_api(monkeypatch):
    calls = []

    def fake_post(path, json_body=None, timeout=30.0):
        calls.append((path, json_body, timeout))
        return {"task_id": "task-1", "status": "queued"}

    monkeypatch.setattr(cli, "_post", fake_post)

    result = runner.invoke(cli.app, ["pif", "research-job-postings", "firm/1"])

    assert result.exit_code == 0
    assert '"task_id": "task-1"' in result.stdout
    assert calls == [
        ("/api/pif/firms/firm%2F1/research-job-postings", None, 90.0),
    ]


def test_pif_research_status_uses_proxied_status_endpoint(monkeypatch):
    calls = []

    def fake_get(path, **params):
        calls.append((path, params))
        return {"task_id": "task/1", "status": "completed"}

    monkeypatch.setattr(cli, "_get", fake_get)

    result = runner.invoke(cli.app, ["pif", "research-status", "task/1"])

    assert result.exit_code == 0
    assert '"status": "completed"' in result.stdout
    assert calls == [("/api/pif/research-status/task%2F1", {})]


def test_research_job_postings_can_poll_until_complete(monkeypatch):
    monkeypatch.setattr(
        cli,
        "_post",
        lambda *args, **kwargs: {"task_id": "task-1", "status": "queued"},
    )
    monkeypatch.setattr(
        cli,
        "_get",
        lambda *args, **kwargs: {"task_id": "task-1", "status": "completed"},
    )

    result = runner.invoke(
        cli.app,
        ["pif", "research-job-postings", "firm-1", "--poll"],
    )

    assert result.exit_code == 0
    assert '"status": "completed"' in result.stdout
