"""Bounded writable sandbox for Possible OS agents."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from app.services.product_traces import safe_record_product_trace


REPO_ROOT = Path(os.getenv("POSSIBLE_OS_FS_ROOT", Path(__file__).resolve().parents[2])).resolve()
SANDBOX_ROOT = Path(os.getenv("POSSIBLE_OS_AGENT_SANDBOX_ROOT", REPO_ROOT / "data/agent-sandbox")).resolve()
MAX_WRITE_BYTES = 100_000
MAX_READ_BYTES = 50_000
MAX_LIST_ITEMS = 500


class SandboxWriteError(ValueError):
    """Raised when a sandbox mutation request is rejected by policy."""


def _summary(text: str, *, limit: int = 240) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _truncate_text(text: str, max_bytes: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, False
    return encoded[:max_bytes].decode("utf-8", errors="ignore"), True


def _safe_rel_path(path: str | None, *, default: str = ".") -> tuple[Path, str]:
    raw = (path or default).strip() or default
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        raise SandboxWriteError("absolute_paths_are_not_allowed")
    if ".." in candidate.parts:
        raise SandboxWriteError("path_traversal_is_not_allowed")
    resolved = (SANDBOX_ROOT / candidate).resolve(strict=False)
    try:
        rel = resolved.relative_to(SANDBOX_ROOT)
    except ValueError as exc:
        raise SandboxWriteError("path_escapes_sandbox_root") from exc
    rel_text = "." if str(rel) == "." else rel.as_posix()
    return resolved, rel_text


def _ensure_sandbox_root() -> None:
    SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
    if not SANDBOX_ROOT.is_dir():
        raise SandboxWriteError("sandbox_root_not_directory")


def _reject_symlink_ancestors(path: Path) -> None:
    _ensure_sandbox_root()
    current = SANDBOX_ROOT
    try:
        relative_parts = path.relative_to(SANDBOX_ROOT).parts
    except ValueError as exc:
        raise SandboxWriteError("path_escapes_sandbox_root") from exc
    for part in relative_parts[:-1]:
        current = current / part
        if current.exists() and current.is_symlink():
            raise SandboxWriteError("symlink_path_blocked")


def _reject_binary(path: Path) -> None:
    try:
        sample = path.read_bytes()[:4096]
    except OSError as exc:
        raise SandboxWriteError(f"file_read_failed:{type(exc).__name__}") from exc
    if b"\x00" in sample:
        raise SandboxWriteError("binary_file_blocked")
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SandboxWriteError("non_utf8_file_blocked") from exc


def list_sandbox(*, path: str = ".", recursive: bool = True, limit: int = MAX_LIST_ITEMS) -> dict[str, Any]:
    _ensure_sandbox_root()
    root, rel_root = _safe_rel_path(path)
    _reject_symlink_ancestors(root)
    if not root.exists():
        raise SandboxWriteError("path_not_found")
    safe_limit = max(1, min(int(limit), MAX_LIST_ITEMS))
    items: list[dict[str, Any]] = []
    if root.is_file() or root.is_symlink():
        stat = root.lstat()
        items.append({
            "path": rel_root,
            "kind": "symlink" if root.is_symlink() else "file",
            "bytes": stat.st_size,
        })
    else:
        if recursive:
            walker = os.walk(root)
            for current_root, dir_names, file_names in walker:
                dir_names[:] = sorted(dir_names)
                for name in [*dir_names, *sorted(file_names)]:
                    item = Path(current_root) / name
                    rel = item.relative_to(SANDBOX_ROOT).as_posix()
                    stat = item.lstat()
                    items.append({
                        "path": rel,
                        "kind": "symlink" if item.is_symlink() else ("directory" if item.is_dir() else "file"),
                        "bytes": stat.st_size,
                    })
                    if len(items) >= safe_limit:
                        break
                if len(items) >= safe_limit:
                    break
        else:
            for item in sorted(root.iterdir(), key=lambda p: p.name)[:safe_limit]:
                stat = item.lstat()
                items.append({
                    "path": item.relative_to(SANDBOX_ROOT).as_posix(),
                    "kind": "symlink" if item.is_symlink() else ("directory" if item.is_dir() else "file"),
                    "bytes": stat.st_size,
                })
    return {
        "operation": "list",
        "sandbox_root": str(SANDBOX_ROOT),
        "root": rel_root,
        "items": items,
        "count": len(items),
        "truncated": len(items) >= safe_limit,
        "files_touched": [],
        "summary": f"{len(items)} sandbox item(s) listed",
    }


def read_sandbox_file(*, path: str, max_bytes: int = MAX_READ_BYTES) -> dict[str, Any]:
    _ensure_sandbox_root()
    file_path, rel = _safe_rel_path(path)
    _reject_symlink_ancestors(file_path)
    if not file_path.exists():
        raise SandboxWriteError("file_not_found")
    if file_path.is_symlink():
        raise SandboxWriteError("symlink_file_blocked")
    if not file_path.is_file():
        raise SandboxWriteError("path_is_not_a_file")
    _reject_binary(file_path)
    text = file_path.read_text(encoding="utf-8", errors="strict")
    content, truncated = _truncate_text(text, max(1, min(int(max_bytes), MAX_READ_BYTES)))
    return {
        "operation": "read",
        "path": rel,
        "content": content,
        "truncated": truncated,
        "files_touched": [rel],
        "summary": f"read sandbox file {rel}",
    }


def write_sandbox_file(*, path: str, content: str, append: bool = False) -> dict[str, Any]:
    _ensure_sandbox_root()
    encoded = str(content or "").encode("utf-8")
    if len(encoded) > MAX_WRITE_BYTES:
        raise SandboxWriteError("content_too_large")
    file_path, rel = _safe_rel_path(path)
    if rel == ".":
        raise SandboxWriteError("file_path_required")
    _reject_symlink_ancestors(file_path)
    if file_path.exists() and file_path.is_symlink():
        raise SandboxWriteError("symlink_file_blocked")
    if file_path.exists() and file_path.is_dir():
        raise SandboxWriteError("path_is_directory")
    file_path.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_ancestors(file_path)
    mode = "a" if append else "w"
    before_bytes = file_path.stat().st_size if file_path.exists() else 0
    with file_path.open(mode, encoding="utf-8") as handle:
        handle.write(str(content or ""))
    after_bytes = file_path.stat().st_size
    operation = "append" if append else "write"
    return {
        "operation": operation,
        "path": rel,
        "bytes_written": len(encoded),
        "before_bytes": before_bytes,
        "after_bytes": after_bytes,
        "truncated": False,
        "files_touched": [rel],
        "summary": f"{operation} sandbox file {rel}",
    }


def mkdir_sandbox(*, path: str) -> dict[str, Any]:
    _ensure_sandbox_root()
    dir_path, rel = _safe_rel_path(path)
    if rel == ".":
        raise SandboxWriteError("directory_path_required")
    _reject_symlink_ancestors(dir_path)
    if dir_path.exists() and dir_path.is_symlink():
        raise SandboxWriteError("symlink_path_blocked")
    if dir_path.exists() and not dir_path.is_dir():
        raise SandboxWriteError("path_is_not_directory")
    dir_path.mkdir(parents=True, exist_ok=True)
    return {
        "operation": "mkdir",
        "path": rel,
        "truncated": False,
        "files_touched": [rel],
        "summary": f"created sandbox directory {rel}",
    }


def delete_sandbox_path(*, path: str) -> dict[str, Any]:
    _ensure_sandbox_root()
    target, rel = _safe_rel_path(path)
    if rel == ".":
        raise SandboxWriteError("cannot_delete_sandbox_root")
    _reject_symlink_ancestors(target)
    if not target.exists() and not target.is_symlink():
        raise SandboxWriteError("path_not_found")
    kind = "symlink" if target.is_symlink() else ("directory" if target.is_dir() else "file")
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)
    return {
        "operation": "delete",
        "path": rel,
        "deleted_kind": kind,
        "truncated": False,
        "files_touched": [rel],
        "summary": f"deleted sandbox {kind} {rel}",
    }


def execute_sandbox_write(payload: dict[str, Any]) -> dict[str, Any]:
    operation = str(payload.get("operation") or "").strip()
    if operation == "list":
        return list_sandbox(
            path=str(payload.get("path") or "."),
            recursive=bool(payload.get("recursive", True)),
            limit=int(payload.get("limit") or MAX_LIST_ITEMS),
        )
    if operation == "read":
        return read_sandbox_file(
            path=str(payload.get("path") or ""),
            max_bytes=int(payload.get("max_bytes") or MAX_READ_BYTES),
        )
    if operation == "write":
        return write_sandbox_file(
            path=str(payload.get("path") or ""),
            content=str(payload.get("content") or ""),
            append=False,
        )
    if operation == "append":
        return write_sandbox_file(
            path=str(payload.get("path") or ""),
            content=str(payload.get("content") or ""),
            append=True,
        )
    if operation == "mkdir":
        return mkdir_sandbox(path=str(payload.get("path") or ""))
    if operation == "delete":
        return delete_sandbox_path(path=str(payload.get("path") or ""))
    raise SandboxWriteError("unsupported_operation")


async def run_sandbox_write(payload: dict[str, Any], *, actor: str = "master-agent") -> dict[str, Any]:
    try:
        result = execute_sandbox_write(payload)
        await safe_record_product_trace(
            actor_type="agent" if actor == "master-agent" else "user",
            actor_id=actor,
            event_type="sandbox_write_executed",
            surface="agents",
            entity_type="agent_sandbox",
            entity_id=str(result.get("path") or result.get("operation") or "unknown"),
            input_json={k: v for k, v in payload.items() if k != "content"},
            output_json={
                "operation": result.get("operation"),
                "summary": result.get("summary"),
                "path": result.get("path"),
                "files_touched": result.get("files_touched") or [],
                "count": result.get("count"),
                "bytes_written": result.get("bytes_written"),
            },
            metadata_json={"sandbox_root": str(SANDBOX_ROOT), "bounded_write": True},
        )
        return {"allowed": True, "result": result}
    except SandboxWriteError as exc:
        result = {
            "operation": str(payload.get("operation") or "unknown"),
            "error": str(exc),
            "summary": f"rejected: {exc}",
            "truncated": False,
            "files_touched": [],
        }
        await safe_record_product_trace(
            actor_type="agent" if actor == "master-agent" else "user",
            actor_id=actor,
            event_type="sandbox_write_rejected",
            surface="agents",
            entity_type="agent_sandbox",
            entity_id=str(payload.get("path") or payload.get("operation") or "unknown"),
            input_json={k: v for k, v in payload.items() if k != "content"},
            output_json=result,
            metadata_json={"sandbox_root": str(SANDBOX_ROOT), "bounded_write": True},
        )
        return {"allowed": False, "result": result}
