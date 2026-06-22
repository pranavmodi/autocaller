"""Bridge PossibleOS lead-gen items to the AI Visibility CLI/report payload."""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.db.models import FirmCompetitiveFeatureRow, FirmContactRow, LeadGenBatchItemRow, PifFirmRow


DEFAULT_AIVIS_CLI = "/home/pranav/ai-visibility/bin/aivis"
DEFAULT_MARKET = "Los Angeles, CA"
DEFAULT_PRACTICE = "auto accidents"


def normalize_domain(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = parsed.netloc or parsed.path.split("/", 1)[0]
    return host.removeprefix("www.")


def email_domain(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if "@" not in raw:
        return ""
    return normalize_domain(raw.rsplit("@", 1)[-1])


def compact_visibility_report(report: dict[str, Any]) -> dict[str, Any]:
    meta = report.get("meta") if isinstance(report.get("meta"), dict) else {}
    variants = report.get("email_variants") if isinstance(report.get("email_variants"), list) else []
    one_pager = report.get("one_pager") if isinstance(report.get("one_pager"), dict) else {}
    compact_variants = []
    for variant in variants[:2]:
        if not isinstance(variant, dict):
            continue
        compact_variants.append(
            {
                "name": variant.get("name"),
                "subject": variant.get("subject"),
                "body": variant.get("body"),
                "gates": variant.get("gates") or {},
                "merge_fields": variant.get("merge_fields") or {},
            }
        )
    return {
        "scan_id": report.get("scan_id") or meta.get("scan_id"),
        "report_url": meta.get("report_url"),
        "firm_name": meta.get("firm_name"),
        "domain": meta.get("domain"),
        "market": meta.get("market"),
        "practice": meta.get("practice"),
        "email_variants": compact_variants,
        "ranked_email_facts": (report.get("ranked_email_facts") or [])[:6],
        "entity_split": report.get("entity_split") or {},
        "estimate": {
            "email_case_band": ((report.get("estimate") or {}).get("email_case_band") or {}),
        },
        "engine_coverage": report.get("engine_coverage") or {},
        "one_pager": {
            "title": one_pager.get("title"),
            "summary": one_pager.get("summary") or [],
            "measured_inputs": (one_pager.get("measured_inputs") or [])[:12],
            "modeled_inputs": (one_pager.get("modeled_inputs") or [])[:12],
        },
        "source": "ai_visibility",
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


async def ensure_visibility_report_for_batch_item(
    batch_item_id: str,
    *,
    dry_run: bool = False,
    force: bool = False,
    aivis_cli: str | None = None,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        item = await session.get(LeadGenBatchItemRow, batch_item_id)
        if item is None:
            raise ValueError("batch_item_not_found")
        contact = await session.get(FirmContactRow, item.contact_id)
        pif = await session.get(PifFirmRow, item.pif_id) if item.pif_id else None
        features = await session.get(FirmCompetitiveFeatureRow, item.pif_id) if item.pif_id else None
        reason = dict(item.reason_json or {})

    existing = reason.get("ai_visibility_report")
    if existing and not force:
        return {"status": "cached_on_batch_item", "batch_item_id": batch_item_id, "report": existing}

    firm_name = item.firm_name or (pif.firm_name if pif else "") or ""
    domain = normalize_domain((pif.website if pif else None) or (features.domain if features else None))
    if not domain and contact:
        domain = email_domain(contact.email)
    market = _infer_market(pif=pif, features=features)
    report_result = ensure_visibility_report(
        firm_name=firm_name,
        domain=domain,
        market=market,
        practice=DEFAULT_PRACTICE,
        dry_run=dry_run,
        force=force,
        aivis_cli=aivis_cli,
    )
    compact = compact_visibility_report(report_result["report"])
    compact["bridge_status"] = report_result["status"]

    async with AsyncSessionLocal() as session:
        row = await session.get(LeadGenBatchItemRow, batch_item_id)
        if row is None:
            raise ValueError("batch_item_not_found")
        next_reason = dict(row.reason_json or {})
        next_reason["ai_visibility_report"] = compact
        next_reason["ai_visibility_report_scan_id"] = compact.get("scan_id")
        next_reason["next_operator_action"] = "compose_visibility_report_email"
        row.reason_json = next_reason
        await session.commit()

    return {"status": "stored_on_batch_item", "batch_item_id": batch_item_id, "report": compact}


def ensure_visibility_report(
    *,
    firm_name: str,
    domain: str,
    market: str,
    practice: str = DEFAULT_PRACTICE,
    dry_run: bool = False,
    force: bool = False,
    aivis_cli: str | None = None,
) -> dict[str, Any]:
    firm_name = (firm_name or "").strip()
    domain = normalize_domain(domain)
    market = (market or os.getenv("AI_VISIBILITY_DEFAULT_MARKET") or DEFAULT_MARKET).strip()
    practice = (practice or DEFAULT_PRACTICE).strip()
    if not firm_name:
        raise ValueError("firm_name_required")
    if not domain:
        raise ValueError("domain_required")
    cli = aivis_cli or os.getenv("AI_VISIBILITY_CLI") or DEFAULT_AIVIS_CLI

    if not force:
        existing = find_existing_visibility_report(domain=domain, firm_name=firm_name, aivis_cli=cli)
        if existing:
            return {"status": "existing", "report": existing}

    scan_args = [
        "scan",
        "--firm-name",
        firm_name,
        "--domain",
        domain,
        "--market",
        market,
        "--practice",
        practice,
        "--source",
        "outbound_email",
    ]
    if dry_run:
        scan_args.append("--dry-run")
    scan_stdout = _run_aivis_text(cli, scan_args, timeout=1800)
    scan_id = _scan_id_from_stdout(scan_stdout)
    if not scan_id:
        raise RuntimeError("ai_visibility_scan_id_not_found")
    report = _run_aivis_json(cli, ["report", scan_id], timeout=300)
    return {"status": "generated", "scan_id": scan_id, "report": report}


def find_existing_visibility_report(
    *,
    domain: str,
    firm_name: str | None = None,
    aivis_cli: str | None = None,
    limit: int = 50,
) -> dict[str, Any] | None:
    cli = aivis_cli or os.getenv("AI_VISIBILITY_CLI") or DEFAULT_AIVIS_CLI
    wanted_domain = normalize_domain(domain)
    wanted_name = _normalize_name(firm_name)
    if wanted_domain:
        try:
            return _run_aivis_json(cli, ["report-for-domain", wanted_domain], timeout=300)
        except RuntimeError as exc:
            if "No scanned report found" not in str(exc):
                raise
    payload = _run_aivis_json(cli, ["reports", "--status", "scanned", "--limit", str(limit)], timeout=300)
    for report in payload.get("reports") or []:
        if not isinstance(report, dict):
            continue
        meta = report.get("meta") if isinstance(report.get("meta"), dict) else {}
        if wanted_domain and normalize_domain(str(meta.get("domain") or "")) == wanted_domain:
            return report
        if wanted_name and _normalize_name(str(meta.get("firm_name") or "")) == wanted_name:
            return report
    return None


async def batch_item_visibility_report(batch_item_id: str) -> dict[str, Any] | None:
    async with AsyncSessionLocal() as session:
        item = await session.get(LeadGenBatchItemRow, batch_item_id)
        if item is None:
            return None
        report = (item.reason_json or {}).get("ai_visibility_report")
        return report if isinstance(report, dict) else None


def _infer_market(*, pif: PifFirmRow | None, features: FirmCompetitiveFeatureRow | None) -> str:
    if features and features.city:
        return f"{features.city}, {features.state or 'CA'}".strip().strip(",")
    if pif:
        for address in pif.addresses or []:
            if not isinstance(address, dict):
                continue
            city = str(address.get("city") or address.get("locality") or "").strip()
            state = str(address.get("state") or address.get("region") or "").strip()
            if city:
                return f"{city}, {state or 'CA'}".strip().strip(",")
    return os.getenv("AI_VISIBILITY_DEFAULT_MARKET", DEFAULT_MARKET)


def _scan_id_from_stdout(stdout: str) -> str | None:
    for line in stdout.splitlines():
        match = re.search(r"Created scan:\s*([a-f0-9]{16,64})", line.strip(), re.IGNORECASE)
        if match:
            return match.group(1)
    match = re.search(r"\b([a-f0-9]{32})\b", stdout, re.IGNORECASE)
    return match.group(1) if match else None


def _normalize_name(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _run_aivis_text(cli: str, args: list[str], *, timeout: int) -> str:
    cli_path = Path(cli).expanduser()
    cwd = str(cli_path.resolve().parents[1]) if cli_path.exists() else None
    env = os.environ.copy()
    if os.getenv("AI_VISIBILITY_DB_PATH"):
        env["DB_PATH"] = os.getenv("AI_VISIBILITY_DB_PATH", "")
    else:
        env.pop("DB_PATH", None)
    proc = subprocess.run(
        [cli, *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
        cwd=cwd,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"ai_visibility_cli_failed: {' '.join(args)}: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout


def _run_aivis_json(cli: str, args: list[str], *, timeout: int) -> dict[str, Any]:
    stdout = _run_aivis_text(cli, args, timeout=timeout)
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ai_visibility_cli_non_json: {' '.join(args)}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"ai_visibility_cli_unexpected_json: {' '.join(args)}")
    return parsed
