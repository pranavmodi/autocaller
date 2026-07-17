import json
import os
import subprocess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import data_returned as data_returned_api
from app.api.data_returned import router as data_returned_router
from app.services.data_returned import build_data_returned_script, save_data_returned_script


def test_script_endpoint_returns_current_shell_script(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://possible.example")
    async def fake_load(callback_url):
        return {
            "script": build_data_returned_script(callback_url),
            "customized": False,
            "updated_at": None,
        }

    monkeypatch.setattr(data_returned_api, "load_data_returned_script", fake_load)
    app = FastAPI()
    app.include_router(data_returned_router)
    client = TestClient(app)

    response = client.get("/datareturned/script")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/x-shellscript")
    assert response.headers["cache-control"] == "no-store"
    assert response.text.startswith("#!/usr/bin/env bash\n")
    assert "environment variables" in response.text
    assert response.text.rstrip().endswith("https://possible.example/datareturned")
    assert response.text.rfind("curl --fail") > response.text.rfind("uname -a")


def test_script_save_endpoint_persists_exact_text(monkeypatch):
    saved_script = "#!/usr/bin/env bash\nprintf 'custom\\n'\n"

    async def fake_save(script):
        assert script == saved_script
        return {"script": script, "customized": True, "updated_at": "2026-07-17T00:00:00+00:00"}

    monkeypatch.setattr(data_returned_api, "save_data_returned_script", fake_save)
    app = FastAPI()
    app.include_router(data_returned_router)
    client = TestClient(app)

    response = client.put("/api/datareturned/script", json={"script": saved_script})

    assert response.status_code == 200
    assert response.json()["script"] == saved_script
    assert response.json()["customized"] is True


@pytest.mark.asyncio
async def test_saved_script_rejects_whitespace_only_content():
    with pytest.raises(ValueError, match="cannot be empty"):
        await save_data_returned_script("  \n")


def test_generated_script_posts_json_encoded_output_with_final_curl(tmp_path):
    fake_curl = tmp_path / "curl"
    fake_curl.write_text(
        """#!/usr/bin/env bash
while (($#)); do
  if [[ "$1" == "--data-binary" ]]; then
    shift
    printf '%s' "$1"
    exit 0
  fi
  shift
done
exit 2
""",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)

    script = build_data_returned_script("https://possible.example/datareturned")
    completed = subprocess.run(
        ["bash", "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
    )

    payload = json.loads(completed.stdout)
    assert payload["source"] == "possibleos-datareturned-script"
    assert payload["script_version"] == 1
    assert "timestamp_utc=" in payload["output"]
    assert "whoami=" in payload["output"]
    assert "identity=" in payload["output"]
    assert "working_directory=" in payload["output"]
    assert "kernel=" in payload["output"]


def test_generated_script_rejects_non_http_callback():
    try:
        build_data_returned_script("file:///tmp/result")
    except ValueError as exc:
        assert "HTTP(S)" in str(exc)
    else:
        raise AssertionError("non-HTTP callback should be rejected")
