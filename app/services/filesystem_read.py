"""Structured read-only filesystem inspection for Possible OS agents."""
from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from app.services.product_traces import safe_record_product_trace


REPO_ROOT = Path(os.getenv("POSSIBLE_OS_FS_ROOT", Path(__file__).resolve().parents[2])).resolve()
MAX_READ_BYTES = 50_000
MAX_SEARCH_MATCHES = 100
MAX_LIST_FILES = 200
MAX_GIT_LOG = 20
SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}
SENSITIVE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
}
SENSITIVE_PARTS = {
    "secrets",
    ".ssh",
    ".gnupg",
}
SENSITIVE_SUFFIXES = {
    ".key",
    ".pem",
    ".p12",
    ".pfx",
}


class FilesystemReadError(ValueError):
    """Raised when a read-only filesystem request is rejected by policy."""


def _summary(text: str, *, limit: int = 240) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _safe_rel_path(path: str | None, *, default: str = ".") -> tuple[Path, str]:
    raw = (path or default).strip() or default
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        raise FilesystemReadError("absolute_paths_are_not_allowed")
    if ".." in candidate.parts:
        raise FilesystemReadError("path_traversal_is_not_allowed")
    resolved = (REPO_ROOT / candidate).resolve()
    try:
        rel = resolved.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise FilesystemReadError("path_escapes_repo_root") from exc
    rel_text = "." if str(rel) == "." else rel.as_posix()
    return resolved, rel_text


def _check_sensitive(rel_path: str) -> None:
    path = Path(rel_path)
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}
    if name in SENSITIVE_NAMES:
        raise FilesystemReadError("sensitive_file_blocked")
    if SENSITIVE_PARTS & parts:
        raise FilesystemReadError("sensitive_path_blocked")
    if any(name.endswith(suffix) for suffix in SENSITIVE_SUFFIXES):
        raise FilesystemReadError("sensitive_file_blocked")


def _reject_binary(path: Path) -> None:
    try:
        sample = path.read_bytes()[:4096]
    except OSError as exc:
        raise FilesystemReadError(f"file_read_failed:{type(exc).__name__}") from exc
    if b"\x00" in sample:
        raise FilesystemReadError("binary_file_blocked")
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FilesystemReadError("non_utf8_file_blocked") from exc


def _truncate_text(text: str, max_bytes: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, False
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return truncated, True


def _run_git(args: list[str], *, max_bytes: int) -> dict[str, Any]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )
    output = proc.stdout if proc.returncode == 0 else proc.stderr
    output, truncated = _truncate_text(output, max(1, min(max_bytes, MAX_READ_BYTES)))
    return {
        "returncode": proc.returncode,
        "output": output,
        "truncated": truncated,
        "summary": _summary(output) if output else ("ok" if proc.returncode == 0 else "no output"),
    }


def list_files(*, path: str = ".", pattern: str | None = None, limit: int = MAX_LIST_FILES) -> dict[str, Any]:
    root, rel_root = _safe_rel_path(path)
    _check_sensitive(rel_root)
    if not root.exists():
        raise FilesystemReadError("path_not_found")
    if root.is_file():
        files = [rel_root]
    else:
        files = []
        max_items = max(1, min(limit, 1000))
        for current_root, dir_names, file_names in os.walk(root):
            dir_names[:] = sorted(name for name in dir_names if name not in SKIP_DIRS)
            for file_name in sorted(file_names):
                file_path = Path(current_root) / file_name
                rel = file_path.relative_to(REPO_ROOT).as_posix()
                if pattern and not fnmatch.fnmatch(rel, pattern) and not fnmatch.fnmatch(file_name, pattern):
                    continue
                try:
                    _check_sensitive(rel)
                except FilesystemReadError:
                    continue
                files.append(rel)
                if len(files) >= max_items:
                    break
            if len(files) >= max_items:
                break
    return {
        "operation": "list_files",
        "root": rel_root,
        "files": files,
        "count": len(files),
        "truncated": len(files) >= max(1, min(limit, 1000)),
        "files_touched": [],
        "summary": f"{len(files)} file(s) listed",
    }


def read_file(
    *,
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    max_bytes: int = MAX_READ_BYTES,
) -> dict[str, Any]:
    file_path, rel = _safe_rel_path(path)
    _check_sensitive(rel)
    if not file_path.exists():
        raise FilesystemReadError("file_not_found")
    if not file_path.is_file():
        raise FilesystemReadError("path_is_not_a_file")
    _reject_binary(file_path)
    text = file_path.read_text(encoding="utf-8", errors="strict")
    lines = text.splitlines()
    start = max(1, int(start_line or 1))
    end = int(end_line or len(lines))
    if end < start:
        raise FilesystemReadError("end_line_before_start_line")
    selected = lines[start - 1:end]
    content = "\n".join(f"{idx}|{line}" for idx, line in enumerate(selected, start=start))
    content, truncated = _truncate_text(content, max(1, min(max_bytes, MAX_READ_BYTES)))
    return {
        "operation": "read_file",
        "path": rel,
        "start_line": start,
        "end_line": min(end, len(lines)),
        "total_lines": len(lines),
        "content": content,
        "truncated": truncated,
        "files_touched": [rel],
        "summary": f"read {rel}:{start}-{min(end, len(lines))}",
    }


def search_text(
    *,
    query: str,
    path: str = ".",
    glob: str | None = None,
    limit: int = MAX_SEARCH_MATCHES,
) -> dict[str, Any]:
    if not query:
        raise FilesystemReadError("query_required")
    root, rel_root = _safe_rel_path(path)
    _check_sensitive(rel_root)
    if glob and (".." in Path(glob).parts or glob.startswith("/")):
        raise FilesystemReadError("unsafe_glob")
    if not root.exists():
        raise FilesystemReadError("path_not_found")
    max_matches = max(1, min(limit, MAX_SEARCH_MATCHES))
    cmd = [
        "rg",
        "--fixed-strings",
        "--line-number",
        "--no-heading",
        "--color",
        "never",
        "--hidden",
        "--glob",
        "!{.git,node_modules,.next,.venv,__pycache__,dist,build}/**",
        "--glob",
        "!.env*",
        "--glob",
        "!secrets/**",
        "--glob",
        "!**/secrets/**",
        "--glob",
        "!**/.ssh/**",
    ]
    if glob:
        cmd.extend(["--glob", glob])
    cmd.extend(["--", query, rel_root])
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )
    raw_lines = proc.stdout.splitlines()
    matches: list[dict[str, Any]] = []
    for line in raw_lines[:max_matches]:
        match = re.match(r"^(?P<path>.+?):(?P<line>\d+):(?P<text>.*)$", line)
        if not match:
            continue
        file_part = match.group("path")
        line_no = match.group("line")
        text = match.group("text")
        if not file_part or file_part.isdigit():
            continue
        try:
            _check_sensitive(file_part)
        except FilesystemReadError:
            continue
        matches.append({
            "path": file_part,
            "line": int(line_no) if line_no.isdigit() else None,
            "text": text,
        })
    files_touched = sorted({str(match["path"]) for match in matches})
    return {
        "operation": "search_text",
        "query": query,
        "root": rel_root,
        "matches": matches,
        "count": len(matches),
        "truncated": len(raw_lines) > len(matches),
        "files_touched": files_touched,
        "summary": f"{len(matches)} match(es) for {query!r}",
        "returncode": proc.returncode,
    }


def git_status() -> dict[str, Any]:
    result = _run_git(["status", "--short", "--branch"], max_bytes=MAX_READ_BYTES)
    return {"operation": "git_status", "files_touched": [], **result}


def git_diff(*, path: str | None = None, max_bytes: int = MAX_READ_BYTES) -> dict[str, Any]:
    args = ["diff", "--"]
    files_touched: list[str] = []
    if path:
        resolved, rel = _safe_rel_path(path)
        _check_sensitive(rel)
        args.append(rel)
        if resolved.exists():
            files_touched.append(rel)
    result = _run_git(args, max_bytes=max_bytes)
    return {"operation": "git_diff", "path": path or "", "files_touched": files_touched, **result}


def git_log(*, limit: int = MAX_GIT_LOG) -> dict[str, Any]:
    safe_limit = max(1, min(limit, MAX_GIT_LOG))
    result = _run_git(["log", f"--max-count={safe_limit}", "--pretty=format:%h%x09%ad%x09%s", "--date=short"], max_bytes=MAX_READ_BYTES)
    return {"operation": "git_log", "limit": safe_limit, "files_touched": [], **result}


def git_show(*, ref: str = "HEAD", path: str | None = None, max_bytes: int = MAX_READ_BYTES) -> dict[str, Any]:
    safe_ref = (ref or "HEAD").strip()
    if not safe_ref or any(part in safe_ref for part in [";", "&", "|", "\n", "\r"]):
        raise FilesystemReadError("unsafe_git_ref")
    args = ["show", "--no-ext-diff", "--stat", "--patch", safe_ref]
    files_touched: list[str] = []
    if path:
        resolved, rel = _safe_rel_path(path)
        _check_sensitive(rel)
        args.extend(["--", rel])
        if resolved.exists():
            files_touched.append(rel)
    result = _run_git(args, max_bytes=max_bytes)
    return {"operation": "git_show", "ref": safe_ref, "path": path or "", "files_touched": files_touched, **result}


def execute_filesystem_read(payload: dict[str, Any]) -> dict[str, Any]:
    operation = str(payload.get("operation") or "").strip()
    if operation == "list_files":
        return list_files(
            path=str(payload.get("path") or "."),
            pattern=payload.get("pattern"),
            limit=int(payload.get("limit") or MAX_LIST_FILES),
        )
    if operation == "read_file":
        return read_file(
            path=str(payload.get("path") or ""),
            start_line=payload.get("start_line") or payload.get("start"),
            end_line=payload.get("end_line") or payload.get("end"),
            max_bytes=int(payload.get("max_bytes") or MAX_READ_BYTES),
        )
    if operation == "search_text":
        return search_text(
            query=str(payload.get("query") or ""),
            path=str(payload.get("path") or "."),
            glob=payload.get("glob"),
            limit=int(payload.get("limit") or MAX_SEARCH_MATCHES),
        )
    if operation == "git_status":
        return git_status()
    if operation == "git_diff":
        return git_diff(path=payload.get("path"), max_bytes=int(payload.get("max_bytes") or MAX_READ_BYTES))
    if operation == "git_log":
        return git_log(limit=int(payload.get("limit") or MAX_GIT_LOG))
    if operation == "git_show":
        return git_show(
            ref=str(payload.get("ref") or "HEAD"),
            path=payload.get("path"),
            max_bytes=int(payload.get("max_bytes") or MAX_READ_BYTES),
        )
    raise FilesystemReadError("unsupported_operation")


async def run_filesystem_read(payload: dict[str, Any], *, actor: str = "operator") -> dict[str, Any]:
    result: dict[str, Any]
    try:
        result = execute_filesystem_read(payload)
        await safe_record_product_trace(
            actor_type="agent" if actor == "master-agent" else "user",
            actor_id=actor,
            event_type="filesystem_read_executed",
            surface="filesystem",
            entity_type="filesystem_read",
            entity_id=str(result.get("operation") or "unknown"),
            input_json={k: v for k, v in payload.items() if k != "content"},
            output_json={
                "operation": result.get("operation"),
                "summary": result.get("summary"),
                "truncated": bool(result.get("truncated")),
                "files_touched": result.get("files_touched") or [],
                "count": result.get("count"),
            },
            metadata_json={"repo_root": str(REPO_ROOT), "read_only": True},
        )
        return {"allowed": True, "result": result}
    except FilesystemReadError as exc:
        result = {
            "operation": str(payload.get("operation") or "unknown"),
            "error": str(exc),
            "truncated": False,
            "files_touched": [],
            "summary": f"rejected: {exc}",
        }
        await safe_record_product_trace(
            actor_type="agent" if actor == "master-agent" else "user",
            actor_id=actor,
            event_type="filesystem_read_rejected",
            surface="filesystem",
            entity_type="filesystem_read",
            entity_id=str(payload.get("operation") or "unknown"),
            input_json={k: v for k, v in payload.items() if k != "content"},
            output_json=result,
            metadata_json={"repo_root": str(REPO_ROOT), "read_only": True},
        )
        return {"allowed": False, "result": result}
