from typer.testing import CliRunner

from app import cli


runner = CliRunner()


def test_pif_enrich_queues_local_api(monkeypatch):
    calls = []

    def fake_post(path, json_body=None, timeout=30.0):
        calls.append((path, json_body, timeout))
        return {"task_id": "task-1", "status": "queued"}

    monkeypatch.setattr(cli, "_post", fake_post)

    result = runner.invoke(cli.app, ["pif", "enrich", "firm/1"])

    assert result.exit_code == 0
    assert '"task_id": "task-1"' in result.stdout
    assert calls == [("/api/pif/firms/firm%2F1/research", None, 90.0)]
