import pytest

from app.services import sandbox_write
from app.services.sandbox_write import SandboxWriteError, execute_sandbox_write


@pytest.fixture()
def isolated_sandbox(tmp_path, monkeypatch):
    root = tmp_path / "agent-sandbox"
    monkeypatch.setattr(sandbox_write, "SANDBOX_ROOT", root)
    return root


def test_sandbox_write_append_read_list_and_delete(isolated_sandbox):
    write = execute_sandbox_write({
        "operation": "write",
        "path": "notes/master.md",
        "content": "# Master\n",
    })
    assert write["operation"] == "write"
    assert write["path"] == "notes/master.md"
    assert (isolated_sandbox / "notes/master.md").exists()

    append = execute_sandbox_write({
        "operation": "append",
        "path": "notes/master.md",
        "content": "More context.\n",
    })
    assert append["after_bytes"] > append["before_bytes"]

    read = execute_sandbox_write({
        "operation": "read",
        "path": "notes/master.md",
    })
    assert "# Master" in read["content"]
    assert "More context." in read["content"]

    listed = execute_sandbox_write({
        "operation": "list",
        "path": ".",
    })
    assert any(item["path"] == "notes/master.md" for item in listed["items"])

    deleted = execute_sandbox_write({
        "operation": "delete",
        "path": "notes",
    })
    assert deleted["deleted_kind"] == "directory"
    assert not (isolated_sandbox / "notes").exists()


def test_sandbox_rejects_path_traversal(isolated_sandbox):
    with pytest.raises(SandboxWriteError) as exc:
        execute_sandbox_write({
            "operation": "write",
            "path": "../outside.md",
            "content": "nope",
        })

    assert str(exc.value) == "path_traversal_is_not_allowed"


def test_sandbox_rejects_symlink_write_escape(isolated_sandbox):
    isolated_sandbox.mkdir(parents=True)
    outside = isolated_sandbox.parent / "outside"
    outside.mkdir()
    (isolated_sandbox / "link").symlink_to(outside)

    with pytest.raises(SandboxWriteError) as exc:
        execute_sandbox_write({
            "operation": "write",
            "path": "link/file.md",
            "content": "nope",
        })

    assert str(exc.value) in {
        "path_escapes_sandbox_root",
        "symlink_path_blocked",
    }
