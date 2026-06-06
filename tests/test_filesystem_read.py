import pytest

from app.services.filesystem_read import FilesystemReadError, execute_filesystem_read, read_file


def test_read_file_returns_line_numbered_content():
    result = read_file(path="app/services/master_agent.py", start_line=1, end_line=3)

    assert result["operation"] == "read_file"
    assert result["path"] == "app/services/master_agent.py"
    assert result["files_touched"] == ["app/services/master_agent.py"]
    assert "1|" in result["content"]


def test_search_text_is_structured_and_bounded():
    result = execute_filesystem_read({
        "operation": "search_text",
        "query": "_build_wake_context",
        "path": "app/services",
        "limit": 5,
    })

    assert result["operation"] == "search_text"
    assert result["count"] >= 1
    assert len(result["matches"]) <= 5
    assert any(match["path"] == "app/services/master_agent.py" for match in result["matches"])


def test_policy_rejects_path_traversal():
    with pytest.raises(FilesystemReadError) as exc:
        execute_filesystem_read({
            "operation": "read_file",
            "path": "../autocaller/app/services/master_agent.py",
        })

    assert str(exc.value) == "path_traversal_is_not_allowed"


def test_policy_rejects_sensitive_files():
    with pytest.raises(FilesystemReadError) as exc:
        execute_filesystem_read({
            "operation": "read_file",
            "path": ".env",
        })

    assert str(exc.value) == "sensitive_file_blocked"


def test_policy_rejects_raw_shell_as_unsupported_operation():
    with pytest.raises(FilesystemReadError) as exc:
        execute_filesystem_read({
            "command": "cat app/services/master_agent.py && rm -rf /",
        })

    assert str(exc.value) == "unsupported_operation"
