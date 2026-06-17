"""Possible OS CLI — headless ops over the FastAPI backend + DB.

The CLI is a thin client: call-related commands talk to the running FastAPI
daemon on loopback, while bulk-lead and config commands touch the DB / .env
directly. Uses Typer for arg parsing + Rich for tabular output.

Entry point: `python -m app.cli <command>` or `bin/possibleos <command>`.
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

import httpx
import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    help="Headless Possible OS CLI — cold-call PI attorneys via Twilio + OpenAI + Cal.com.",
    add_completion=False,
    no_args_is_help=True,
)

leads_app = typer.Typer(help="Manage leads (import, list, show, add, remove, sync-mission)", no_args_is_help=True)
calls_app = typer.Typer(help="Inspect call history + transcripts + judge", no_args_is_help=True)
dispatcher_app = typer.Typer(help="Control the auto-dispatcher", no_args_is_help=True)
config_app = typer.Typer(help="Config / .env wizard + inspection", no_args_is_help=True)
system_app = typer.Typer(help="Global on/off — master kill switch", no_args_is_help=True)
mock_app = typer.Typer(help="Mock-mode toggle (redirect all Twilio calls to a mock phone)", no_args_is_help=True)
allowlist_app = typer.Typer(help="Manage allowed_phones (phone allowlist)", no_args_is_help=True)
followups_app = typer.Typer(help="GTM follow-up queue — calls awaiting action", no_args_is_help=True)
voice_app = typer.Typer(help="Switch between realtime voice backends (openai | gemini)", no_args_is_help=True)
ivr_app = typer.Typer(help="Phone-tree (IVR) navigation — press digits to reach a human", no_args_is_help=True)
carrier_app = typer.Typer(help="Inspect the active telephony carrier account (Twilio)", no_args_is_help=True)
prompts_app = typer.Typer(help="Prompt-style selector (current | minimal). Parallel prompt versions.", no_args_is_help=True)
email_app = typer.Typer(help="Outbound email — config check + manual sends (test, one-pager, VM follow-up, consult).", no_args_is_help=True)
pif_app = typer.Typer(help="Native PI-firm directory — pull emailtag's pif-info into possibleos (replaces mission.db).", no_args_is_help=True)
reviews_app = typer.Typer(help="Yelp-review extraction — turn pasted raw reviews into citable pain-point quotes.", no_args_is_help=True)
decisions_app = typer.Typer(help="Append/read the repo decision log (docs/decisions/<UTC-date>.md). Format: docs/decisions/README.md.", no_args_is_help=True)
comms_app = typer.Typer(help="Outbound communications dashboard — calls, voicemails, SMS, emails (read-only).", no_args_is_help=True)
contacts_app = typer.Typer(help="Per-firm contact roster (backfill from PIF Stats + patients).", no_args_is_help=True)
front_app = typer.Typer(help="Front read-only enrichment sync and warm lead signals.", no_args_is_help=True)
front_competitors_app = typer.Typer(help="Local firm-vs-firm PI competition graph.", no_args_is_help=True)
research_app = typer.Typer(help="PIF Stats firm research orchestration.", no_args_is_help=True)
personas_app = typer.Typer(help="Map and inspect PI firm contact personas.", no_args_is_help=True)
composer_ab_app = typer.Typer(help="Composer A/B experiment — variants, assignment, report.", no_args_is_help=True)
sequences_app = typer.Typer(help="Email sequences — preview, start, and recommend contacts.", no_args_is_help=True)
lead_gen_app = typer.Typer(help="Cybernetic lead-generation loop — batches, feedback, learning.", no_args_is_help=True)
lead_gen_observations_app = typer.Typer(
    help="List and summarize automatic lead-generation observations.",
    no_args_is_help=False,
)
inbound_app = typer.Typer(help="Inbound email ingestion — Zoho IMAP reader for replies.", no_args_is_help=True)
outreach_app = typer.Typer(help="Blog-post outreach campaigns — LLM-composed, per-recipient, tracked.", no_args_is_help=True)
todos_app = typer.Typer(help="Editable project todo backlog.", no_args_is_help=True)
ideas_app = typer.Typer(help="Simple future product, marketing, and GTM idea capture.", no_args_is_help=True)
agents_app = typer.Typer(help="Possible OS master-agent heartbeat and subagent tasks.", no_args_is_help=True)
actions_app = typer.Typer(help="Durable Possible OS action execution queue.", no_args_is_help=True)
fs_app = typer.Typer(help="Read-only repo filesystem inspection for Possible OS agents.", no_args_is_help=True)
listening_app = typer.Typer(help="Mission Control listening brief, insights, sources, and prep.", no_args_is_help=True)
outreach_campaigns_app = typer.Typer(help="Create / list / show outreach campaigns.", no_args_is_help=True)
outreach_audience_app = typer.Typer(help="Build a campaign's recipient list from firm contacts.", no_args_is_help=True)
outreach_app.add_typer(outreach_campaigns_app, name="campaigns")
outreach_app.add_typer(outreach_audience_app, name="audience")
lead_gen_app.add_typer(lead_gen_observations_app, name="observations")
front_app.add_typer(front_competitors_app, name="competitors")

app.add_typer(leads_app, name="leads")
app.add_typer(calls_app, name="calls")
app.add_typer(dispatcher_app, name="dispatcher")
app.add_typer(config_app, name="config")
app.add_typer(system_app, name="system")
app.add_typer(mock_app, name="mock")
app.add_typer(allowlist_app, name="allowlist")
app.add_typer(followups_app, name="followups")
app.add_typer(voice_app, name="voice")
app.add_typer(ivr_app, name="ivr")
app.add_typer(carrier_app, name="carrier")
app.add_typer(prompts_app, name="prompts")
app.add_typer(email_app, name="email")
app.add_typer(pif_app, name="pif")
app.add_typer(reviews_app, name="reviews")
app.add_typer(decisions_app, name="decisions")
app.add_typer(comms_app, name="comms")
app.add_typer(contacts_app, name="contacts")
app.add_typer(front_app, name="front")
app.add_typer(research_app, name="research")
app.add_typer(personas_app, name="personas")
app.add_typer(composer_ab_app, name="composer-ab")
app.add_typer(sequences_app, name="sequences")
app.add_typer(lead_gen_app, name="lead-gen")
app.add_typer(inbound_app, name="inbound")
app.add_typer(outreach_app, name="outreach")
app.add_typer(todos_app, name="todos")
app.add_typer(ideas_app, name="ideas")
app.add_typer(agents_app, name="agents")
app.add_typer(actions_app, name="actions")
app.add_typer(fs_app, name="fs")
app.add_typer(listening_app, name="listening")

console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _api_base() -> str:
    """Base URL of the FastAPI daemon (loopback by default)."""
    port = os.getenv("BACKEND_PORT", "8000").strip() or "8000"
    return (
        os.getenv("POSSIBLEOS_API_BASE")
        or os.getenv("AUTOCALLER_API_BASE")
        or f"http://127.0.0.1:{port}"
    ).rstrip("/")


def _http_error_detail(exc: httpx.HTTPError) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            payload = exc.response.json()
        except Exception:
            payload = {}
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if detail:
            return f"{exc.response.status_code} {detail}"
    return str(exc)


def _get(path: str, **params) -> dict:
    try:
        resp = httpx.get(f"{_api_base()}{path}", params=params or None, timeout=15.0)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        console.print(f"[red]API request failed: {_http_error_detail(e)}[/red]")
        raise typer.Exit(code=1) from e
    return resp.json()


def _post(path: str, json_body: Optional[dict] = None, timeout: float = 30.0) -> dict:
    try:
        resp = httpx.post(f"{_api_base()}{path}", json=json_body or {}, timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        console.print(f"[red]API request failed: {_http_error_detail(e)}[/red]")
        raise typer.Exit(code=1) from e
    return resp.json() if resp.content else {}


def _parse_editor_draft(raw: str) -> tuple[str, str]:
    lines = raw.splitlines()
    if not lines:
        raise ValueError("draft file is empty")
    first = lines[0]
    if not first.lower().startswith("subject:"):
        raise ValueError("first line must be 'Subject: ...'")
    subject = first.split(":", 1)[1].strip()
    body_lines = lines[1:]
    if body_lines and body_lines[0].strip() == "":
        body_lines = body_lines[1:]
    body = "\n".join(body_lines).strip()
    if not subject:
        raise ValueError("subject cannot be empty")
    if not body:
        raise ValueError("body cannot be empty")
    return subject, body


def _edit_subject_body(subject: str, body: str, *, use_editor: bool) -> tuple[str, str]:
    if not use_editor:
        return subject, body
    editor = os.getenv("EDITOR", "").strip() or "vi"
    with tempfile.NamedTemporaryFile("w+", prefix="lead-gen-draft-", suffix=".txt", encoding="utf-8") as tmp:
        tmp.write(f"Subject: {subject.strip()}\n\n{body.strip()}\n")
        tmp.flush()
        try:
            subprocess.run([*shlex.split(editor), tmp.name], check=True)
        except FileNotFoundError as exc:
            console.print(f"[red]Editor not found: {editor}[/red]")
            raise typer.Exit(code=1) from exc
        except subprocess.CalledProcessError as exc:
            console.print(f"[red]Editor exited with status {exc.returncode}[/red]")
            raise typer.Exit(code=1) from exc
        tmp.seek(0)
        try:
            return _parse_editor_draft(tmp.read())
        except ValueError as exc:
            console.print(f"[red]Invalid draft file: {exc}[/red]")
            raise typer.Exit(code=1) from exc


def _patch(path: str, json_body: Optional[dict] = None, timeout: float = 30.0) -> dict:
    try:
        resp = httpx.patch(f"{_api_base()}{path}", json=json_body or {}, timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        console.print(f"[red]API request failed: {_http_error_detail(e)}[/red]")
        raise typer.Exit(code=1) from e
    return resp.json() if resp.content else {}


def _run_fs_payload(payload: dict, *, actor: str = "operator") -> dict:
    from app.services.filesystem_read import run_filesystem_read

    return asyncio.run(run_filesystem_read(payload, actor=actor))


def _run_sandbox_payload(payload: dict, *, actor: str = "operator") -> dict:
    from app.services.sandbox_write import run_sandbox_write

    return asyncio.run(run_sandbox_write(payload, actor=actor))


def _print_fs_result(data: dict, *, json_output: bool) -> None:
    if json_output:
        console.print_json(data=data)
        return
    result = data.get("result") or {}
    if not data.get("allowed"):
        console.print(f"[red]rejected[/red] {result.get('error') or result.get('summary') or 'request rejected'}")
        return
    operation = result.get("operation") or "filesystem_read"
    console.print(f"[green]{operation}[/green] {result.get('summary') or ''}")
    if "files" in result:
        for path in result.get("files") or []:
            console.print(path)
    elif "matches" in result:
        for match in result.get("matches") or []:
            console.print(f"{match.get('path')}:{match.get('line')}: {match.get('text')}")
    elif "content" in result:
        console.print(result.get("content") or "")
    elif "output" in result:
        console.print(result.get("output") or "")


def _print_sandbox_result(data: dict, *, json_output: bool) -> None:
    if json_output:
        console.print_json(data=data)
        return
    result = data.get("result") or {}
    if not data.get("allowed"):
        console.print(f"[red]rejected[/red] {result.get('error') or result.get('summary') or 'request rejected'}")
        return
    operation = result.get("operation") or "sandbox"
    console.print(f"[green]{operation}[/green] {result.get('summary') or ''}")
    if "items" in result:
        for item in result.get("items") or []:
            console.print(f"{item.get('kind', ''):9} {item.get('path')} {item.get('bytes', '')}")
    elif "content" in result:
        console.print(result.get("content") or "")


def _delete(path: str, timeout: float = 30.0) -> dict:
    try:
        resp = httpx.delete(f"{_api_base()}{path}", timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        console.print(f"[red]API request failed: {e}[/red]")
        raise typer.Exit(code=1) from e
    return resp.json() if resp.content else {}


def _run(coro):
    """Run an async coroutine to completion for DB-direct CLI commands."""
    return asyncio.run(coro)


def _mask_email(value: str | None) -> str:
    raw = (value or "").strip()
    if "@" not in raw:
        return raw or "—"
    local, domain = raw.split("@", 1)
    return f"{local[:2]}***@{domain}"


def _phone_normalize(raw: str) -> str:
    """Normalize to E.164. Drops extensions, rejects malformed lengths."""
    s = (raw or "").strip()
    # Split off extension markers so 'x', 'ext', ',' don't contaminate digits.
    s = re.split(r"(?i)\s*(?:x|ext\.?|,|;)\s*", s, maxsplit=1)[0]
    digits = re.sub(r"\D", "", s)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    # Non-US international, already in E.164-ish form
    if s.startswith("+") and 8 <= len(digits) <= 15:
        return f"+{digits}"
    return ""


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------

@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Host to bind to"),
    port: int = typer.Option(lambda: int(os.getenv("BACKEND_PORT", "8000")), help="Port to bind to"),
    reload: bool = typer.Option(False, help="Dev auto-reload"),
):
    """Start the FastAPI daemon (foreground)."""
    import uvicorn
    log_level = "warning" if not reload else "info"
    uvicorn.run("app.main:app", host=host, port=port, reload=reload, log_level=log_level)


# ---------------------------------------------------------------------------
# leads
# ---------------------------------------------------------------------------

_REQUIRED_LEAD_COLS = {"phone", "name"}


@leads_app.command("import")
def leads_import(
    csv_path: Path = typer.Argument(..., exists=True, readable=True, help="CSV file with leads"),
    source: str = typer.Option("csv", help="Source tag stored on each imported row"),
    dry_run: bool = typer.Option(False, help="Parse + validate, don't write to DB"),
):
    """Bulk-import leads from CSV. Required columns: phone, name. Optional: firm, state,
    practice_area, email, title, website, tags (pipe-separated), notes."""
    rows = list(csv.DictReader(csv_path.open(newline="", encoding="utf-8")))
    if not rows:
        console.print("[yellow]CSV is empty[/yellow]")
        raise typer.Exit(code=1)

    headers_lower = {(h or "").strip().lower() for h in rows[0].keys()}
    missing = _REQUIRED_LEAD_COLS - headers_lower
    if missing:
        console.print(f"[red]Missing required columns: {sorted(missing)}[/red]")
        raise typer.Exit(code=1)

    parsed: list[dict] = []
    skipped = 0
    for i, raw in enumerate(rows, start=1):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        phone = _phone_normalize(row.get("phone", ""))
        name = row.get("name", "")
        if not phone or not name:
            skipped += 1
            continue
        tags_field = row.get("tags", "")
        tags = [t.strip() for t in tags_field.split("|") if t.strip()] if tags_field else []
        parsed.append({
            "patient_id": row.get("id") or row.get("lead_id") or f"LEAD-{i:06d}",
            "name": name,
            "phone": phone,
            "firm_name": row.get("firm") or row.get("firm_name") or None,
            "state": (row.get("state") or "").upper()[:2] or None,
            "practice_area": row.get("practice_area") or None,
            "email": row.get("email") or None,
            "title": row.get("title") or None,
            "website": row.get("website") or None,
            "source": row.get("source") or source,
            "tags": tags,
            "notes": row.get("notes") or None,
        })

    console.print(f"Parsed {len(parsed)} valid rows, skipped {skipped}.")
    if dry_run:
        console.print("[cyan]--dry-run: no DB writes performed[/cyan]")
        return

    async def _insert():
        from app.db import AsyncSessionLocal
        from app.db.models import PatientRow
        from sqlalchemy import select
        inserted = 0
        updated = 0
        async with AsyncSessionLocal() as session:
            for r in parsed:
                existing = await session.execute(
                    select(PatientRow).where(PatientRow.patient_id == r["patient_id"])
                )
                row_obj = existing.scalar_one_or_none()
                if row_obj:
                    for k, v in r.items():
                        if k == "patient_id":
                            continue
                        setattr(row_obj, k, v)
                    updated += 1
                else:
                    session.add(PatientRow(**r))
                    inserted += 1
            await session.commit()
        return inserted, updated

    inserted, updated = _run(_insert())
    console.print(f"[green]Imported {inserted} new, updated {updated}.[/green]")


@leads_app.command("list")
def leads_list(
    state: Optional[str] = typer.Option(None, help="Filter by 2-letter state"),
    language: Optional[str] = typer.Option(None, "--language", help="Filter by language (en|es)"),
    limit: int = typer.Option(50, help="Max rows to display"),
):
    """List leads."""
    async def _query():
        from app.db import AsyncSessionLocal
        from app.db.models import PatientRow
        from sqlalchemy import select
        async with AsyncSessionLocal() as session:
            stmt = select(PatientRow)
            if state:
                stmt = stmt.where(PatientRow.state == state.upper())
            if language:
                stmt = stmt.where(PatientRow.language == language.strip().lower())
            stmt = stmt.order_by(PatientRow.priority_bucket, PatientRow.updated_at.desc()).limit(limit)
            res = await session.execute(stmt)
            return list(res.scalars().all())

    leads = _run(_query())
    table = Table(title=f"Leads ({len(leads)})")
    for col in ["id", "name", "firm", "state", "lang", "phone", "title", "attempts", "last_outcome"]:
        table.add_column(col, overflow="fold")
    for l in leads:
        table.add_row(
            str(l.patient_id),
            l.name or "",
            l.firm_name or "",
            l.state or "",
            l.language or "",
            l.phone or "",
            l.title or "",
            str(l.attempt_count),
            l.last_outcome or "",
        )
    console.print(table)


@leads_app.command("retry")
def leads_retry(
    lead_id: str = typer.Argument(..., help="Lead / patient_id to queue for immediate retry"),
):
    """Clear the cooldown on a lead so the dispatcher picks it up on its
    next tick. Use after a call you want to redial without waiting for
    `min_hours_between` to elapse (default is 1 week)."""
    resp = _post(f"/api/patients/{lead_id}/retry")
    console.print_json(data=resp)


@leads_app.command("set-language")
def leads_set_language(
    lead_id: str = typer.Argument(..., help="Lead / patient_id"),
    language: str = typer.Argument(..., help="'en' or 'es'"),
):
    """Set the outbound-call language for a lead (controls which prompt
    template + first-word seed the AI uses)."""
    lang = language.strip().lower()
    if lang not in ("en", "es"):
        console.print("[red]language must be 'en' or 'es'[/red]")
        raise typer.Exit(code=2)
    async def _update():
        from app.db import AsyncSessionLocal
        from app.db.models import PatientRow
        from sqlalchemy import select
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(PatientRow).where(PatientRow.patient_id == lead_id)
            )
            row = res.scalar_one_or_none()
            if not row:
                return None
            row.language = lang
            await session.commit()
            return row
    row = _run(_update())
    if not row:
        console.print(f"[red]lead not found: {lead_id}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]✓[/green] {lead_id} language → {lang} ({row.name})")


@leads_app.command("show")
def leads_show(lead_id: str = typer.Argument(...)):
    """Show full detail on a single lead."""
    async def _q():
        from app.db import AsyncSessionLocal
        from app.db.models import PatientRow
        from sqlalchemy import select
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(PatientRow).where(PatientRow.patient_id == lead_id))
            return res.scalar_one_or_none()

    lead = _run(_q())
    if not lead:
        console.print(f"[red]Lead not found: {lead_id}[/red]")
        raise typer.Exit(code=1)
    data = {
        "id": lead.patient_id,
        "name": lead.name,
        "firm": lead.firm_name,
        "state": lead.state,
        "phone": lead.phone,
        "email": lead.email,
        "title": lead.title,
        "practice_area": lead.practice_area,
        "website": lead.website,
        "tags": lead.tags,
        "notes": lead.notes,
        "attempt_count": lead.attempt_count,
        "last_outcome": lead.last_outcome,
        "last_attempt_at": lead.last_attempt_at.isoformat() if lead.last_attempt_at else None,
        "priority_bucket": lead.priority_bucket,
    }
    console.print_json(data=data)


@leads_app.command("add")
def leads_add(
    name: str = typer.Option(...),
    phone: str = typer.Option(...),
    firm: Optional[str] = typer.Option(None),
    state: Optional[str] = typer.Option(None),
    email: Optional[str] = typer.Option(None),
    title: Optional[str] = typer.Option(None),
    practice_area: str = typer.Option("personal injury"),
):
    """Add a single lead."""
    phone_norm = _phone_normalize(phone)
    if not phone_norm:
        console.print("[red]Invalid phone[/red]")
        raise typer.Exit(code=1)

    async def _add():
        from app.db import AsyncSessionLocal
        from app.db.models import PatientRow
        import uuid
        lead_id = f"LEAD-{uuid.uuid4().hex[:10].upper()}"
        async with AsyncSessionLocal() as session:
            session.add(PatientRow(
                patient_id=lead_id,
                name=name,
                phone=phone_norm,
                firm_name=firm,
                state=(state or "").upper()[:2] or None,
                email=email,
                title=title,
                practice_area=practice_area,
                source="cli",
                tags=[],
            ))
            await session.commit()
        return lead_id

    lead_id = _run(_add())
    console.print(f"[green]Added lead {lead_id}[/green]")


_MISSION_API = os.getenv(
    "MISSION_CONTROL_API",
    "https://mission.getpossibleminds.com",
).rstrip("/")

# Titles that typically indicate a gatekeeper / non-decision-maker. We skip these
# by default so Possible OS starts on actual partners/owners.
def _best_phone(firm: dict, contact: Optional[dict]) -> str:
    """Fallback phone picker used when the LLM extraction fails."""
    if contact and contact.get("phone"):
        return _phone_normalize(contact["phone"])
    phones = firm.get("phones") or []
    for p in phones:
        norm = _phone_normalize(p)
        if norm:
            return norm
    return ""


def _best_email(firm: dict, contact: Optional[dict]) -> str:
    if contact and contact.get("email"):
        return str(contact["email"]).strip().lower()
    emails = firm.get("emails") or []
    return str(emails[0]).strip().lower() if emails else ""


@leads_app.command("sync-mission")
def leads_sync_mission(
    tiers: str = typer.Option("A,B", "--tiers", help="Comma-sep ICP tiers (A, B, C, or 'all')"),
    dm_threshold: int = typer.Option(
        5,
        "--dm-threshold",
        help="Minimum decision_maker_confidence (0-10) to keep. Default 5 = at least associate attorney.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Extract + report only, no DB writes"),
    limit: int = typer.Option(500, "--limit", help="Stop after N firms"),
    page_size: int = typer.Option(100, "--page-size"),
    concurrency: int = typer.Option(10, "--concurrency", help="Parallel LLM calls"),
    extractor_model: str = typer.Option(
        None,
        "--extractor-model",
        help="LLM for lead extraction (default: LEAD_EXTRACTOR_MODEL env or gpt-4o-mini)",
    ),
):
    """Pull PI firm contacts from Mission Control and upsert them as leads.

    An LLM (gpt-4o-mini by default) reads each raw firm record, picks the
    best contact to call, normalizes the phone to E.164, extracts the state,
    and scores decision-maker likelihood. No regex — the LLM handles messy
    titles, extensions, and address formats.

    Leads are keyed by `mc-{pif_id}` for idempotent re-sync.
    """
    from app.services.lead_extractor import extract_leads_batch, DEFAULT_MODEL

    wanted_tiers = None if tiers.lower() == "all" else [
        t.strip().upper() for t in tiers.split(",") if t.strip()
    ]
    model = extractor_model or DEFAULT_MODEL

    # Step 1: fetch raw firms from Mission Control
    async def _fetch_all() -> list[dict]:
        import httpx
        out: list[dict] = []
        async with httpx.AsyncClient(timeout=30.0) as cli:
            tier_list = wanted_tiers or [None]
            for tier in tier_list:
                page = 1
                while len(out) < limit:
                    params = {"page": page, "page_size": page_size}
                    if tier:
                        params["tier"] = tier
                    r = await cli.get(f"{_MISSION_API}/api/pif-local/firms", params=params)
                    r.raise_for_status()
                    data = r.json()
                    items = data.get("items") or []
                    if not items:
                        break
                    out.extend(items)
                    if page >= data.get("total_pages", 1):
                        break
                    page += 1
                    if len(out) >= limit:
                        break
        return out[:limit]

    firms = _run(_fetch_all())
    console.print(f"Fetched {len(firms)} firms from Mission Control (tiers={tiers!r}).")

    if not firms:
        console.print("[yellow]No firms matched.[/yellow]")
        return

    # Step 2: LLM extraction, batched with bounded concurrency
    console.print(
        f"Running LLM extractor ([bold]{model}[/bold], concurrency={concurrency}) "
        f"— estimated cost ≈ ${len(firms) * 0.0008:.2f}"
    )

    progress_state = {"done": 0, "total": len(firms)}

    def _on_progress(done: int, total: int):
        # Only print every 25 items to avoid log noise in large syncs.
        if done % 25 == 0 or done == total:
            console.print(f"  extracted {done}/{total}")

    extracted = _run(extract_leads_batch(
        firms,
        model=model,
        concurrency=concurrency,
        on_progress=_on_progress,
    ))

    # Step 3: filter + shape into PatientRow fields
    by_firm = {f.get("id"): f for f in firms}
    rows: list[dict] = []
    skipped_unusable = 0
    skipped_dm = 0

    for firm, lead in zip(firms, extracted):
        if not lead.usable or not lead.phone_e164:
            skipped_unusable += 1
            continue
        if lead.decision_maker_confidence < dm_threshold:
            skipped_dm += 1
            continue

        pif_id = firm.get("id") or ""
        icp_tier = firm.get("icp_tier")
        tags = [f"tier:{icp_tier}"] if icp_tier else []
        tags.append(f"dm:{lead.decision_maker_confidence}")
        if lead.is_decision_maker:
            tags.append("decision-maker")

        rows.append({
            "patient_id": f"mc-{pif_id}",
            "name": lead.name,
            "phone": lead.phone_e164,
            "firm_name": lead.firm_name or None,
            "state": lead.state,
            "practice_area": lead.practice_area,
            "email": lead.email,
            "title": lead.title,
            "website": lead.website,
            "source": "mission-control",
            "tags": tags,
            "notes": lead.notes,
            "name_is_person": lead.name_is_person,
            "_dm_confidence": lead.decision_maker_confidence,  # dropped before insert
        })

    console.print(
        f"Extractor results: [green]{len(rows)} kept[/green]  "
        f"(skipped: {skipped_unusable} unreachable, {skipped_dm} below DM threshold={dm_threshold})"
    )

    if dry_run:
        for r in rows[:15]:
            conf = r["_dm_confidence"]
            color = "green" if conf >= 8 else "yellow" if conf >= 5 else "red"
            console.print(
                f"  [{color}]dm={conf:>2}[/{color}]  {r['name'][:24]:24s}  "
                f"{(r.get('title') or '—')[:28]:28s}  "
                f"{(r['firm_name'] or '—')[:30]:30s}  "
                f"{r['state'] or '  ':2s}  {r['phone']}"
            )
        if len(rows) > 15:
            console.print(f"  … and {len(rows) - 15} more")
        console.print("[cyan]--dry-run: no DB writes[/cyan]")
        return

    # Step 4: upsert
    async def _upsert():
        from app.db import AsyncSessionLocal
        from app.db.models import PatientRow
        from sqlalchemy import select
        ins, upd = 0, 0
        async with AsyncSessionLocal() as session:
            for lead in rows:
                persistable = {k: v for k, v in lead.items() if not k.startswith("_")}
                existing = await session.execute(
                    select(PatientRow).where(PatientRow.patient_id == persistable["patient_id"])
                )
                row_obj = existing.scalar_one_or_none()
                if row_obj:
                    for k, v in persistable.items():
                        if k == "patient_id":
                            continue
                        setattr(row_obj, k, v)
                    upd += 1
                else:
                    session.add(PatientRow(**persistable))
                    ins += 1
            await session.commit()
        return ins, upd

    ins, upd = _run(_upsert())
    console.print(f"[green]Inserted {ins}, updated {upd}.[/green]")


@leads_app.command("backfill-names")
def leads_backfill_names(
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """Classify all leads: is the name a real person or a firm/brand?

    Uses gpt-4o-mini to judge each lead where name_is_person has not been
    explicitly set (defaults to true). Updates the DB so render_system_prompt
    uses 'the managing partner' instead of a firm name as a person.
    """
    async def _backfill():
        import json as _json
        from app.db import AsyncSessionLocal
        from app.db.models import PatientRow
        from sqlalchemy import select
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(PatientRow))
            rows = list(result.scalars().all())

        console.print(f"Classifying {len(rows)} leads...")

        sem = asyncio.Semaphore(15)
        updates: list[tuple[str, bool]] = []

        async def _classify(pid: str, name: str, firm: str, title: str):
            async with sem:
                try:
                    resp = await client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": "You classify whether a name is a real person or a firm/brand. Reply with JSON: {\"is_person\": true/false}."},
                            {"role": "user", "content": _json.dumps({"name": name, "firm_name": firm, "title": title or ""})},
                        ],
                        response_format={"type": "json_object"},
                        temperature=0,
                    )
                    data = _json.loads(resp.choices[0].message.content or "{}")
                    return pid, bool(data.get("is_person", True))
                except Exception as e:
                    logger.warning("classify failed for %s: %s", pid, e)
                    return pid, True

        tasks = [
            _classify(r.patient_id, r.name, r.firm_name or "", getattr(r, "title", "") or "")
            for r in rows
        ]
        results = await asyncio.gather(*tasks)

        changed = 0
        for pid, is_person in results:
            if not is_person:
                updates.append((pid, is_person))
                changed += 1

        console.print(f"Results: {changed} leads are firm/brand names (not persons)")
        for pid, _ in updates[:20]:
            row = next((r for r in rows if r.patient_id == pid), None)
            if row:
                console.print(f"  [yellow]✗ not a person[/yellow]: {row.name} @ {row.firm_name or '—'}")
        if len(updates) > 20:
            console.print(f"  … and {len(updates) - 20} more")

        if dry_run:
            console.print("[cyan]--dry-run: no DB writes[/cyan]")
            return changed

        async with AsyncSessionLocal() as session:
            for pid, is_person in updates:
                result = await session.execute(
                    select(PatientRow).where(PatientRow.patient_id == pid)
                )
                row = result.scalar_one_or_none()
                if row:
                    row.name_is_person = is_person
            await session.commit()
        console.print(f"[green]Updated {changed} leads.[/green]")
        return changed

    _run(_backfill())


@leads_app.command("remove")
def leads_remove(lead_id: str = typer.Argument(...)):
    """Delete a lead."""
    async def _del():
        from app.db import AsyncSessionLocal
        from app.db.models import PatientRow
        from sqlalchemy import delete
        async with AsyncSessionLocal() as session:
            await session.execute(delete(PatientRow).where(PatientRow.patient_id == lead_id))
            await session.commit()

    _run(_del())
    console.print(f"[green]Removed {lead_id}[/green]")


# ---------------------------------------------------------------------------
# call (manual, single-shot)
# ---------------------------------------------------------------------------

@app.command()
def call(
    lead_id: str = typer.Argument(..., help="Lead ID to call now"),
    mode: str = typer.Option("twilio", help="'twilio' (real PSTN) or 'web'"),
    voice: str = typer.Option(
        "", "--voice",
        help="Override voice backend for this call: 'openai' | 'gemini'. "
             "Default uses the DB setting or VOICE_PROVIDER env.",
    ),
    carrier: str = typer.Option(
        "", "--carrier",
        help="Override telephony carrier for this call: 'twilio' | 'telnyx'. "
             "Default uses the DB default_carrier setting.",
    ),
    persona: str = typer.Option(
        "", "--persona",
        help="Voice persona: 'alex' (male) | 'natalia' (female). Default: alex.",
    ),
):
    """Place a call immediately to a lead (bypasses dispatcher)."""
    body: dict = {"patient_id": lead_id, "mode": mode}
    v = (voice or "").strip().lower()
    if v:
        if v not in ("openai", "gemini"):
            console.print(f"[red]--voice must be 'openai' or 'gemini' (got {voice!r})[/red]")
            raise typer.Exit(code=2)
        body["voice_provider"] = v
    c = (carrier or "").strip().lower()
    if c:
        if c not in ("twilio", "telnyx"):
            console.print(f"[red]--carrier must be 'twilio' or 'telnyx' (got {carrier!r})[/red]")
            raise typer.Exit(code=2)
        body["carrier"] = c
    p = (persona or "").strip().lower()
    if p:
        if p not in ("alex", "natalia"):
            console.print(f"[red]--persona must be 'alex' or 'natalia' (got {persona!r})[/red]")
            raise typer.Exit(code=2)
        body["persona"] = p
    resp = _post("/api/call/start", body)
    console.print_json(data=resp)


# ---------------------------------------------------------------------------
# dispatcher
# ---------------------------------------------------------------------------

@dispatcher_app.command("start")
def dispatcher_start():
    resp = _post("/api/dispatcher/toggle", {"enabled": True})
    console.print_json(data=resp)


@dispatcher_app.command("stop")
def dispatcher_stop():
    resp = _post("/api/dispatcher/toggle", {"enabled": False})
    console.print_json(data=resp)


@dispatcher_app.command("status")
def dispatcher_status():
    resp = _get("/api/dispatcher/status")
    console.print_json(data=resp)


@dispatcher_app.command("batch")
def dispatcher_batch(
    count: int = typer.Argument(..., help="Number of calls to place before auto-stop"),
):
    """Start the dispatcher with a hard stop after N calls."""
    if count <= 0:
        console.print("[red]count must be a positive integer[/red]")
        raise typer.Exit(code=2)
    resp = _post("/api/dispatcher/start-batch", {"count": count})
    console.print_json(data=resp)


@dispatcher_app.command("clear-active")
def dispatcher_clear_active():
    """Hang up the live Twilio call (if any) and clear the active-call marker."""
    resp = _post("/api/calls/clear-active")
    console.print_json(data=resp)


@dispatcher_app.command("cooldown")
def dispatcher_cooldown(
    seconds: Optional[int] = typer.Argument(
        None,
        help="Inter-call cooldown in seconds. Omit to just show the current value.",
    ),
):
    """Get or set the wait time the dispatcher enforces between consecutive calls."""
    if seconds is None:
        s = _get("/api/settings")
        current = int((s.get("dispatcher_settings") or {}).get("cooldown_seconds", 0))
        console.print(f"cooldown_seconds = {current}")
        return
    if seconds < 0:
        console.print("[red]seconds must be >= 0[/red]")
        raise typer.Exit(code=2)
    s = _put("/api/settings/dispatcher/cooldown", {"cooldown_seconds": seconds})
    new_val = int((s.get("dispatcher_settings") or {}).get("cooldown_seconds", 0))
    console.print(f"[green]✓[/green] cooldown_seconds = {new_val}")


@dispatcher_app.command("batch-size")
def dispatcher_batch_size(
    size: Optional[int] = typer.Argument(
        None,
        help="Default batch size. Omit to show the current value.",
    ),
):
    """Get or set the default batch size for dispatcher batches."""
    if size is None:
        s = _get("/api/settings")
        current = int((s.get("dispatcher_settings") or {}).get("default_batch_size", 5))
        console.print(f"default_batch_size = {current}")
        return
    if size < 1:
        console.print("[red]size must be >= 1[/red]")
        raise typer.Exit(code=2)
    s = _put("/api/settings/dispatcher/batch-size", {"batch_size": size})
    new_val = int((s.get("dispatcher_settings") or {}).get("default_batch_size", 5))
    console.print(f"[green]✓[/green] default_batch_size = {new_val}")


# ---------------------------------------------------------------------------
# calls (history + transcript + export)
# ---------------------------------------------------------------------------

@calls_app.command("list")
def calls_list(
    limit: int = typer.Option(25, help="Max rows"),
    outcome: Optional[str] = typer.Option(None, help="Filter by outcome"),
    provider: Optional[str] = typer.Option(
        None, "--provider",
        help="Filter by voice backend: 'openai' | 'gemini'",
    ),
    carrier: Optional[str] = typer.Option(
        None, "--carrier",
        help="Filter by telephony carrier: 'twilio' | 'telnyx'",
    ),
):
    """List recent calls."""
    async def _q():
        from app.db import AsyncSessionLocal
        from app.db.models import CallLogRow
        from sqlalchemy import select, desc
        async with AsyncSessionLocal() as session:
            stmt = select(CallLogRow).order_by(desc(CallLogRow.started_at)).limit(limit)
            if outcome:
                stmt = stmt.where(CallLogRow.outcome == outcome)
            if provider:
                stmt = stmt.where(CallLogRow.voice_provider == provider.strip().lower())
            if carrier:
                stmt = stmt.where(CallLogRow.carrier == carrier.strip().lower())
            res = await session.execute(stmt)
            return list(res.scalars().all())

    rows = _run(_q())
    table = Table(title=f"Recent calls ({len(rows)})")
    for col in ["call_id", "lead", "firm", "state", "outcome", "dur_s", "carrier", "voice", "model", "interest", "demo_id", "started"]:
        table.add_column(col, overflow="fold")
    for r in rows:
        table.add_row(
            r.call_id[:10],
            (r.patient_name or "")[:28],
            (r.firm_name or "")[:28],
            r.lead_state or "",
            r.outcome,
            str(r.duration_seconds),
            (getattr(r, "carrier", None) or "")[:8],
            r.voice_provider or "",
            (r.voice_model or "")[:24],
            str(r.interest_level or ""),
            (r.demo_booking_id or "")[:12],
            r.started_at.strftime("%Y-%m-%d %H:%M") if r.started_at else "",
        )
    console.print(table)


@calls_app.command("show")
def calls_show(call_id: str = typer.Argument(...)):
    """Show full detail on a single call."""
    async def _q():
        from app.db import AsyncSessionLocal
        from app.db.models import CallLogRow
        from sqlalchemy import select
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(CallLogRow).where(CallLogRow.call_id == call_id))
            return res.scalar_one_or_none()

    row = _run(_q())
    if not row:
        console.print(f"[red]Call not found: {call_id}[/red]")
        raise typer.Exit(code=1)
    data = {
        "call_id": row.call_id,
        "patient_id": row.patient_id,
        "patient_name": row.patient_name,
        "firm_name": row.firm_name,
        "state": row.lead_state,
        "outcome": row.outcome,
        "call_status": row.call_status,
        "call_disposition": row.call_disposition,
        "duration_seconds": row.duration_seconds,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        "interest_level": row.interest_level,
        "is_decision_maker": row.is_decision_maker,
        "was_gatekeeper": row.was_gatekeeper,
        "gatekeeper_contact": row.gatekeeper_contact,
        "pain_point_summary": row.pain_point_summary,
        "demo_booking_id": row.demo_booking_id,
        "demo_scheduled_at": row.demo_scheduled_at.isoformat() if row.demo_scheduled_at else None,
        "demo_meeting_url": row.demo_meeting_url,
        "followup_email_sent": row.followup_email_sent,
        "recording_path": row.recording_path,
        "error_code": row.error_code,
        "error_message": row.error_message,
    }
    console.print_json(data=data)


@calls_app.command("transcript")
def calls_transcript(call_id: str = typer.Argument(...)):
    """Print the conversation transcript."""
    async def _q():
        from app.db import AsyncSessionLocal
        from app.db.models import CallLogRow
        from sqlalchemy import select
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(CallLogRow).where(CallLogRow.call_id == call_id))
            return res.scalar_one_or_none()

    row = _run(_q())
    if not row:
        console.print(f"[red]Call not found[/red]")
        raise typer.Exit(code=1)
    for t in row.transcript or []:
        speaker = t.get("speaker", "?")
        text = t.get("text", "")
        console.print(f"[bold]{speaker}[/bold]: {text}")


@calls_app.command("judge")
def calls_judge(
    call_id: Optional[str] = typer.Argument(None, help="Call to judge, or omit + use --all-pending"),
    all_pending: bool = typer.Option(False, "--all-pending", help="Backfill every un-judged completed call"),
):
    """Run (or re-run) the LLM judge on a call. Scores it 0-10 and assigns a GTM disposition."""
    if all_pending:
        async def _pending():
            from app.db import AsyncSessionLocal
            from app.db.models import CallLogRow
            from sqlalchemy import select
            async with AsyncSessionLocal() as s:
                r = await s.execute(
                    select(CallLogRow.call_id)
                    .where(CallLogRow.ended_at.is_not(None))
                    .where(CallLogRow.judged_at.is_(None))
                )
                return [row[0] for row in r.all()]
        ids = _run(_pending())
        if not ids:
            console.print("[green]Nothing to judge.[/green]")
            return
        console.print(f"Judging {len(ids)} pending calls (est. cost ~${len(ids) * 0.02:.2f})…")
        for i, cid in enumerate(ids, 1):
            try:
                r = _post(f"/api/calls/{cid}/judge")
                console.print(f"  [{i}/{len(ids)}] {cid[:8]} → score={r.get('judge_score')} disposition={r.get('gtm_disposition')}")
            except typer.Exit:
                console.print(f"  [{i}/{len(ids)}] {cid[:8]} — failed")
        return
    if not call_id:
        console.print("[red]pass either <call_id> or --all-pending[/red]")
        raise typer.Exit(code=2)
    r = _post(f"/api/calls/{call_id}/judge")
    console.print_json(data=r)


@calls_app.command("takeover")
def calls_takeover(
    call_id: str = typer.Argument(..., help="ID of the live call to take over / release"),
    off: bool = typer.Option(False, "--off", help="Release — hand the call back to the AI"),
):
    """Flip human-takeover on a live call. Mutes AI, accepts operator mic via the UI.

    Only useful mid-call: pair with the UI's Listen + mic button. This CLI
    command flips the server-side flag only; the browser still owns the mic.
    """
    r = _post(f"/api/calls/{call_id}/takeover", {"enabled": not off})
    console.print_json(data=r)


@calls_app.command("force-hangup")
def calls_force_hangup(
    call_id: str = typer.Argument(..., help="Call ID (not the carrier SID)"),
):
    """Force the carrier to hang up a call, via the carrier REST API.

    Looks up the row's carrier_call_sid and fires the async hangup with
    retry. Use when the DB thinks a call is ended but the carrier still
    has a live leg (the reconciler catches this within ~60s on its own;
    this command bypasses the wait).
    """
    r = _post(f"/api/calls/{call_id}/force-hangup")
    console.print_json(data=r)


@calls_app.command("reconcile")
def calls_reconcile(
    window_hours: int = typer.Option(
        0, "--window-hours", "-w",
        help="Only sweep rows whose started_at is within this many hours. "
             "0 (default) = sweep all pending orphans regardless of age.",
    ),
):
    """Run one pass of the carrier-state reconciler on demand.

    Loads every call_log row whose termination_state is non-terminal
    and asks the carrier what it currently thinks of each one. Stamps
    ended_at / force-hangs-up as needed. Returns per-row action summary.
    """
    payload = {"window_hours": window_hours} if window_hours else {}
    path = "/api/calls/reconcile"
    if window_hours:
        path = f"{path}?window_hours={window_hours}"
    r = _post(path, payload if payload else None)
    summary = {k: v for k, v in r.items() if k != "details"}
    console.print_json(data=summary)
    details = r.get("details") or []
    if details:
        console.print("[bold]Per-row actions (first 50):[/bold]")
        for d in details:
            console.print(
                f"  {d['call_id'][:8]}  {d['action']:28}  {d.get('detail','')[:80]}"
            )


@calls_app.command("dtmf")
def calls_dtmf(
    call_id: str = typer.Argument(..., help="ID of the live call"),
    digits: str = typer.Argument(..., help='DTMF sequence to send, e.g. "701" or "*123#"'),
    enable_manual: bool = typer.Option(
        False, "--enable-manual",
        help="First flip manual-IVR mode on (required before DTMF is accepted)",
    ),
):
    """Send an operator DTMF sequence on a live call.

    Multi-digit input is batched: "701" streams 7, 0, 1 with 80ms
    inter-digit gaps so the phone tree registers the whole string
    as one input. Requires manual-IVR mode to be on first — pass
    --enable-manual to flip it for you.
    """
    if enable_manual:
        r = _post(f"/api/calls/{call_id}/manual-ivr", {"enabled": True})
        console.print(f"[dim]manual-ivr → {r.get('manual_ivr_active')}[/dim]")
    r = _post(f"/api/calls/{call_id}/dtmf", {"digits": digits})
    console.print_json(data=r)


@calls_app.command("export")
def calls_export(
    output: Path = typer.Option(Path("calls_export.csv"), "--output", "-o"),
    outcome: Optional[str] = typer.Option(None),
    limit: int = typer.Option(1000),
):
    """Export calls to CSV for CRM import."""
    async def _q():
        from app.db import AsyncSessionLocal
        from app.db.models import CallLogRow
        from sqlalchemy import select, desc
        async with AsyncSessionLocal() as session:
            stmt = select(CallLogRow).order_by(desc(CallLogRow.started_at)).limit(limit)
            if outcome:
                stmt = stmt.where(CallLogRow.outcome == outcome)
            res = await session.execute(stmt)
            return list(res.scalars().all())

    rows = _run(_q())
    cols = [
        "call_id", "patient_id", "patient_name", "firm_name", "lead_state",
        "outcome", "call_status", "call_disposition", "interest_level",
        "is_decision_maker", "was_gatekeeper", "pain_point_summary",
        "demo_booking_id", "demo_scheduled_at", "demo_meeting_url",
        "followup_email_sent", "duration_seconds", "started_at",
    ]
    with output.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([
                r.call_id, r.patient_id, r.patient_name, r.firm_name, r.lead_state,
                r.outcome, r.call_status, r.call_disposition, r.interest_level,
                r.is_decision_maker, r.was_gatekeeper, r.pain_point_summary,
                r.demo_booking_id,
                r.demo_scheduled_at.isoformat() if r.demo_scheduled_at else "",
                r.demo_meeting_url, r.followup_email_sent,
                r.duration_seconds,
                r.started_at.isoformat() if r.started_at else "",
            ])
    console.print(f"[green]Exported {len(rows)} calls → {output}[/green]")


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

_ENV_KEYS_PROMPTED = [
    ("OPENAI_API_KEY", True, "OpenAI API key (Realtime-enabled)"),
    ("TWILIO_ACCOUNT_SID", True, "Twilio Account SID"),
    ("TWILIO_AUTH_TOKEN", True, "Twilio Auth Token"),
    ("TWILIO_FROM_NUMBER", True, "Twilio from-number (E.164, e.g. +15551234567)"),
    ("PUBLIC_BASE_URL", True, "Public HTTPS base URL for Twilio callbacks"),
    ("ALLOW_TWILIO_CALLS", False, "Allow real Twilio calls? 'true' or 'false'"),
    ("CALCOM_API_KEY", True, "Cal.com API key"),
    ("CALCOM_EVENT_TYPE_ID", False, "Cal.com event-type ID (integer)"),
    ("SALES_REP_NAME", False, "Sales rep first name (spoken by AI)"),
    ("SALES_REP_COMPANY", False, "Sales rep company name"),
    ("SALES_REP_EMAIL", False, "Sales rep reply-to email"),
    ("PRODUCT_CONTEXT", False, "One-paragraph product context for the AI"),
    ("DATABASE_URL", True, "Postgres URL (postgresql://user:pw@host:5432/db)"),
]


@config_app.command("show")
def config_show():
    """Print current env-based config (masks secrets)."""
    for key, _, _ in _ENV_KEYS_PROMPTED:
        v = os.getenv(key, "")
        if any(s in key for s in ("KEY", "TOKEN", "PASSWORD")) and v:
            v = v[:4] + "…" + v[-2:] if len(v) > 8 else "set"
        console.print(f"{key}={v or '(unset)'}")


@config_app.command("init")
def config_init(env_path: Path = typer.Option(Path(".env"), help="Path to .env file")):
    """Interactive wizard — writes .env in the project root."""
    existing = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()

    answers: dict[str, str] = {}
    for key, required, desc in _ENV_KEYS_PROMPTED:
        default = existing.get(key, "")
        prompt = f"{desc} [{key}]"
        val = typer.prompt(prompt, default=default or "", show_default=bool(default)).strip()
        if required and not val:
            console.print(f"[red]{key} is required — skipping write[/red]")
            raise typer.Exit(code=1)
        answers[key] = val

    lines = [f"{k}={v}" for k, v in answers.items() if v != ""]
    env_path.write_text("\n".join(lines) + "\n")
    console.print(f"[green]Wrote {env_path} ({len(lines)} vars)[/green]")


# ---------------------------------------------------------------------------
# system (master kill switch)
# ---------------------------------------------------------------------------

def _put(path: str, body: dict) -> dict:
    import httpx
    r = httpx.put(f"{_api_base()}{path}", json=body, timeout=15.0)
    try:
        r.raise_for_status()
    except httpx.HTTPError as e:
        console.print(f"[red]{path} {r.status_code}: {r.text[:200]}[/red]")
        raise typer.Exit(code=1) from e
    return r.json() if r.content else {}


@system_app.command("on")
def system_on():
    """Enable the system — dispatcher can now place calls."""
    _put("/api/settings/system-enabled", {"enabled": True})
    console.print("[green]system enabled[/green]")


@system_app.command("off")
def system_off():
    """Disable the system — hard stop. Dispatcher's gate blocks all calls."""
    _put("/api/settings/system-enabled", {"enabled": False})
    console.print("[red]system disabled — no calls will be placed[/red]")


@system_app.command("status")
def system_status():
    """Show the system_enabled flag + related gates."""
    s = _get("/api/settings")
    console.print(f"system_enabled: [{'green' if s.get('system_enabled') else 'red'}]"
                  f"{s.get('system_enabled')}[/]")
    console.print(f"mock_mode:       {s.get('mock_mode')} → {s.get('mock_phone') or '—'}")
    console.print(f"allow_live_calls: {s.get('allow_live_calls')}")
    console.print(f"allowed_phones:   {len(s.get('allowed_phones') or [])} entries")


# ---------------------------------------------------------------------------
# mock mode
# ---------------------------------------------------------------------------

@mock_app.command("on")
def mock_on(phone: str = typer.Argument(..., help="E.164 phone to redirect all calls to (e.g. +1415...)")):
    """Turn mock mode ON — all calls redirect to the given phone."""
    _put("/api/settings/mock-mode", {"enabled": True, "mock_phone": phone})
    console.print(f"[yellow]mock mode ON — redirecting to {phone}[/yellow]")


@mock_app.command("off")
def mock_off():
    """Turn mock mode OFF — calls go to the lead's real phone."""
    _put("/api/settings/mock-mode", {"enabled": False, "mock_phone": ""})
    console.print("[green]mock mode OFF — real outbound active[/green]")


@mock_app.command("status")
def mock_status():
    s = _get("/api/settings")
    mode = "ON" if s.get("mock_mode") else "OFF"
    console.print(f"mock_mode: {mode}  phone: {s.get('mock_phone') or '—'}")


# ---------------------------------------------------------------------------
# allowlist (allowed_phones)
# ---------------------------------------------------------------------------

@allowlist_app.command("list")
def allowlist_list():
    """Show the current phone allowlist."""
    s = _get("/api/settings")
    phones = s.get("allowed_phones") or []
    if not phones:
        console.print("[yellow](empty — no per-phone gating)[/yellow]")
        return
    for p in phones:
        console.print(f"  {p}")


@allowlist_app.command("add")
def allowlist_add(phone: str = typer.Argument(..., help="E.164 phone to add")):
    """Add a phone to allowed_phones."""
    s = _get("/api/settings")
    phones = list(s.get("allowed_phones") or [])
    if phone in phones:
        console.print("(already present)")
        return
    phones.append(phone)
    _put("/api/settings/allowed-phones", {"phones": phones})
    console.print(f"[green]added[/green] {phone} — {len(phones)} total")


@allowlist_app.command("remove")
def allowlist_remove(phone: str = typer.Argument(..., help="E.164 phone to remove")):
    """Remove a phone from allowed_phones."""
    s = _get("/api/settings")
    phones = [p for p in (s.get("allowed_phones") or []) if p != phone]
    _put("/api/settings/allowed-phones", {"phones": phones})
    console.print(f"[green]removed[/green] {phone} — {len(phones)} remaining")


@allowlist_app.command("clear")
def allowlist_clear():
    """Clear the entire allowlist."""
    _put("/api/settings/allowed-phones", {"phones": []})
    console.print("[green]cleared[/green]")


@allowlist_app.command("set-from-leads")
def allowlist_set_from_leads(
    state: Optional[str] = typer.Option(None, help="Filter by 2-letter state"),
    dm_only: bool = typer.Option(True, "--dm-only/--any", help="Only decision-makers"),
    limit: int = typer.Option(20, help="Max leads to add to allowlist"),
):
    """Populate the allowlist from the top N eligible leads (priority-ordered)."""
    async def _q():
        from app.db import AsyncSessionLocal
        from app.db.models import PatientRow
        from sqlalchemy import select
        async with AsyncSessionLocal() as s:
            stmt = select(PatientRow).where(PatientRow.attempt_count == 0).order_by(PatientRow.priority_bucket)
            if state:
                stmt = stmt.where(PatientRow.state == state.upper())
            stmt = stmt.limit(limit * 3)  # oversample then filter DM
            res = await s.execute(stmt)
            rows = list(res.scalars().all())
            if dm_only:
                rows = [r for r in rows if "decision-maker" in (r.tags or [])]
            return [r.phone for r in rows[:limit] if r.phone]
    phones = _run(_q())
    _put("/api/settings/allowed-phones", {"phones": phones})
    console.print(f"[green]allowlist set to {len(phones)} phones[/green]"
                  f"{' (state=' + state.upper() + ')' if state else ''}"
                  f"{' (DM only)' if dm_only else ''}")


# ---------------------------------------------------------------------------
# followups (GTM action queue)
# ---------------------------------------------------------------------------

@followups_app.command("list")
def followups_list(
    action: Optional[str] = typer.Option(None, "--action", help="Filter by follow_up_action"),
    owner: Optional[str] = typer.Option(None, "--owner", help="Filter by follow_up_owner (autocaller|sales_human|none)"),
    disposition: Optional[str] = typer.Option(None, "--disposition"),
    due_within_days: int = typer.Option(14, "--within", help="Only show items due within N days"),
    limit: int = typer.Option(50, "--limit"),
):
    """List calls awaiting follow-up action. See docs/DISPOSITIONS.md."""
    async def _q():
        from app.db import AsyncSessionLocal
        from app.db.models import CallLogRow
        from sqlalchemy import select, and_, or_
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        horizon = now + timedelta(days=due_within_days)
        async with AsyncSessionLocal() as s:
            stmt = (
                select(CallLogRow)
                .where(CallLogRow.gtm_disposition.is_not(None))
                .where(CallLogRow.follow_up_action.is_not(None))
                .where(CallLogRow.follow_up_action != "discard")
                .where(CallLogRow.follow_up_action != "mark_dnc")
                .where(CallLogRow.follow_up_action != "mark_bad_number")
                .where(
                    or_(
                        CallLogRow.follow_up_when.is_(None),
                        CallLogRow.follow_up_when <= horizon,
                    )
                )
                .order_by(CallLogRow.follow_up_when.asc().nulls_first())
                .limit(limit)
            )
            if action:
                stmt = stmt.where(CallLogRow.follow_up_action == action)
            if owner:
                stmt = stmt.where(CallLogRow.follow_up_owner == owner)
            if disposition:
                stmt = stmt.where(CallLogRow.gtm_disposition == disposition)
            res = await s.execute(stmt)
            return list(res.scalars().all())
    rows = _run(_q())
    if not rows:
        console.print("[yellow]No follow-ups match the filter.[/yellow]")
        return
    table = Table(title=f"Follow-ups ({len(rows)})")
    for col in ["when", "action", "owner", "disposition", "firm", "lead", "note"]:
        table.add_column(col, overflow="fold")
    for r in rows:
        table.add_row(
            r.follow_up_when.strftime("%Y-%m-%d") if r.follow_up_when else "—",
            r.follow_up_action or "—",
            r.follow_up_owner or "—",
            r.gtm_disposition or "—",
            (r.firm_name or "—")[:25],
            (r.patient_name or "—")[:20],
            (r.follow_up_note or "—")[:50],
        )
    console.print(table)


@followups_app.command("show")
def followups_show(call_id: str = typer.Argument(...)):
    """Full follow-up detail for one call (alias for `calls show` with a focus)."""
    async def _q():
        from app.db import AsyncSessionLocal
        from app.db.models import CallLogRow
        from sqlalchemy import select
        async with AsyncSessionLocal() as s:
            r = await s.execute(select(CallLogRow).where(CallLogRow.call_id == call_id))
            return r.scalar_one_or_none()
    row = _run(_q())
    if not row:
        console.print(f"[red]Not found: {call_id}[/red]")
        raise typer.Exit(code=1)
    console.print_json(data={
        "call_id": row.call_id,
        "lead": row.patient_name, "firm": row.firm_name, "state": row.lead_state,
        "disposition": row.gtm_disposition,
        "follow_up_action": row.follow_up_action,
        "follow_up_when": row.follow_up_when.isoformat() if row.follow_up_when else None,
        "follow_up_owner": row.follow_up_owner,
        "follow_up_note": row.follow_up_note,
        "captured_contacts": row.captured_contacts,
        "pain_points_discussed": row.pain_points_discussed,
        "signal_flags": row.signal_flags,
    })


@followups_app.command("send-voicemail")
def followups_send_voicemail(
    call_id: str = typer.Argument(...),
    dry_run: bool = typer.Option(False, "--dry-run", help="Resolve recipient only; do not send."),
):
    """Fire the VM / no-reach follow-up email for a single call_id.

    Gated by ALLOW_VOICEMAIL_EMAIL=true. Picks email from captured_contacts,
    falls back to patients.email.
    """
    from app.services.voicemail_followup_service import process_one_by_id
    result = _run(process_one_by_id(call_id, dry_run=dry_run))
    console.print_json(data=result)


@followups_app.command("backfill-voicemails")
def followups_backfill_voicemails(
    since_days: int = typer.Option(7, "--since-days", help="Only look back N days."),
    limit: int = typer.Option(50, "--limit", help="Max calls to process this run."),
    dry_run: bool = typer.Option(True, "--dry-run/--live",
                                 help="Default dry-run. Pass --live to actually send."),
):
    """Batch-send VM / no-reach follow-up emails for eligible calls.

    Default is --dry-run for safety. Pass --live to actually send.
    Also gated by ALLOW_VOICEMAIL_EMAIL=true.
    """
    from app.services.voicemail_followup_service import tick
    results = _run(tick(limit=limit, since_days=since_days, dry_run=dry_run))
    sent = sum(1 for r in results if r.get("delivered"))
    skipped = sum(1 for r in results if r.get("skipped"))
    dry = sum(1 for r in results if r.get("dry_run"))
    errors = sum(1 for r in results if r.get("error"))
    console.print_json(data={
        "mode": "dry_run" if dry_run else "live",
        "since_days": since_days,
        "total": len(results),
        "sent": sent, "skipped": skipped, "dry_run_count": dry, "errors": errors,
        "results": results,
    })


# ---------------------------------------------------------------------------
# listening — Mission Control mindset brief + insights
# ---------------------------------------------------------------------------

def _listening_client():
    from app.services.listening_client import ListeningClient

    return ListeningClient()


def _listening_get(coro):
    from app.services.listening_client import ListeningClientError

    try:
        return _run(coro)
    except ListeningClientError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1) from e


def _rows_from_payload(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = payload.get(key)
    if rows is None:
        rows = payload.get("items")
    return [row for row in (rows or []) if isinstance(row, dict)]


def _brief_text(payload: dict[str, Any]) -> str:
    return str(payload.get("brief_md") or payload.get("markdown") or payload.get("body") or "")


def _parse_dt(value: Any):
    if not value:
        return None
    from datetime import datetime, timezone

    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _source_stale(row: dict[str, Any]) -> bool:
    from datetime import datetime, timezone

    if row.get("stale") is not None:
        return bool(row.get("stale"))
    last = _parse_dt(row.get("last_polled_at"))
    if last is None:
        return True
    try:
        cadence = int(row.get("expected_cadence_days") or 30)
    except (TypeError, ValueError):
        cadence = 30
    return (datetime.now(timezone.utc) - last).days > cadence


@listening_app.command("brief")
def listening_brief(
    version: Optional[int] = typer.Option(None, "--version", "-v", help="Brief version to print. Defaults to latest."),
):
    """Print the Mission Control mindset brief as markdown."""
    data = _listening_get(_listening_client().brief(version=version))
    md = _brief_text(data)
    if not md:
        console.print("[yellow]Brief returned no markdown.[/yellow]")
        console.print_json(data=data)
        return
    console.print(md, markup=False)


@listening_app.command("search")
def listening_search(
    q: str = typer.Argument(..., help="Insight search query."),
    insight_type: Optional[str] = typer.Option(None, "--type", "-t", help="Filter by insight type."),
    who: Optional[str] = typer.Option(None, "--who", "-w", help="Filter by who_feels_it persona."),
    limit: int = typer.Option(20, "--limit", "-n", min=1, max=100, help="Maximum insights to show."),
):
    """Search listening insights."""
    data = _listening_get(_listening_client().insights(
        q=q,
        insight_type=insight_type,
        who=who,
        limit=limit,
    ))
    rows = _rows_from_payload(data, "insights")
    if not rows:
        console.print("[yellow]No insights matched.[/yellow]")
        return
    table = Table(title=f"Listening insights ({len(rows)})")
    for col in ["type", "cluster", "who", "severity", "quote", "source"]:
        table.add_column(col, overflow="fold")
    for row in rows:
        table.add_row(
            str(row.get("type") or "—"),
            str(row.get("cluster") or "—"),
            str(row.get("who_feels_it") or "—"),
            str(row.get("severity") or "—"),
            str(row.get("quote") or row.get("paraphrase") or "—")[:220],
            str(row.get("source_name") or row.get("url") or "—")[:80],
        )
    console.print(table)


@listening_app.command("quotes")
def listening_quotes(
    cluster: str = typer.Option(..., "--cluster", "-c", help="Insight cluster to pull quotes from."),
    limit: int = typer.Option(5, "--limit", "-n", min=1, max=50, help="Maximum quotes to show."),
):
    """Show direct quotes for one insight cluster."""
    data = _listening_get(_listening_client().insights(cluster=cluster, limit=limit))
    rows = _rows_from_payload(data, "insights")
    if not rows:
        console.print("[yellow]No quotes matched.[/yellow]")
        return
    for i, row in enumerate(rows, start=1):
        quote = str(row.get("quote") or row.get("paraphrase") or "").strip()
        source = str(row.get("source_name") or row.get("url") or "").strip()
        console.print(f"[bold]{i}. {row.get('type') or 'insight'}[/bold] [{row.get('who_feels_it') or 'unknown'}]")
        console.print(quote, markup=False)
        if source:
            console.print(f"[dim]{source}[/dim]")
        console.print()


@listening_app.command("sources")
def listening_sources():
    """List listening sources and freshness state."""
    data = _listening_get(_listening_client().sources(limit=500))
    rows = _rows_from_payload(data, "sources")
    if not rows:
        console.print("[yellow]No sources returned.[/yellow]")
        return
    table = Table(title=f"Listening sources ({len(rows)})")
    for col in ["name", "kind", "last_polled_at", "stale"]:
        table.add_column(col, overflow="fold")
    for row in rows:
        stale = _source_stale(row)
        table.add_row(
            str(row.get("name") or "—")[:60],
            str(row.get("kind") or "—"),
            str(row.get("last_polled_at") or "never"),
            "yes" if stale else "no",
        )
    console.print(table)


async def _firm_context_for_prep(term: str) -> dict[str, Any]:
    from sqlalchemy import or_, select

    from app.db import AsyncSessionLocal
    from app.db.models import FirmContactRow, PatientRow

    like = f"%{term}%"
    async with AsyncSessionLocal() as session:
        patients = (await session.execute(
            select(PatientRow)
            .where(or_(PatientRow.firm_name.ilike(like), PatientRow.name.ilike(like)))
            .order_by(PatientRow.updated_at.desc())
            .limit(5)
        )).scalars().all()
        pif_ids = []
        for row in patients:
            pid = row.patient_id or ""
            if pid.startswith("pif-"):
                pif_ids.append(pid[4:])
            elif pid.startswith("mc-"):
                pif_ids.append(pid[3:])
        contact_filters = [FirmContactRow.full_name.ilike(like)]
        if pif_ids:
            contact_filters.append(FirmContactRow.pif_id.in_(pif_ids))
        contacts = (await session.execute(
            select(FirmContactRow)
            .where(or_(*contact_filters))
            .order_by(FirmContactRow.updated_at.desc())
            .limit(10)
        )).scalars().all()
    return {
        "query": term,
        "patients": [
            {
                "patient_id": row.patient_id,
                "lead_name": row.name,
                "firm_name": row.firm_name,
                "state": row.state,
                "practice_area": row.practice_area,
                "title": row.title,
                "tags": row.tags,
                "notes": row.notes,
                "source": row.source,
            }
            for row in patients
        ],
        "contacts": [
            {
                "id": row.id,
                "pif_id": row.pif_id,
                "full_name": row.full_name,
                "first_name": row.first_name,
                "title": row.title,
                "email": row.email,
                "source": row.source,
            }
            for row in contacts
        ],
    }


def _prep_search_query(context: dict[str, Any], term: str) -> str:
    parts = [term]
    for row in context.get("patients") or []:
        parts.extend([
            row.get("firm_name"),
            row.get("practice_area"),
            row.get("title"),
            row.get("notes"),
        ])
        parts.extend(row.get("tags") or [])
    for row in context.get("contacts") or []:
        parts.append(row.get("title"))
    text = " ".join(str(part or "") for part in parts)
    tokens = [
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text)
        if token.lower() not in {"firm", "law", "legal", "group", "office", "and", "the"}
    ]
    return " ".join(list(dict.fromkeys(tokens))[:10]) or term


async def _render_listening_prep(context: dict[str, Any], insights: list[dict[str, Any]]) -> str:
    from app.services.llm_gateway import DEFAULT_GATEWAY_URL, extract_json, gateway_token, require_fields

    url = os.getenv("OPENCLAW_GATEWAY_URL", DEFAULT_GATEWAY_URL)
    model = os.getenv("LISTENING_PREP_MODEL", os.getenv("OPENCLAW_DEFAULT_MODEL", "openclaw/proxy"))
    payload = {
        "firm_context": context,
        "matched_insights": insights[:8],
        "task": (
            "Render a concise pre-call one-pager for a PI-firm outreach call. "
            "Return JSON with markdown, persona, expected_objections, and vocabulary."
        ),
    }
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You prepare practical sales-call prep for Possible Minds. "
                    "Use only the provided firm context and listening insights. "
                    "Return JSON only: {\"markdown\": string, \"persona\": string, "
                    "\"expected_objections\": [string], \"vocabulary\": [string]}."
                ),
            },
            {"role": "user", "content": json.dumps(payload, indent=2)},
        ],
        "max_tokens": 1100,
    }
    timeout_s = float(os.getenv("LISTENING_PREP_TIMEOUT_S", "240"))
    async with httpx.AsyncClient(timeout=timeout_s, verify=False) as client:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {gateway_token()}",
                "Content-Type": "application/json",
            },
            json=body,
        )
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    parsed = extract_json(content)
    require_fields(parsed, ["markdown", "persona", "expected_objections", "vocabulary"])
    return str(parsed["markdown"]).strip()


@listening_app.command("prep")
def listening_prep(
    firm_or_name: str = typer.Argument(..., help="Firm or contact name to prepare for."),
):
    """Build a one-page persona, objections, and vocabulary prep sheet."""
    context = _run(_firm_context_for_prep(firm_or_name))
    if not context.get("patients") and not context.get("contacts"):
        console.print(f"[red]No local firm/contact context matched: {firm_or_name}[/red]")
        raise typer.Exit(code=1)
    search_query = _prep_search_query(context, firm_or_name)
    insights_data = _listening_get(_listening_client().insights(q=search_query, limit=8))
    insights = _rows_from_payload(insights_data, "insights")
    try:
        markdown = _run(_render_listening_prep(context, insights))
    except Exception as e:
        console.print(f"[red]Prep LLM call failed: {type(e).__name__}: {str(e)[:300]}[/red]")
        raise typer.Exit(code=1) from e
    console.print(markdown, markup=False)


# ---------------------------------------------------------------------------
# status + doctor
# ---------------------------------------------------------------------------

@app.command()
def status():
    """One-shot system status summary."""
    try:
        s = _get("/api/status")
        console.print_json(data=s)
    except typer.Exit:
        console.print("[yellow]Daemon unreachable - run `possibleos serve`.[/yellow]")


@app.command()
def doctor():
    """Validate env + connectivity to Twilio, OpenAI, Cal.com, and DB."""
    import urllib.parse as _urlparse

    checks: list[tuple[str, bool, str]] = []

    # Env
    for key in ("OPENAI_API_KEY", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN",
                "TWILIO_FROM_NUMBER", "DATABASE_URL"):
        ok = bool(os.getenv(key, "").strip())
        checks.append((f"env:{key}", ok, "set" if ok else "missing"))

    # DB
    async def _ping_db():
        from app.db import async_engine
        from sqlalchemy import text
        try:
            async with async_engine.connect() as conn:
                await conn.execute(text("select 1"))
            return True, "ok"
        except Exception as e:
            return False, str(e)[:80]

    ok, detail = _run(_ping_db())
    checks.append(("db", ok, detail))

    # Cal.com
    key = os.getenv("CALCOM_API_KEY", "").strip()
    if key:
        async def _ping_calcom():
            async with httpx.AsyncClient(timeout=8.0) as cli:
                try:
                    r = await cli.get("https://api.cal.com/v2/me",
                                      headers={"Authorization": f"Bearer {key}"})
                    return r.status_code < 500, f"HTTP {r.status_code}"
                except Exception as e:
                    return False, str(e)[:80]
        ok, detail = _run(_ping_calcom())
        checks.append(("calcom", ok, detail))
    else:
        checks.append(("calcom", False, "no CALCOM_API_KEY"))

    # OpenAI — we only check the HTTP-side `/v1/models` to avoid hitting quota
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if key:
        async def _ping_openai():
            async with httpx.AsyncClient(timeout=8.0) as cli:
                try:
                    r = await cli.get("https://api.openai.com/v1/models",
                                      headers={"Authorization": f"Bearer {key}"})
                    return r.status_code < 500, f"HTTP {r.status_code}"
                except Exception as e:
                    return False, str(e)[:80]
        ok, detail = _run(_ping_openai())
        checks.append(("openai", ok, detail))
    else:
        checks.append(("openai", False, "no OPENAI_API_KEY"))

    # Public base URL reachable?
    pub = os.getenv("PUBLIC_BASE_URL", "").strip()
    if pub:
        try:
            parsed = _urlparse.urlparse(pub)
            reachable = parsed.scheme in ("http", "https") and bool(parsed.netloc)
            checks.append(("public_base_url", reachable, pub))
        except Exception as e:
            checks.append(("public_base_url", False, str(e)[:80]))
    else:
        checks.append(("public_base_url", False, "unset — Twilio callbacks will fail"))

    table = Table(title="Possible OS doctor")
    table.add_column("check")
    table.add_column("ok")
    table.add_column("detail", overflow="fold")
    any_bad = False
    for name, ok, detail in checks:
        table.add_row(name, "[green]✓[/green]" if ok else "[red]✗[/red]", detail)
        if not ok:
            any_bad = True
    console.print(table)
    if any_bad:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# voice provider (openai | gemini)
# ---------------------------------------------------------------------------

def _voice_status_line(s: dict) -> str:
    provider = s.get("voice_provider") or "openai"
    model = s.get("voice_model") or "<backend default>"
    return f"provider={provider}  model={model}"


@voice_app.command("status")
def voice_status():
    """Show the current default voice backend (applies to future calls)."""
    s = _get("/api/settings")
    console.print(_voice_status_line(s))


@voice_app.command("openai")
def voice_openai(
    model: str = typer.Option("", "--model", help="Override OPENAI_REALTIME_MODEL for this setting"),
):
    """Switch default voice backend to OpenAI Realtime."""
    s = _put("/api/settings/voice", {"provider": "openai", "model": model})
    console.print(f"[green]✓[/green] {_voice_status_line(s)}")


@voice_app.command("gemini")
def voice_gemini(
    model: str = typer.Option("", "--model", help="Override GEMINI_LIVE_MODEL for this setting"),
):
    """Switch default voice backend to Gemini Live."""
    s = _put("/api/settings/voice", {"provider": "gemini", "model": model})
    console.print(f"[green]✓[/green] {_voice_status_line(s)}")


@voice_app.command("set")
def voice_set(
    provider: str = typer.Argument(..., help="'openai' or 'gemini'"),
    model: str = typer.Option("", "--model", help="Exact model ID (empty → backend env default)"),
):
    """Set default voice backend + optional model override."""
    p = provider.strip().lower()
    if p not in ("openai", "gemini"):
        console.print(f"[red]provider must be 'openai' or 'gemini' (got {provider!r})[/red]")
        raise typer.Exit(code=2)
    s = _put("/api/settings/voice", {"provider": p, "model": model})
    console.print(f"[green]✓[/green] {_voice_status_line(s)}")


@voice_app.command("config")
def voice_config(
    provider: str = typer.Argument(
        "",
        help="'openai' or 'gemini'. Omit to see the full config for both.",
    ),
):
    """Show the per-provider voice config (name, temperature, flags)."""
    p = (provider or "").strip().lower()
    s = _get("/api/settings")
    cfg = s.get("voice_config") or {}
    if not p:
        console.print_json(data=cfg)
        return
    if p not in ("openai", "gemini"):
        console.print(f"[red]provider must be 'openai' or 'gemini' (got {provider!r})[/red]")
        raise typer.Exit(code=2)
    console.print_json(data=cfg.get(p, {}))


@voice_app.command("set-voice")
def voice_set_voice(
    provider: str = typer.Argument(..., help="'openai' or 'gemini'"),
    voice: str = typer.Argument(..., help="Prebuilt voice name"),
):
    """Set the prebuilt voice name for a provider.

    OpenAI: alloy, ash, ballad, coral, echo, sage, shimmer, verse.
    Gemini: Aoede, Puck, Charon, Kore, Fenrir, Leda, Orus, Zephyr.
    """
    p = provider.strip().lower()
    s = _put("/api/settings/voice-config", {"provider": p, "voice": voice})
    console.print(f"[green]✓[/green] voice_config[{p}].voice = {voice}")
    console.print_json(data=(s.get("voice_config") or {}).get(p, {}))


@voice_app.command("temperature")
def voice_temperature(
    provider: str = typer.Argument(..., help="'openai' or 'gemini'"),
    value: float = typer.Argument(..., help="0.0 to 2.0"),
):
    """Set sampling temperature for a provider."""
    p = provider.strip().lower()
    s = _put("/api/settings/voice-config", {"provider": p, "temperature": value})
    console.print(f"[green]✓[/green] voice_config[{p}].temperature = {value}")
    console.print_json(data=(s.get("voice_config") or {}).get(p, {}))


@voice_app.command("affective")
def voice_affective(
    state: str = typer.Argument(..., help="'on' or 'off' — Gemini only"),
):
    """Toggle Gemini's affective-dialog flag (emotion-matched prosody)."""
    st = state.strip().lower()
    if st not in ("on", "off"):
        console.print("[red]state must be 'on' or 'off'[/red]")
        raise typer.Exit(code=2)
    s = _put("/api/settings/voice-config", {
        "provider": "gemini", "affective_dialog": st == "on",
    })
    console.print(f"[green]✓[/green] voice_config[gemini].affective_dialog = {st == 'on'}")
    console.print_json(data=(s.get("voice_config") or {}).get("gemini", {}))


@voice_app.command("proactive")
def voice_proactive(
    state: str = typer.Argument(..., help="'on' or 'off' — Gemini only"),
):
    """Toggle Gemini's proactive-audio flag (model emits short non-verbal cues)."""
    st = state.strip().lower()
    if st not in ("on", "off"):
        console.print("[red]state must be 'on' or 'off'[/red]")
        raise typer.Exit(code=2)
    s = _put("/api/settings/voice-config", {
        "provider": "gemini", "proactive_audio": st == "on",
    })
    console.print(f"[green]✓[/green] voice_config[gemini].proactive_audio = {st == 'on'}")
    console.print_json(data=(s.get("voice_config") or {}).get("gemini", {}))


@voice_app.command("voices")
def voice_voices():
    """Print the supported voice names per provider (reference)."""
    console.print("[bold]OpenAI Realtime[/bold]")
    for v in ("alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse"):
        console.print(f"  • {v}")
    console.print()
    console.print("[bold]Gemini Live[/bold]")
    for v in ("Aoede", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Zephyr"):
        console.print(f"  • {v}")


@voice_app.command("speed")
def voice_speed(value: float = typer.Argument(..., help="Playback speed 0.25-4.0 (default 1.0) — OpenAI only")):
    """Set OpenAI Realtime speech speed. Higher = faster playback."""
    s = _put("/api/settings/voice-config", {"provider": "openai", "speed": value})
    console.print(f"[green]✓[/green] voice_config[openai].speed = {value}")
    console.print_json(data=(s.get("voice_config") or {}).get("openai", {}))


@voice_app.command("top-p")
def voice_top_p(value: float = typer.Argument(..., help="Top-P sampling 0.0-1.0 (default 0.95) — Gemini only")):
    """Set Gemini nucleus-sampling cutoff. Lower = more deterministic."""
    s = _put("/api/settings/voice-config", {"provider": "gemini", "top_p": value})
    console.print(f"[green]✓[/green] voice_config[gemini].top_p = {value}")
    console.print_json(data=(s.get("voice_config") or {}).get("gemini", {}))


# ---------------------------------------------------------------------------
# ivr (phone-tree navigation)
# ---------------------------------------------------------------------------

@ivr_app.command("status")
def ivr_status():
    """Show whether phone-tree navigation is enabled."""
    s = _get("/api/settings")
    enabled = bool(s.get("ivr_navigate_enabled", False))
    console.print(f"ivr_navigate_enabled = {enabled}")


@ivr_app.command("on")
def ivr_on():
    """Enable phone-tree navigation for subsequent calls."""
    s = _put("/api/settings/ivr-navigate", {"enabled": True})
    console.print(f"[green]✓[/green] ivr_navigate_enabled = {s.get('ivr_navigate_enabled')}")


@ivr_app.command("off")
def ivr_off():
    """Disable phone-tree navigation — hang up on first menu prompt (legacy behavior)."""
    s = _put("/api/settings/ivr-navigate", {"enabled": False})
    console.print(f"[green]✓[/green] ivr_navigate_enabled = {s.get('ivr_navigate_enabled')}")


# ---------------------------------------------------------------------------
# carrier — inspect active Twilio account
# ---------------------------------------------------------------------------

def _carrier_block(info: dict, is_default: bool) -> Table:
    t = Table(show_header=False, box=None, pad_edge=False)
    t.add_column(justify="right", style="dim")
    t.add_column()
    name = info.get("provider", "?")
    label = info.get("label") or ""
    title = f"[bold]{name}[/bold]"
    if label:
        title += f"  [dim]({label})[/dim]"
    if is_default:
        title += "  [green]← default[/green]"
    t.add_row("", title)
    if not info.get("configured"):
        t.add_row("", f"[red]{info.get('error') or 'not configured'}[/red]")
        return t
    status = info.get("status") or "?"
    status_color = (
        "green" if status == "active" and info.get("reachable")
        else "yellow" if info.get("reachable") else "red"
    )
    acct_sid = info.get("account_sid_masked") or ""
    acct_name = info.get("account_name") or ""
    t.add_row("account", f"{acct_sid}  [dim]{acct_name}[/dim]".strip())
    if info.get("account_type"):
        t.add_row("account type", info["account_type"])
    t.add_row("status", f"[{status_color}]{status}[/{status_color}]  reachable={info.get('reachable')}")
    t.add_row(
        "from number",
        f"{info.get('from_number','')}  [dim]{info.get('number_status') or ''}[/dim]",
    )
    bal = info.get("balance")
    if bal is not None:
        try:
            b = float(bal)
            col = "red" if b < 5 else "green"
            t.add_row("balance", f"[{col}]{info.get('currency','')} {b:.2f}[/{col}]")
        except ValueError:
            t.add_row("balance", f"{info.get('currency','')} {bal}")
    if info.get("error"):
        t.add_row("error", f"[red]{info['error']}[/red]")
    return t


@carrier_app.command("status")
def carrier_status():
    """Show both carrier accounts — Twilio + Telnyx — and mark the default."""
    c = _get("/api/carrier")
    default = c.get("default_carrier", "twilio")
    carriers = c.get("carriers", {})
    for name in ("twilio", "telnyx"):
        info = carriers.get(name) or {}
        console.print(_carrier_block(info, is_default=(name == default)))
        console.print("")
    console.print(
        "[dim]Switch default: [/dim][bold]possibleos carrier twilio[/bold][dim] / [/dim]"
        "[bold]possibleos carrier telnyx[/bold][dim]. "
        "Per-call override: [/dim][bold]--carrier=telnyx[/bold][dim] on `call`.[/dim]"
    )


@carrier_app.command("twilio")
def carrier_set_twilio():
    """Set default telephony carrier to Twilio."""
    r = _put("/api/carrier", {"carrier": "twilio"})
    console.print(f"[green]✓[/green] default_carrier = {r.get('default_carrier')}")


@carrier_app.command("telnyx")
def carrier_set_telnyx():
    """Set default telephony carrier to Telnyx."""
    r = _put("/api/carrier", {"carrier": "telnyx"})
    console.print(f"[green]✓[/green] default_carrier = {r.get('default_carrier')}")


@carrier_app.command("set")
def carrier_set(
    name: str = typer.Argument(..., help="'twilio' or 'telnyx'"),
):
    """Set the default carrier by name."""
    n = name.strip().lower()
    if n not in ("twilio", "telnyx"):
        console.print("[red]carrier must be 'twilio' or 'telnyx'[/red]")
        raise typer.Exit(code=2)
    r = _put("/api/carrier", {"carrier": n})
    console.print(f"[green]✓[/green] default_carrier = {r.get('default_carrier')}")


@leads_app.command("sync-pifstats")
def leads_sync_pifstats(
    limit: int = typer.Option(100, help="Max firms to pull"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    recently_researched: int = typer.Option(
        0,
        "--recently-researched",
        help="Only pull firms researched in the last N days (0 = no filter)",
    ),
):
    """Pull researched firms from PIF Stats into the Possible OS leads table.

    Only imports firms that have been researched (leadership data available)
    and have a phone number. Picks the best decision-maker contact from
    the leadership list. Keyed by 'pif-{pif_id}' for idempotent re-sync.
    """
    import httpx

    PIF_BASE = "https://emailprocessing.mediflow360.com/api/v1/pif-info"

    console.print(f"Fetching researched firms from PIF Stats (limit={limit})...")

    firms = []
    page = 1
    extra = f"&recently_researched={recently_researched}" if recently_researched > 0 else ""
    while len(firms) < limit:
        resp = httpx.get(
            f"{PIF_BASE}/?page={page}&page_size=100{extra}",
            timeout=30,
        )
        data = resp.json()
        items = data.get("items", [])
        for f in items:
            if (f.get("research_status") == "completed" or f.get("last_researched_at")) \
                    and f.get("phones") and f.get("leadership"):
                firms.append(f)
        if page >= data.get("total_pages", 1):
            break
        page += 1
        if page > 30:
            break

    console.print(f"Found {len(firms)} callable researched firms")

    # Pick best contact per firm
    DM_TITLES = {"owner", "partner", "managing", "principal", "director", "ceo", "coo", "president", "founder", "shareholder"}

    rows = []
    for firm in firms[:limit]:
        leaders = firm.get("leadership") or []
        phones = firm.get("phones") or []
        best = None
        best_score = -1
        for l in leaders:
            title_lower = (l.get("title") or "").lower()
            score = sum(1 for kw in DM_TITLES if kw in title_lower) * 10
            if l.get("phone"):
                score += 5
            if l.get("email"):
                score += 3
            if l.get("linkedin"):
                score += 2
            if score > best_score:
                best_score = score
                best = l

        if not best:
            continue

        # Pick phone: prefer leader's phone, fall back to firm phone
        phone = (best.get("phone") or "").strip()
        if not phone and phones:
            phone = phones[0]
        phone = phone.replace("\u2011", "-").replace(".", "-").strip()

        # Normalize via the canonical helper so extension-suffixed
        # numbers ("844-422-3476 ext 102") drop to the base instead of
        # smushing into an invalid 13-digit blob — root cause of the
        # Dennis Lalezar D11 failure. See app/services/phone_normalize.py.
        from app.services.phone_normalize import normalize_phone
        phone = normalize_phone(phone)
        if not phone:
            continue
        # Sanity bound — 10-digit US is 12 chars (+1NNN…); max E.164 16.
        if len(phone) < 11 or len(phone) > 16:
            continue

        beh = firm.get("behavioral_data") or {}
        pain = beh.get("primary_pain_point", "")
        after_hrs = beh.get("after_hours_ratio")
        email_vol = beh.get("monthly_email_volume", [])
        notes_parts = []
        if pain:
            notes_parts.append(f"Pain: {pain.replace('_', ' ')}")
        if after_hrs is not None:
            notes_parts.append(f"After-hours: {round(after_hrs * 100)}%")
        if email_vol:
            avg = sum(email_vol) / len(email_vol)
            notes_parts.append(f"Email vol: {avg:.0f}/mo")
        notes_parts.append(f"PIF ID: {firm['id']}")

        rows.append({
            "patient_id": f"pif-{firm['id']}",
            "name": best["name"],
            "phone": phone,
            "firm_name": firm.get("firm_name"),
            "state": None,  # TODO: extract from address
            "practice_area": "personal injury",
            "email": best.get("email"),
            "title": (best.get("title") or "")[:128] or None,
            "website": firm.get("website"),
            "source": "pifstats",
            "tags": [f"pif-tier:{firm.get('icp_tier', '?')}"],
            "notes": " | ".join(notes_parts) if notes_parts else None,
        })

    console.print(f"Extracted {len(rows)} leads with valid phone + DM contact")

    if dry_run:
        for r in rows[:15]:
            console.print(
                f"  {r['name'][:28]:28s}  {(r.get('title') or '-')[:28]:28s}  "
                f"{(r['firm_name'] or '-')[:30]:30s}  {r['phone']}"
            )
        if len(rows) > 15:
            console.print(f"  ... and {len(rows) - 15} more")
        console.print("[cyan]--dry-run: no DB writes[/cyan]")
        return

    async def _upsert():
        from app.db import AsyncSessionLocal
        from app.db.models import PatientRow
        from sqlalchemy import select
        ins, upd = 0, 0
        async with AsyncSessionLocal() as session:
            for lead in rows:
                existing = await session.execute(
                    select(PatientRow).where(PatientRow.patient_id == lead["patient_id"])
                )
                row_obj = existing.scalar_one_or_none()
                if row_obj:
                    for k, v in lead.items():
                        if k == "patient_id":
                            continue
                        setattr(row_obj, k, v)
                    upd += 1
                else:
                    session.add(PatientRow(**lead))
                    ins += 1
            await session.commit()
        return ins, upd

    ins, upd = _run(_upsert())
    console.print(f"[green]Inserted {ins}, updated {upd}.[/green]")


# ---------------------------------------------------------------------------
# Prompts — parallel prompt-style selector
# ---------------------------------------------------------------------------

@prompts_app.command("show")
def prompts_show():
    """Show the active prompt style + version."""
    from app.prompts import active as prompt_mod
    style = prompt_mod.get_active_style()
    version = prompt_mod.get_prompt_version()
    console.print(f"Active style  : [bold]{style}[/bold]")
    console.print(f"PROMPT_VERSION: {version}")
    console.print(
        f"(Switch via [bold]possibleos prompts set <style>[/bold] or the "
        f"/system UI panel. DB-backed, no restart needed. Valid: "
        f"{', '.join(prompt_mod.VALID_STYLES)}.)"
    )


@prompts_app.command("set")
def prompts_set(
    style: str = typer.Argument(
        ..., help="Prompt style to activate. One of: current, minimal."
    ),
):
    """Switch the active prompt style. Persisted in system_settings;
    takes effect on the next call (cache TTL ~5s)."""
    from app.prompts import active as prompt_mod
    s = (style or "").strip().lower()
    if s not in prompt_mod.VALID_STYLES:
        console.print(
            f"[red]Invalid style: {style!r}. Valid: "
            f"{', '.join(prompt_mod.VALID_STYLES)}[/red]"
        )
        raise typer.Exit(code=1)
    written = _run(prompt_mod.set_active_style(s))
    console.print(
        f"[green]Active prompt style → {written}[/green] "
        f"(takes effect on the next call)"
    )


@prompts_app.command("list")
def prompts_list():
    """List available prompt styles with their versions."""
    from app.prompts import active as prompt_mod
    active = prompt_mod.get_active_style()
    console.print("[bold]Available prompt styles:[/bold]")
    for style in prompt_mod.VALID_STYLES:
        if style == "current":
            from app.prompts import attorney_cold_call as m
        else:
            from app.prompts import attorney_cold_call_minimal as m
        marker = "●" if style == active else "○"
        console.print(
            f"  {marker} {style:10} {m.PROMPT_VERSION}"
            f"{'  (active)' if style == active else ''}"
        )


@prompts_app.command("preview")
def prompts_preview(
    style: str = typer.Option(
        "", "--style", "-s",
        help="Style to preview (default: active). One of: current, minimal.",
    ),
    lead_name: str = typer.Option("Zoe Fernbacher", help="Sample lead name"),
    firm: str = typer.Option("Homa Molayem Law Corporation", help="Sample firm"),
    state: str = typer.Option("CA", help="Sample state (2-letter)"),
):
    """Preview the rendered system prompt against a sample lead.

    Useful for eyeballing what each style actually sends to the model
    without placing a live call.
    """
    from types import SimpleNamespace
    from app.prompts import active as prompt_mod

    s = (style or prompt_mod.get_active_style()).strip().lower()
    if s == "current":
        from app.prompts import attorney_cold_call as mod
    elif s == "minimal":
        from app.prompts import attorney_cold_call_minimal as mod
    else:
        console.print(f"[red]Unknown style {s!r}. Use current or minimal.[/red]")
        raise typer.Exit(code=2)

    lead = SimpleNamespace(
        name=lead_name, firm_name=firm, state=state,
        title="Partner", language="en", name_is_person=True,
    )
    text = mod.render_system_prompt(
        lead=lead,
        rep_name="Alex",
        rep_company="Possible Minds",
        rep_phone="443-775-2452",
        product_context="",
    )
    console.print(f"[dim]--- {s} ({mod.PROMPT_VERSION}) · "
                  f"{len(text)} chars · {text.count(chr(10))+1} lines ---[/dim]")
    console.print(text)


# ---------------------------------------------------------------------------
# email — config check + manual sends
# ---------------------------------------------------------------------------

def _mask(value: str, keep: int = 4) -> str:
    v = (value or "").strip()
    if not v:
        return ""
    if len(v) <= keep:
        return "*" * len(v)
    return v[:keep] + "*" * (len(v) - keep)


@email_app.command("status")
def email_status():
    """Show email transport config: which provider is active, sender address,
    default recipient, BCC, reply-to, and the gates that
    govern automated sends.
    """
    email_transport = os.getenv("EMAIL_TRANSPORT", "").strip()
    zoho_refresh = os.getenv("ZOHO_MAIL_REFRESH_TOKEN", "").strip()
    zoho_client = os.getenv("ZOHO_MAIL_CLIENT_ID", "").strip()
    zoho_secret = os.getenv("ZOHO_MAIL_CLIENT_SECRET", "").strip()
    zoho_account = os.getenv("ZOHO_MAIL_ACCOUNT_ID", "").strip()
    zoho_from = os.getenv("ZOHO_MAIL_FROM_ADDRESS", "").strip()
    resend_key = os.getenv("RESEND_API_KEY", "").strip()
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_user = os.getenv("SMTP_USERNAME", "").strip()
    smtp_pass = os.getenv("SMTP_PASSWORD", "").strip()
    smtp_from = os.getenv("SMTP_FROM_EMAIL", "").strip()
    fallback_from = os.getenv("RESEND_FALLBACK_FROM", "").strip()
    allowed_from = os.getenv("EMAIL_ALLOWED_FROM_ADDRESSES", "").strip()
    thread_from = os.getenv("THREAD_REPLY_FROM_EMAIL", "").strip()
    recipient = os.getenv("EMAIL_NOTIFICATION_RECIPIENT", "").strip()
    reply_to = os.getenv("REPLY_TO_EMAIL", "").strip()
    bcc = os.getenv("BCC_EMAIL", "").strip()
    vm_gate = os.getenv("ALLOW_VOICEMAIL_EMAIL", "false").strip().lower() in {"1", "true", "yes", "on"}

    if email_transport:
        transport = email_transport
    elif zoho_refresh:
        transport = "zoho_api (HTTPS)"
    elif smtp_host:
        transport = f"smtp ({smtp_host}:{os.getenv('SMTP_PORT','587')})"
    elif resend_key:
        transport = "resend (HTTPS)"
    else:
        transport = "[red]NOT CONFIGURED[/red]"

    table = Table(show_header=False, box=None)
    table.add_column("key", style="dim")
    table.add_column("value")
    table.add_row("transport", transport)
    table.add_row("EMAIL_TRANSPORT", email_transport or "—")
    table.add_row("ZOHO_MAIL_CLIENT_ID", _mask(zoho_client, 6) or "—")
    table.add_row("ZOHO_MAIL_CLIENT_SECRET", _mask(zoho_secret, 0) or "—")
    table.add_row("ZOHO_MAIL_REFRESH_TOKEN", _mask(zoho_refresh, 6) or "—")
    table.add_row("ZOHO_MAIL_ACCOUNT_ID", zoho_account or "—")
    table.add_row("ZOHO_MAIL_FROM_ADDRESS", zoho_from or "—")
    table.add_row("RESEND_API_KEY", _mask(resend_key, 6) or "—")
    table.add_row("SMTP_HOST", smtp_host or "—")
    table.add_row("SMTP_USERNAME", smtp_user or "—")
    table.add_row("SMTP_PASSWORD", _mask(smtp_pass, 0) or "—")
    table.add_row("SMTP_FROM_EMAIL", smtp_from or "—")
    table.add_row("RESEND_FALLBACK_FROM", fallback_from or "—")
    table.add_row("EMAIL_ALLOWED_FROM_ADDRESSES", allowed_from or "—")
    table.add_row("THREAD_REPLY_FROM_EMAIL", thread_from or "—")
    table.add_row("EMAIL_NOTIFICATION_RECIPIENT", recipient or "—")
    table.add_row("REPLY_TO_EMAIL", reply_to or "—")
    table.add_row("BCC_EMAIL", bcc or "—")
    table.add_row("ALLOW_VOICEMAIL_EMAIL", "[green]true[/green]" if vm_gate else "[yellow]false[/yellow] (VM follow-ups blocked)")
    console.print(table)

    if not (zoho_refresh or resend_key or smtp_host):
        console.print("[yellow]No transport configured — set Zoho API, RESEND_API_KEY, or SMTP_HOST in .env.[/yellow]")
    if not recipient:
        console.print("[yellow]EMAIL_NOTIFICATION_RECIPIENT unset — `email test` needs --to or this var.[/yellow]")


@email_app.command("test")
def email_test(
    to: str = typer.Option("", "--to", help="Recipient. Defaults to EMAIL_NOTIFICATION_RECIPIENT."),
    from_addr: str = typer.Option(
        "",
        "--from",
        help=(
            "Optional From header. Must match a configured/allowed sender "
            "address and be accepted by the active transport."
        ),
    ),
    subject: str = typer.Option("Possible OS test email", "--subject"),
    body: str = typer.Option(
        "If you can read this, the Possible OS email pipeline works.",
        "--body",
    ),
):
    """Send a plain test email through the configured transport. Useful for
    verifying Resend/SMTP credentials end-to-end without firing a real
    follow-up template.
    """
    from app.services.email_notification_service import _send_email
    recipient = (to or os.getenv("EMAIL_NOTIFICATION_RECIPIENT", "")).strip()
    if not recipient:
        console.print("[red]No recipient. Pass --to or set EMAIL_NOTIFICATION_RECIPIENT.[/red]")
        raise typer.Exit(code=1)
    try:
        msg_id = _send_email(subject, body, to=recipient, from_addr=from_addr or None)
    except Exception as e:
        console.print(f"[red]Send failed: {e}[/red]")
        raise typer.Exit(code=1) from e
    console.print(f"[green]Sent[/green] to {recipient} (id={msg_id or '—'})")


@email_app.command("send-onepager")
def email_send_onepager(
    to: str = typer.Option(..., "--to", help="Recipient email."),
    name: str = typer.Option("there", "--name", help="Lead first name (used in greeting)."),
    firm: str = typer.Option("", "--firm", help="Firm name (currently informational)."),
    note: str = typer.Option("", "--note", help="Optional custom paragraph prepended to the body."),
    rep_name: str = typer.Option("", "--rep-name", help="Defaults to SALES_REP_NAME."),
    rep_company: str = typer.Option("", "--rep-company", help="Defaults to SALES_REP_COMPANY."),
    rep_email: str = typer.Option("", "--rep-email", help="Defaults to SALES_REP_EMAIL."),
):
    """Send the post-call one-pager follow-up email (the same template the
    AI fires from `send_followup_email` mid-call).
    """
    from app.services.email_notification_service import send_followup_email
    rn = rep_name or os.getenv("SALES_REP_NAME", "Alex")
    rc = rep_company or os.getenv("SALES_REP_COMPANY", "Possible Minds")
    re_ = rep_email or os.getenv("SALES_REP_EMAIL", "")
    ok = _run(send_followup_email(
        to_email=to,
        lead_name=name,
        firm_name=firm,
        message_type="one_pager",
        custom_note=note,
        rep_name=rn,
        rep_company=rc,
        rep_email=re_,
    ))
    if not ok:
        console.print(f"[red]Send failed (likely SMTP unconfigured — check `email status`).[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]One-pager sent[/green] to {to} (rep={rn} <{re_}>)")


@email_app.command("send-vm-followup")
def email_send_vm_followup(
    to: str = typer.Option(..., "--to", help="Recipient email."),
    first_name: str = typer.Option("", "--first-name", help="Lead first name (used in greeting)."),
    no_vm: bool = typer.Option(
        False, "--no-vm",
        help="Use the 'tried to reach you' subject/opener (no voicemail was left).",
    ),
):
    """Send the VM / no-reach follow-up email (the same template
    `followups send-voicemail` fires, but to an arbitrary address — useful
    for previewing copy without a call_id).

    Gated by ALLOW_VOICEMAIL_EMAIL=true, same as the automated path.
    """
    from app.services.email_notification_service import send_voicemail_followup_email
    delivered, note = send_voicemail_followup_email(
        to_email=to, first_name=first_name, voicemail_left=not no_vm,
    )
    if not delivered:
        console.print(f"[red]Not delivered:[/red] {note}")
        raise typer.Exit(code=1)
    console.print(f"[green]VM follow-up sent[/green] to {to} (id={note})")


@email_app.command("send-consult")
def email_send_consult(
    to: str = typer.Option(..., "--to", help="Booker's email."),
    name: str = typer.Option(..., "--name", help="Booker's full name."),
    firm: str = typer.Option("", "--firm", help="Firm name (optional)."),
    slot: str = typer.Option(
        ..., "--slot",
        help='PT-formatted slot string, e.g. "Wed Apr 30 at 2:00 PM PT".',
    ),
    notes: str = typer.Option("", "--notes", help="Optional focus area the booker mentioned."),
):
    """Send a consult-booking confirmation email (the same one fired when a
    Cal.com booking is created). Includes the Google Meet link from
    CONSULT_MEET_URL.
    """
    from app.services.email_notification_service import send_consult_confirmation
    try:
        msg_id = send_consult_confirmation(
            to_email=to, name=name, firm_name=firm or None,
            slot_local_str=slot, notes=notes or None,
        )
    except Exception as e:
        console.print(f"[red]Send failed: {e}[/red]")
        raise typer.Exit(code=1) from e
    console.print(f"[green]Consult confirmation sent[/green] to {to} (id={msg_id or '—'})")


# ---------------------------------------------------------------------------
# comms — outbound communications dashboard (read-only)
# ---------------------------------------------------------------------------

_CHANNEL_GLYPH = {
    "call": "📞",
    "voicemail": "📼",
    "email": "📧",
    "sms": "💬",
}


@comms_app.command("list")
def comms_list(
    firm: str = typer.Option("", "--firm", help="Filter to one pif_id."),
    channel: str = typer.Option(
        "", "--channel",
        help="One of: call, voicemail, email, sms. Empty = all.",
    ),
    since: str = typer.Option(
        "", "--since",
        help="Lookback window: '7d' / '24h' / ISO8601. Empty = no lower bound.",
    ),
    status: str = typer.Option("", "--status", help="Filter by exact status string."),
    q: str = typer.Option("", "--q", help="Free-text over recipient/contact/firm/summary."),
    limit: int = typer.Option(50, "--limit", min=1, max=500),
    raw: bool = typer.Option(False, "--raw/--table", help="Print JSON instead of a table."),
):
    """List outbound communications across all channels.

    Reads from the running daemon. Mirrors the /comms UI page.
    """
    if firm:
        path = f"/api/firms/{firm}/communications"
    else:
        path = "/api/communications"
    params = {"limit": limit}
    if channel:
        params["channel"] = channel
    if since:
        params["since"] = since
    if status:
        params["status"] = status
    if q:
        params["q"] = q
    data = _get(path, **params)

    if raw:
        console.print_json(data=data)
        return

    items = data.get("items", [])
    if not items:
        console.print("[dim]No communications match the filter.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("when (UTC)", style="dim", no_wrap=True)
    table.add_column("ch", no_wrap=True)
    table.add_column("firm")
    table.add_column("contact")
    table.add_column("recipient")
    table.add_column("summary", max_width=60)
    table.add_column("status", no_wrap=True)
    for it in items:
        ts = (it.get("occurred_at") or "")[:19].replace("T", " ")
        ch = it.get("channel") or "?"
        glyph = f"{_CHANNEL_GLYPH.get(ch, '·')} {ch}"
        table.add_row(
            ts,
            glyph,
            (it.get("firm_name") or "—")[:32],
            (it.get("contact_name") or "—")[:24],
            (it.get("recipient") or "—")[:32],
            (it.get("summary") or "")[:60],
            it.get("status") or "—",
        )
    console.print(table)
    console.print(f"[dim]{len(items)} item(s)[/dim]")


@comms_app.command("show")
def comms_show(
    item_id: str = typer.Argument(
        ...,
        help='Channel-prefixed id: "call:<call_id>", "email:<id>", or "sms:<id>".',
    ),
):
    """Print one communication as pretty JSON.

    Looks the row up directly in the source table — call_logs for
    "call:" / "voicemail:" prefixes, email_logs for "email:", sms_logs
    for "sms:".
    """
    if ":" not in item_id:
        console.print(
            "[red]ID must be channel-prefixed: call:<call_id> | email:<id> | sms:<id>[/red]"
        )
        raise typer.Exit(code=2)
    kind, ref = item_id.split(":", 1)
    kind = kind.lower()

    async def _fetch() -> dict:
        from sqlalchemy import select
        from app.db import AsyncSessionLocal
        from app.db.models import CallLogRow, EmailLogRow, SmsLogRow
        async with AsyncSessionLocal() as session:
            if kind in ("call", "voicemail"):
                row = (await session.execute(
                    select(CallLogRow).where(CallLogRow.call_id == ref)
                )).scalar_one_or_none()
                if not row:
                    return {}
                return {
                    "kind": "call",
                    "call_id": row.call_id,
                    "patient_id": row.patient_id,
                    "patient_name": row.patient_name,
                    "firm_name": row.firm_name,
                    "phone": row.phone,
                    "started_at": row.started_at.isoformat() if row.started_at else None,
                    "ended_at": row.ended_at.isoformat() if row.ended_at else None,
                    "duration_seconds": row.duration_seconds,
                    "outcome": row.outcome,
                    "voicemail_left": row.voicemail_left,
                    "call_summary": row.call_summary,
                    "judge_score": row.judge_score,
                    "gtm_disposition": row.gtm_disposition,
                    "voice_provider": row.voice_provider,
                    "carrier": row.carrier,
                }
            if kind == "email":
                row = (await session.execute(
                    select(EmailLogRow).where(EmailLogRow.id == ref)
                )).scalar_one_or_none()
                if not row:
                    return {}
                return {
                    "kind": "email",
                    "id": row.id,
                    "pif_id": row.pif_id,
                    "call_id": row.call_id,
                    "recipient_email": row.recipient_email,
                    "recipient_name": row.recipient_name,
                    "subject": row.subject,
                    "body_excerpt": row.body_excerpt,
                    "message_type": row.message_type,
                    "transport": row.transport,
                    "message_id": row.message_id,
                    "status": row.status,
                    "error": row.error,
                    "sent_at": row.sent_at.isoformat() if row.sent_at else None,
                }
            if kind == "sms":
                row = (await session.execute(
                    select(SmsLogRow).where(SmsLogRow.id == ref)
                )).scalar_one_or_none()
                if not row:
                    return {}
                return {
                    "kind": "sms",
                    "id": row.id,
                    "pif_id": row.pif_id,
                    "call_id": row.call_id,
                    "recipient_phone": row.recipient_phone,
                    "recipient_name": row.recipient_name,
                    "body": row.body,
                    "message_sid": row.message_sid,
                    "status": row.status,
                    "error": row.error,
                    "sent_at": row.sent_at.isoformat() if row.sent_at else None,
                }
            return {}

    result = _run(_fetch())
    if not result:
        console.print(f"[red]Not found: {item_id}[/red]")
        raise typer.Exit(code=1)
    console.print_json(data=result)


@leads_app.command("warm-list")
def leads_warm_list(
    limit: int = typer.Option(20, "--limit", "-n", min=1, max=100),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """List top Front-warmed firms with named contacts not yet emailed."""
    from app.services.front_sync import warm_list

    rows = _run(warm_list(limit=limit))
    if json_output:
        console.print_json(data={"warm_list": rows})
        return
    table = Table(title=f"Front warm list ({len(rows)})")
    for col in ["score", "domain", "pif_id", "contact", "email", "last_seen", "tech"]:
        table.add_column(col, overflow="fold")
    for row in rows:
        table.add_row(
            str(row.get("warm_score") or 0),
            str(row.get("domain") or ""),
            str(row.get("pif_id") or ""),
            str(row.get("contact_name") or ""),
            _mask_email(row.get("contact_email")),
            str(row.get("last_seen_at") or row.get("last_referral_at") or ""),
            json.dumps(row.get("tech_signals") or {}, sort_keys=True),
        )
    console.print(table)


# ---------------------------------------------------------------------------
# contacts — firm_contacts roster (backfill + list)
# ---------------------------------------------------------------------------

@contacts_app.command("backfill")
def contacts_backfill(
    limit: int = typer.Option(0, "--limit", help="Cap firms processed (0 = all)."),
):
    """Pull leadership rosters from PIF Stats + the Possible OS DM rows
    into `firm_contacts`. Idempotent — re-running is a near-no-op."""
    from app.services.firm_contacts_service import backfill_all
    res = _run(backfill_all(limit=limit or None))
    console.print_json(data=res)


@contacts_app.command("list")
def contacts_list(
    firm: str = typer.Option("", "--firm", help="Filter to one pif_id."),
    limit: int = typer.Option(50, "--limit", min=1, max=500),
):
    """List firm_contacts rows."""
    from app.services.firm_contacts_service import (
        list_contacts_for_firm, list_firms_with_contacts,
    )
    if firm:
        rows = _run(list_contacts_for_firm(firm))
    else:
        firms = _run(list_firms_with_contacts())
        rows = []
        for f in firms[:limit]:
            for c in _run(list_contacts_for_firm(f["pif_id"])):
                rows.append({**c, "firm_name": f["firm_name"]})
                if len(rows) >= limit:
                    break
            if len(rows) >= limit:
                break

    if not rows:
        console.print("[dim]No contacts. Run `possibleos contacts backfill` first.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("contact_id", no_wrap=True)
    table.add_column("firm" if not firm else "title")
    table.add_column("name")
    table.add_column("email")
    table.add_column("phone", no_wrap=True)
    table.add_column("source", no_wrap=True)
    for r in rows:
        table.add_row(
            r["id"][:8] + "…",
            (r.get("firm_name") if not firm else r.get("title")) or "—",
            r["full_name"] or "—",
            r.get("email") or "—",
            r.get("phone") or "—",
            r.get("source", "—"),
        )
    console.print(table)
    console.print(f"[dim]{len(rows)} contact(s)[/dim]")


# ---------------------------------------------------------------------------
# research / personas — PIF Stats warm research orchestration
# ---------------------------------------------------------------------------

def _parse_research_kinds(raw: str) -> list[str]:
    from app.services.firm_research import normalize_kinds

    parts = [p.strip() for p in (raw or "").split(",") if p.strip()]
    return normalize_kinds(parts or None)


def _print_research_tasks(tasks: list[dict[str, Any]]) -> None:
    table = Table(title=f"Research tasks ({len(tasks)})")
    for col in ["kind", "task_id", "pif_id", "status"]:
        table.add_column(col, overflow="fold")
    for row in tasks:
        table.add_row(
            str(row.get("kind") or ""),
            str(row.get("task_id") or ""),
            str(row.get("pif_id") or ""),
            str(row.get("status") or ""),
        )
    console.print(table)


@research_app.command("firm")
def research_firm_cmd(
    domain_or_pif: str = typer.Argument(..., help="Warm-list domain or upstream PIF ID."),
    staff: bool = typer.Option(True, "--staff/--no-staff", help="Queue staff research too."),
    behavior: bool = typer.Option(False, "--behavior", help="Queue behavior analysis too."),
    poll: bool = typer.Option(False, "--poll", help="Poll queued/open tasks after queueing."),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """Queue research for one firm. Safe POST budget defaults to 30/run."""
    from app.services.firm_research import poll_research_tasks, queue_firm_research, resolve_domain_or_pif

    async def _run_one():
        pif_id = await resolve_domain_or_pif(domain_or_pif)
        queued = await queue_firm_research(pif_id, staff=staff, behavior=behavior)
        polled = None
        if poll:
            task_ids = [row["task_id"] for row in queued.get("queued") or []]
            polled = await poll_research_tasks(task_ids=task_ids or None)
        return {"pif_id": pif_id, "queue": queued, "poll": polled}

    data = _run(_run_one())
    if json_output:
        console.print_json(data=data)
        return
    queue = data["queue"]
    console.print(
        f"pif_id={data['pif_id']} queued={len(queue.get('queued') or [])} "
        f"skipped={len(queue.get('skipped') or [])} posts={queue.get('budget', {}).get('task_posts_made')}"
    )
    _print_research_tasks([{**row, "pif_id": data["pif_id"]} for row in queue.get("queued") or []])
    if queue.get("skipped"):
        console.print_json(data={"skipped": queue["skipped"]})
    if data.get("poll"):
        console.print_json(data=data["poll"])


@research_app.command("warm")
def research_warm_cmd(
    top: int = typer.Option(50, "--top", min=1, max=100, help="Warm firms to inspect."),
    kinds: str = typer.Option("research,staff", "--kinds", help="Comma-separated: research,staff,behavior."),
    timeout: int = typer.Option(1800, "--timeout", min=1, max=1800, help="Poll timeout seconds."),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """Research the warm list on demand with hard POST budget and resume."""
    from app.services.firm_research import orchestrate_warm_research

    data = _run(orchestrate_warm_research(top_n=top, kinds=_parse_research_kinds(kinds), timeout_seconds=timeout))
    if json_output:
        console.print_json(data=data)
        return
    console.print(
        f"warm top={top} queued={len(data.get('queued_task_ids') or [])} "
        f"posts={data.get('budget', {}).get('task_posts_made')} timed_out={data.get('timed_out')}"
    )
    tasks = []
    for result in data.get("queue_results") or []:
        for row in result.get("queued") or []:
            tasks.append({**row, "pif_id": result.get("pif_id")})
    _print_research_tasks(tasks)
    poll_data = data.get("poll") or {}
    console.print(
        f"poll polled={poll_data.get('polled', 0)} completed={poll_data.get('completed', 0)} "
        f"failed={poll_data.get('failed', 0)} open={poll_data.get('open', 0)}"
    )


@research_app.command("status")
def research_status_cmd(
    tasks: bool = typer.Option(False, "--tasks", help="Print open task rows."),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """Show research coverage counts and open tasks."""
    from app.services.firm_research import research_coverage

    data = _run(research_coverage())
    if json_output:
        console.print_json(data=data)
        return
    coverage = data.get("coverage") or {}
    console.print(
        f"matched={coverage.get('matched_firms')} researched={coverage.get('researched_firms')} "
        f"({coverage.get('research_percent')}%) staff={coverage.get('staff_researched_firms')} "
        f"behavior={coverage.get('behavior_analyzed_firms')} open_tasks={len(data.get('open_tasks') or [])}"
    )
    if tasks:
        _print_research_tasks(data.get("open_tasks") or [])


@research_app.command("sync")
def research_sync_cmd(json_output: bool = typer.Option(False, "--json", help="Print raw JSON.")):
    """Poll and upsert queued/running research tasks without queueing new work."""
    from app.services.firm_research import poll_research_tasks

    data = _run(poll_research_tasks())
    if json_output:
        console.print_json(data=data)
        return
    console.print(
        f"polled={data.get('polled')} completed={data.get('completed')} "
        f"failed={data.get('failed')} open={data.get('open')}"
    )
    _print_research_tasks(data.get("tasks") or [])


@personas_app.command("map")
def personas_map_cmd(
    pif: str = typer.Option("", "--pif", help="Limit to one PIF ID."),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """Map firm_contacts titles/emails to composer persona keys."""
    from app.services.persona_mapper import map_personas

    data = _run(map_personas(pif_id=pif or None))
    if json_output:
        console.print_json(data=data)
        return
    console.print(f"scanned={data.get('scanned')} updated={data.get('updated')} skipped={data.get('skipped')}")


@personas_app.command("show")
def personas_show_cmd(
    domain: str = typer.Argument(..., help="Warm-list domain or PIF ID."),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """Show contacts and mapped personas for a firm."""
    from app.services.firm_research import personas_for_domain

    data = _run(personas_for_domain(domain))
    if json_output:
        console.print_json(data=data)
        return
    table = Table(title=f"Personas for {domain}")
    for col in ["name", "email", "title", "persona", "source", "conf"]:
        table.add_column(col, overflow="fold")
    for row in data.get("contacts") or []:
        table.add_row(
            row.get("name") or "—",
            _mask_email(row.get("email")),
            row.get("title") or "—",
            row.get("persona") or "—",
            row.get("persona_source") or "—",
            str(row.get("persona_confidence") if row.get("persona_confidence") is not None else "—"),
        )
    console.print(table)


# ---------------------------------------------------------------------------
# front — Precise Front enrichment sync
# ---------------------------------------------------------------------------

@front_app.command("sync")
def front_sync_cmd(
    full: bool = typer.Option(False, "--full", help="Ignore saved cursors/watermarks for this run."),
    max_calls: int = typer.Option(300, "--max-calls", min=1, max=300, help="Hard Front API call budget for this run."),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """Run a budgeted Front contacts/activity sync, then resolve and score offline."""
    from app.services.front_sync import list_front_contacts, run_front_sync

    async def _run_sync_and_samples():
        sync_data = await run_front_sync(max_calls=max_calls, full=full)
        return sync_data, await list_front_contacts(limit=3)

    data, samples = _run(_run_sync_and_samples())
    if json_output:
        console.print_json(data=data)
        return
    contacts = data.get("contacts") or {}
    activity = data.get("activity") or {}
    resolve = data.get("resolve") or {}
    scores = data.get("scores") or {}
    counts = (data.get("status") or {}).get("counts") or {}
    console.print(
        f"contacts fetched={contacts.get('fetched')} upserted={contacts.get('upserted')} "
        f"activity fetched={activity.get('fetched', 0)} "
        f"calls={max(int(contacts.get('calls_made') or 0), int(activity.get('calls_made') or 0))}"
    )
    console.print(
        f"front_contacts={counts.get('front_contacts')} activity_domains={counts.get('front_firm_activity')} "
        f"matched_domains={counts.get('matched_domains')} warm_domains={counts.get('warm_domains')} "
        f"resolved_contacts={resolve.get('upserted_contacts')} warm_scores_updated={scores.get('updated')}"
    )
    if samples:
        table = Table(title="Sample Front contacts")
        for col in ["front_id", "name", "email", "domain", "pif_id", "warm"]:
            table.add_column(col, overflow="fold")
        for row in samples:
            table.add_row(
                str(row.get("front_id") or ""),
                str(row.get("name") or ""),
                _mask_email(row.get("primary_email")),
                str(row.get("domain") or ""),
                str(row.get("pif_id") or ""),
                str(row.get("warm_score") or 0),
            )
        console.print(table)


@front_app.command("status")
def front_status_cmd(json_output: bool = typer.Option(False, "--json", help="Print raw JSON.")):
    """Show Front sync cursors, watermarks, counts, and last synced row."""
    from app.services.front_sync import front_status

    data = _run(front_status())
    if json_output:
        console.print_json(data=data)
        return
    counts = data.get("counts") or {}
    console.print(
        f"front_contacts={counts.get('front_contacts')} activity_domains={counts.get('front_firm_activity')} "
        f"matched_domains={counts.get('matched_domains')} warm_domains={counts.get('warm_domains')}"
    )
    table = Table(title="Front sync state")
    for col in ["key", "watermark", "updated", "cursor"]:
        table.add_column(col, overflow="fold")
    for row in data.get("states") or []:
        table.add_row(
            str(row.get("key") or ""),
            str(row.get("watermark") or ""),
            str(row.get("updated_at") or ""),
            str(row.get("cursor") or "")[:80],
        )
    console.print(table)


@front_app.command("contacts")
def front_contacts_cmd(
    firm: str = typer.Option("", "--firm", help="Filter by matched pif_id."),
    domain: str = typer.Option("", "--domain", help="Filter by email/domain."),
    q: str = typer.Option("", "--q", help="Search name, email, domain, or pif_id."),
    limit: int = typer.Option(50, "--limit", "-n", min=1, max=500),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """List synced Front contacts with matched firm and warmth metadata."""
    from app.services.front_sync import list_front_contacts

    rows = _run(list_front_contacts(firm=firm, domain=domain, q=q, limit=limit))
    if json_output:
        console.print_json(data={"contacts": rows})
        return
    table = Table(title=f"Front contacts ({len(rows)})")
    for col in ["front_id", "name", "email", "domain", "pif_id", "warm", "tech"]:
        table.add_column(col, overflow="fold")
    for row in rows:
        table.add_row(
            str(row.get("front_id") or ""),
            str(row.get("name") or ""),
            _mask_email(row.get("primary_email")),
            str(row.get("domain") or ""),
            str(row.get("pif_id") or ""),
            str(row.get("warm_score") or 0),
            json.dumps(row.get("tech_signals") or {}, sort_keys=True),
        )
    console.print(table)


@front_app.command("warm-batch")
def front_warm_batch_cmd(
    domains: str = typer.Option(..., "--domains", help="Comma-separated synced Front domains to include."),
    name: str = typer.Option("", "--name", help="Optional lead-gen batch name."),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """Create a recommended lead-gen batch from selected Front-warm domains."""
    from app.services.front_sync import create_front_warm_batch

    domain_list = [part.strip() for part in domains.split(",") if part.strip()]
    try:
        data = _run(create_front_warm_batch(
            domains=domain_list,
            name=name or None,
            created_by="operator-cli",
        ))
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
    if json_output:
        console.print_json(data=data)
        return
    batch = data.get("batch") or {}
    items = data.get("items") or []
    link = data.get("link") or f"/lead-gen?batch={batch.get('id')}"
    console.print(f"created batch={batch.get('id')} items={len(items)} link={link}")
    table = Table(title="Front warm batch items")
    for col in ["score", "domain", "firm", "contact", "email"]:
        table.add_column(col, overflow="fold")
    for item in items:
        reason = item.get("reason") or {}
        features = reason.get("selection_features") or {}
        table.add_row(
            str(item.get("score") or 0),
            str(features.get("domain") or ""),
            str(item.get("firm_name") or ""),
            str(item.get("contact_name") or ""),
            _mask_email(item.get("contact_email")),
        )
    console.print(table)


@front_competitors_app.command("rebuild")
def front_competitors_rebuild_cmd(
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """Rebuild the local firm-vs-firm competition graph from cached data."""
    from app.services.competitor_graph import rebuild_competitor_graph

    data = _run(rebuild_competitor_graph())
    if json_output:
        console.print_json(data=data)
        return
    console.print(
        f"features={data.get('firms_with_features')} with_metro={data.get('firms_with_metro')} "
        f"with_case_mix={data.get('firms_with_case_mix')} edges={data.get('edge_count')} "
        f"excluded_non_competitors={data.get('excluded_non_competitors')} "
        f"client_switching_hits={data.get('client_switching_hit_count')} duration={data.get('duration_seconds')}s"
    )


@front_competitors_app.command("summary")
def front_competitors_summary_cmd(
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """Show competitor graph coverage, edge count, and tier distribution."""
    from app.services.competitor_graph import competitor_summary

    data = _run(competitor_summary())
    if json_output:
        console.print_json(data=data)
        return
    console.print(
        f"features={data.get('firms_with_features')} with_metro={data.get('firms_with_metro')} "
        f"edges={data.get('edge_count')} last={data.get('last_computed_at') or 'never'}"
    )
    table = Table(title="Competitor graph metros")
    table.add_column("metro", overflow="fold")
    table.add_column("firms", justify="right")
    for row in (data.get("metro_counts") or [])[:12]:
        table.add_row(str(row.get("metro") or ""), str(row.get("count") or 0))
    console.print(table)
    console.print(f"tiers={json.dumps(data.get('tier_distribution') or {}, sort_keys=True)}")


@front_competitors_app.command("show")
def front_competitors_show_cmd(
    identifier: str = typer.Argument(..., help="Firm domain, PIF id, or firm-name fragment."),
    limit: int = typer.Option(10, "--limit", "-n", min=1, max=50),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """Show who competes with one firm."""
    from app.services.competitor_graph import get_competitors
    from app.services.front_sync import normalize_domain

    domain = normalize_domain(identifier) if "." in identifier else ""
    data = _run(get_competitors(domain=domain, pif_id=identifier if not domain else "", q=identifier, limit=limit))
    if json_output:
        console.print_json(data=data)
        return
    firm = data.get("firm")
    if not firm:
        console.print(f"[red]No competitor graph feature found for {identifier}[/red]")
        raise typer.Exit(code=1)
    console.print(
        f"{firm.get('firm_name')} ({firm.get('domain') or firm.get('pif_id')}) "
        f"metro={firm.get('metro') or 'unknown'} tier={firm.get('value_tier') or 'unknown'}"
    )
    table = Table(title="Competes with")
    for col in ["score", "firm", "domain", "metro", "why"]:
        table.add_column(col, overflow="fold")
    for row in data.get("competitors") or []:
        evidence = row.get("evidence") or {}
        table.add_row(
            f"{float(row.get('score') or 0):.2f}",
            str(row.get("firm_name") or ""),
            str(row.get("domain") or ""),
            str(row.get("metro") or ""),
            str(evidence.get("why") or ""),
        )
    console.print(table)


@front_competitors_app.command("search")
def front_competitors_search_cmd(
    q: str = typer.Argument(..., help="Firm-name or domain substring."),
    limit: int = typer.Option(10, "--limit", "-n", min=1, max=50),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """Search firms with local competitor features."""
    from app.services.competitor_graph import search_competitor_firms

    try:
        data = _run(search_competitor_firms(q=q, limit=limit))
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if json_output:
        console.print_json(data=data)
        return
    rows = data.get("results") or []
    table = Table(title="Competitor firm search")
    for col in ["firm", "domain", "metro", "tier", "edges", "warm"]:
        table.add_column(col, overflow="fold")
    for row in rows:
        table.add_row(
            str(row.get("firm_name") or ""),
            str(row.get("domain") or ""),
            str(row.get("metro") or ""),
            str(row.get("value_tier") or ""),
            str(row.get("edge_count") or 0),
            "yes" if row.get("is_warm_list") else "",
        )
    console.print(table)


@front_competitors_app.command("graph")
def front_competitors_graph_cmd(
    identifier: str = typer.Argument(..., help="Firm domain, PIF id, or firm-name fragment."),
    depth: int = typer.Option(1, "--depth", min=1, max=2, help="Neighborhood depth: 1 or 2 hops."),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """Print an ego-network payload for one firm's competitive neighborhood."""
    from app.services.competitor_graph import get_competitor_graph, get_competitors
    from app.services.front_sync import normalize_domain

    domain = normalize_domain(identifier) if "." in identifier else ""
    async def load_graph():
        resolved = await get_competitors(domain=domain, pif_id=identifier if not domain else "", q=identifier, limit=1)
        firm = resolved.get("firm")
        if not firm:
            return None, None
        graph = await get_competitor_graph(pif_id=str(firm.get("pif_id") or ""), depth=depth)
        return firm, graph

    firm, data = _run(load_graph())
    if not firm:
        console.print(f"[red]No competitor graph feature found for {identifier}[/red]")
        raise typer.Exit(code=1)
    if not data:
        console.print(f"[red]No competitor graph feature found for {identifier}[/red]")
        raise typer.Exit(code=1)
    if json_output:
        console.print_json(data=data)
        return
    nodes = data.get("nodes") or []
    links = data.get("links") or []
    console.print(
        f"{firm.get('firm_name')} ({firm.get('domain') or firm.get('pif_id')}) "
        f"depth={depth} nodes={len(nodes)} links={len(links)}"
    )
    names = {row.get("pif_id"): row.get("firm_name") or row.get("pif_id") for row in nodes}
    table = Table(title="Top graph edges")
    for col in ["score", "source", "target", "why"]:
        table.add_column(col, overflow="fold")
    for row in links[:15]:
        table.add_row(
            f"{float(row.get('score') or 0):.2f}",
            str(names.get(row.get("source"), row.get("source"))),
            str(names.get(row.get("target"), row.get("target"))),
            str(row.get("evidence_summary") or ""),
        )
    console.print(table)


# ---------------------------------------------------------------------------
# sequences — preview + start (strict one-at-a-time)
# ---------------------------------------------------------------------------

@sequences_app.command("preview")
def sequences_preview(
    contact_id: str = typer.Argument(..., help="firm_contacts.id"),
    template_key: str = typer.Option(
        "possible_minds_dynamic",
        "--template-key",
        "--template",
        help="Sequence template key.",
    ),
):
    """Render every step of the sequence for one contact, against their
    real personalization data. Read-only — no DB writes, no sends."""
    data = _get(
        f"/api/contacts/{contact_id}/sequence/preview",
        template_key=template_key,
    )
    for step in data:
        console.print(f"[bold cyan]── Step {step['step']} ──[/bold cyan]")
        console.print(f"[dim]message_type: {step['message_type']}[/dim]")
        console.print(f"[bold]Subject:[/bold] {step['subject']}")
        console.print()
        console.print(step["body"])
        console.print()


@sequences_app.command("start")
def sequences_start(
    contact_id: str = typer.Argument(..., help="firm_contacts.id"),
    template_key: str = typer.Option(
        "possible_minds_dynamic",
        "--template-key",
        "--template",
        help="Sequence template key.",
    ),
):
    """Start the configured email sequence for one contact. Idempotent — second
    start returns 409 with current state.

    The scheduler picks step 1 up within ~60s. Sends are gated by
    ALLOW_SEQUENCE_SEND=true; without that env var, the row sits
    active and ticks no-op until the gate is opened."""
    res = _post(
        f"/api/contacts/{contact_id}/sequence/start",
        json_body={"template_key": template_key},
    )
    console.print_json(data=res)


@sequences_app.command("pause")
def sequences_pause(
    contact_id: str = typer.Argument(..., help="firm_contacts.id"),
    reason: str = typer.Option("", "--reason", "-r", help="Why you're pausing — recorded on the row."),
    template_key: str = typer.Option(
        "possible_minds_dynamic",
        "--template-key",
        "--template",
        help="Sequence template key.",
    ),
):
    """Pause an active sequence. Scheduler will skip it; no further
    sends fire until `sequences resume`."""
    res = _post(
        f"/api/contacts/{contact_id}/sequence/pause?template_key={template_key}",
        json_body={"reason": reason},
    )
    console.print_json(data=res)


@sequences_app.command("resume")
def sequences_resume(
    contact_id: str = typer.Argument(..., help="firm_contacts.id"),
    template_key: str = typer.Option(
        "possible_minds_dynamic",
        "--template-key",
        "--template",
        help="Sequence template key.",
    ),
):
    """Flip a paused sequence back to active. The next due step fires
    on the scheduler's next tick (≤60s)."""
    res = _post(f"/api/contacts/{contact_id}/sequence/resume?template_key={template_key}")
    console.print_json(data=res)


@sequences_app.command("templates")
def sequences_templates():
    """List selectable sequence templates."""
    rows = _get("/api/sequences/templates")
    table = Table(show_header=True, header_style="bold")
    table.add_column("template_key", no_wrap=True)
    table.add_column("label")
    table.add_column("steps", no_wrap=True)
    table.add_column("variant", no_wrap=True)
    table.add_column("description")
    for r in rows:
        table.add_row(
            r["template_key"],
            r["label"],
            str(r["steps_total"]),
            r["default_variant"],
            r.get("description") or "",
        )
    console.print(table)


@sequences_app.command("recommend")
def sequences_recommend(
    template_key: str = typer.Option(
        "possible_minds_dynamic",
        "--template-key",
        "--template",
        help="Strategy/composer template key.",
    ),
    limit: int = typer.Option(50, "--limit", "-n", min=1, max=200),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """Recommend next contacts for human approval.

    Suppresses firms already present in the comms feed and firms with any
    existing sequence row. Returns one founder/COO-style contact per firm.
    """
    data = _get(
        "/api/sequences/recommendations",
        template_key=template_key,
        limit=limit,
    )
    if json_output:
        console.print_json(data=data)
        return
    counts = data.get("counts") or {}
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", justify="right", no_wrap=True)
    table.add_column("firm")
    table.add_column("contact")
    table.add_column("title")
    table.add_column("email")
    table.add_column("score", justify="right", no_wrap=True)
    table.add_column("reason")
    for i, r in enumerate(data.get("recommended") or [], start=1):
        table.add_row(
            str(i),
            r["firm_name"],
            r["contact_name"] or "—",
            r["contact_title"] or "—",
            r["contact_email"],
            str(r["score"]),
            r["reason"],
        )
    console.print(table)
    console.print(
        "[dim]"
        f"template={data.get('template_key')} returned={counts.get('returned')} "
        f"eligible_firms={counts.get('eligible_firms')} "
        f"contacted_firms={counts.get('contacted_firms')} "
        f"sequenced_firms={counts.get('sequenced_firms')}"
        "[/dim]"
    )


@sequences_app.command("list")
def sequences_list(
    status: str = typer.Option("", "--status", help="active | paused | completed"),
):
    """List sequence rows. Reads the DB directly."""
    async def _q():
        from sqlalchemy import select
        from app.db import AsyncSessionLocal
        from app.db.models import EmailSequenceRow, FirmContactRow
        async with AsyncSessionLocal() as session:
            q = select(EmailSequenceRow, FirmContactRow).join(
                FirmContactRow,
                EmailSequenceRow.contact_id == FirmContactRow.id,
            ).order_by(EmailSequenceRow.updated_at.desc())
            if status:
                q = q.where(EmailSequenceRow.status == status.strip().lower())
            return list((await session.execute(q)).all())

    rows = _run(_q())
    if not rows:
        console.print("[dim]No sequences match.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("id", no_wrap=True)
    table.add_column("contact")
    table.add_column("email")
    table.add_column("template")
    table.add_column("step", no_wrap=True)
    table.add_column("variant", no_wrap=True)
    table.add_column("status", no_wrap=True)
    table.add_column("next due (UTC)", no_wrap=True)
    for seq, contact in rows:
        nd = seq.next_step_due_at
        table.add_row(
            seq.id[:8] + "…",
            contact.full_name or "—",
            contact.email or "—",
            seq.template_key,
            f"{seq.current_step}/{seq.steps_total}",
            seq.variant,
            seq.status,
            (nd.isoformat()[:19] if nd else "—"),
        )
    console.print(table)
    console.print(f"[dim]{len(rows)} sequence(s)[/dim]")


# ---------------------------------------------------------------------------
# todos — editable project backlog
# ---------------------------------------------------------------------------

@todos_app.command("list")
def todos_list(
    area: str = typer.Option("", "--area", help="Filter by area, e.g. lead-gen."),
    status: str = typer.Option("", "--status", help="Filter by status."),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """List DB-backed project todos."""
    data = _get("/api/todos", area=area or None, status=status or None)
    if json_output:
        console.print_json(data=data)
        return
    rows = data.get("todos") or []
    table = Table(show_header=True, header_style="bold")
    table.add_column("id", no_wrap=True)
    table.add_column("area", no_wrap=True)
    table.add_column("status", no_wrap=True)
    table.add_column("title")
    for row in rows:
        table.add_row(str(row.get("id") or ""), row.get("area") or "", row.get("status") or "", row.get("title") or "")
    console.print(table)


@todos_app.command("add")
def todos_add(
    title: str = typer.Argument(...),
    area: str = typer.Option("general", "--area"),
    section: str = typer.Option("Not Started", "--section"),
    status: str = typer.Option("not_started", "--status"),
    body: str = typer.Option("", "--body"),
    source_url: str = typer.Option("", "--source-url"),
    actor: str = typer.Option("operator", "--actor"),
):
    """Add a DB-backed project todo."""
    data = _post(
        "/api/todos",
        json_body={
            "title": title,
            "area": area,
            "section": section,
            "status": status,
            "body": body,
            "source_url": source_url or None,
            "actor": actor,
        },
    )
    console.print_json(data=data)


@todos_app.command("update")
def todos_update(
    todo_id: int = typer.Argument(...),
    title: str = typer.Option("", "--title"),
    area: str = typer.Option("", "--area"),
    section: str = typer.Option("", "--section"),
    status: str = typer.Option("", "--status"),
    body: str = typer.Option("", "--body"),
    source_url: str = typer.Option("", "--source-url"),
    clear_source_url: bool = typer.Option(False, "--clear-source-url"),
    actor: str = typer.Option("operator", "--actor"),
):
    """Update a DB-backed project todo."""
    payload = {"actor": actor}
    if title:
        payload["title"] = title
    if area:
        payload["area"] = area
    if section:
        payload["section"] = section
    if status:
        payload["status"] = status
    if body:
        payload["body"] = body
    if clear_source_url:
        payload["source_url"] = None
    elif source_url:
        payload["source_url"] = source_url
    data = _patch(f"/api/todos/{todo_id}", json_body=payload)
    console.print_json(data=data)


@todos_app.command("delete")
def todos_delete(
    todo_id: int = typer.Argument(...),
):
    """Delete a DB-backed project todo."""
    console.print_json(data=_delete(f"/api/todos/{todo_id}"))


# ---------------------------------------------------------------------------
# ideas — simple future idea capture
# ---------------------------------------------------------------------------

IDEAS_AREA = "ideas"
LEGACY_IDEA_AREA_PREFIX = "idea:"


def _is_idea_row(row: dict) -> bool:
    area = str(row.get("area") or "")
    return area == IDEAS_AREA or area.startswith(LEGACY_IDEA_AREA_PREFIX)


def _read_idea_text(text: str) -> str:
    if text == "-":
        text = sys.stdin.read()
    text = text.strip()
    if not text:
        console.print("[red]Idea text is required.[/red]")
        raise typer.Exit(code=1)
    return text


def _idea_title(text: str) -> str:
    from datetime import datetime, timezone

    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "Idea")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{first_line[:80]} {stamp}"


def _idea_rows() -> list[dict]:
    data = _get("/api/todos")
    return [row for row in data.get("todos") or [] if _is_idea_row(row)]


def _get_idea_or_exit(idea_id: int) -> dict:
    for row in _idea_rows():
        if int(row.get("id") or 0) == idea_id:
            return row
    console.print(f"[red]Idea {idea_id} not found.[/red]")
    raise typer.Exit(code=1)


@ideas_app.command("list")
def ideas_list(
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """List saved future ideas."""
    rows = list(reversed(_idea_rows()))
    if json_output:
        console.print_json(data={"ideas": rows})
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("id", no_wrap=True)
    table.add_column("updated", no_wrap=True)
    table.add_column("idea")
    for row in rows:
        text = (row.get("body") or row.get("title") or "").strip()
        preview = text.replace("\n", " ")
        if len(preview) > 120:
            preview = f"{preview[:117]}..."
        table.add_row(
            str(row.get("id") or ""),
            str(row.get("updated_at") or row.get("created_at") or ""),
            preview,
        )
    console.print(table)


@ideas_app.command("add")
def ideas_add(
    text: str = typer.Argument(..., help='Idea text. Use "-" to read multiline text from stdin.'),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """Save a future product, marketing, or GTM idea."""
    body = _read_idea_text(text)
    data = _post(
        "/api/todos",
        json_body={
            "title": _idea_title(body),
            "area": IDEAS_AREA,
            "section": "Ideas",
            "status": "raw",
            "body": body,
            "actor": "operator",
        },
    )
    if json_output:
        console.print_json(data=data)
        return
    row = data.get("todo") or {}
    console.print(f"[green]saved idea[/green] {row.get('id')}")


@ideas_app.command("edit")
def ideas_edit(
    idea_id: int = typer.Argument(...),
    text: str = typer.Argument(..., help='Replacement idea text. Use "-" to read multiline text from stdin.'),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """Replace the text for a saved idea."""
    existing = _get_idea_or_exit(idea_id)
    body = _read_idea_text(text)
    data = _patch(
        f"/api/todos/{idea_id}",
        json_body={
            "title": existing.get("title") or _idea_title(body),
            "area": existing.get("area") or IDEAS_AREA,
            "section": existing.get("section") or "Ideas",
            "status": existing.get("status") or "raw",
            "body": body,
            "actor": "operator",
        },
    )
    if json_output:
        console.print_json(data=data)
        return
    console.print(f"[green]updated idea[/green] {idea_id}")


# ---------------------------------------------------------------------------
# actions — durable Possible OS action execution
# ---------------------------------------------------------------------------

@actions_app.command("list")
def actions_list(
    status: str = typer.Option("", "--status", help="Filter by action status."),
    action_type: str = typer.Option("", "--type", help="Filter by action type."),
    scheduled: bool = typer.Option(False, "--scheduled", help="Show only future scheduled approved actions."),
    limit: int = typer.Option(50, "--limit", "-n", min=1, max=500),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """List durable action execution records."""
    data = _get(
        "/api/actions",
        status=status or None,
        action_type=action_type or None,
        scheduled=scheduled or None,
        limit=limit,
    )
    if json_output:
        console.print_json(data=data)
        return
    rows = data.get("actions") or []
    pending_scheduled = data.get("pending_scheduled_count", 0)
    title = f"Scheduled actions ({len(rows)})" if scheduled else f"Actions ({len(rows)}; scheduled pending={pending_scheduled})"
    table = Table(title=title)
    for col in ["id", "type", "status", "risk", "entity", "scheduled", "requested", "approved", "created"]:
        table.add_column(col, overflow="fold")
    for row in rows:
        table.add_row(
            str(row.get("id") or ""),
            str(row.get("action_type") or ""),
            str(row.get("status") or ""),
            str(row.get("risk_level") or ""),
            f"{row.get('entity_type') or ''}:{row.get('entity_id') or ''}",
            str(row.get("scheduled_for") or ""),
            str(row.get("requested_by") or ""),
            str(row.get("approved_by") or ""),
            str(row.get("created_at") or ""),
        )
    console.print(table)


@actions_app.command("scheduler-status")
def actions_scheduler_status(json_output: bool = typer.Option(False, "--json", help="Print raw JSON.")):
    """Show daemon scheduled-action loop status and pending counts."""
    data = _get("/api/actions/scheduler/status")
    if json_output:
        console.print_json(data=data)
        return
    console.print(f"running={data.get('running')}")
    console.print(f"last_tick_at={data.get('last_tick_at') or '-'}")
    console.print(f"pending_count={data.get('pending_count')}")
    console.print(f"due_count={data.get('due_count')}")
    if data.get("last_error"):
        console.print(f"[red]last_error={data.get('last_error')}[/red]")


@actions_app.command("show")
def actions_show(action_id: str = typer.Argument(...), json_output: bool = typer.Option(False, "--json")):
    """Show one action and its event timeline."""
    data = _get(f"/api/actions/{action_id}")
    if json_output:
        console.print_json(data=data)
        return
    console.print_json(data=data.get("action") or {})
    events = data.get("events") or []
    table = Table(title=f"Action events ({len(events)})")
    for col in ["id", "type", "actor", "message", "created"]:
        table.add_column(col, overflow="fold")
    for event in events:
        table.add_row(
            str(event.get("id") or ""),
            str(event.get("event_type") or ""),
            str(event.get("actor") or ""),
            str(event.get("message") or ""),
            str(event.get("created_at") or ""),
        )
    console.print(table)


@actions_app.command("policy-check")
def actions_policy_check(
    action_id: str = typer.Argument(...),
    actor: str = typer.Option("operator", "--actor"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Run policy checks for an action without executing it."""
    data = _post(f"/api/actions/{action_id}/policy-check", json_body={"actor": actor})
    if json_output:
        console.print_json(data=data)
        return
    policy = data.get("policy") or {}
    console.print(f"allowed={policy.get('allowed')} reason={policy.get('reason')}")
    table = Table(title="Policy checks")
    for col in ["check", "passed", "detail"]:
        table.add_column(col, overflow="fold")
    for check in policy.get("checks") or []:
        table.add_row(
            str(check.get("name") or ""),
            "yes" if check.get("passed") else "no",
            str(check.get("detail") or ""),
        )
    console.print(table)


@actions_app.command("execute")
def actions_execute(
    action_id: str = typer.Argument(...),
    actor: str = typer.Option("operator", "--actor"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Execute one policy-approved action."""
    data = _post(f"/api/actions/{action_id}/execute", json_body={"actor": actor}, timeout=120.0)
    if json_output:
        console.print_json(data=data)
        return
    action = data.get("action") or {}
    policy = data.get("policy") or {}
    console.print(
        f"executed={data.get('executed')} status={action.get('status')} "
        f"policy={policy.get('reason')}"
    )


@actions_app.command("cancel")
def actions_cancel(
    action_id: str = typer.Argument(...),
    reason: str = typer.Option("", "--reason", help="Human-readable cancellation reason."),
    actor: str = typer.Option("operator", "--actor", help="Actor recorded on action events/traces."),
    json_output: bool = typer.Option(False, "--json"),
):
    """Cancel a waiting or approved action before it runs."""
    data = _post(
        f"/api/actions/{action_id}/cancel",
        json_body={"actor": actor, "reason": reason},
        timeout=30.0,
    )
    if json_output:
        console.print_json(data=data)
        return
    action = data.get("action") or {}
    console.print(f"action={action.get('id')} status={action.get('status')} cancelled=true")


@actions_app.command("reschedule")
def actions_reschedule(
    action_id: str = typer.Argument(...),
    at: str = typer.Option(..., "--at", help='New send time: ISO-8601 with offset, or "HH:MM PT|PDT|PST" today.'),
    actor: str = typer.Option("operator", "--actor", help="Actor recorded on action events/traces."),
    json_output: bool = typer.Option(False, "--json"),
):
    """Move an approved scheduled action to a new future time."""
    from app.services.scheduled_time import parse_scheduled_time

    try:
        scheduled_for = parse_scheduled_time(at)
    except ValueError as exc:
        console.print(f"[red]Invalid --at: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    data = _post(
        f"/api/actions/{action_id}/reschedule",
        json_body={"actor": actor, "scheduled_for": scheduled_for.isoformat()},
        timeout=30.0,
    )
    if json_output:
        console.print_json(data=data)
        return
    action = data.get("action") or {}
    console.print(
        f"action={action.get('id')} status={action.get('status')} "
        f"{data.get('old_scheduled_for_pt')} ({data.get('old_scheduled_for_utc')}) -> "
        f"{data.get('scheduled_for_pt')} ({data.get('scheduled_for_utc')})"
    )


@actions_app.command("execute-approved-lead-gen")
def actions_execute_approved_lead_gen(
    limit: int = typer.Option(1, "--limit", "-n", min=1, max=25, help="Maximum approved lead-gen email actions to execute."),
    actor: str = typer.Option("operator", "--actor", help="Actor recorded on action events/traces."),
    json_output: bool = typer.Option(False, "--json"),
):
    """Execute approved lead-gen email actions through the durable policy gate."""
    data = _post(
        "/api/actions/lead-gen/execute-approved",
        json_body={"actor": actor, "limit": limit},
        timeout=180.0,
    )
    if json_output:
        console.print_json(data=data)
        return
    console.print(
        f"attempted={data.get('attempted')} executed={data.get('executed')} "
        f"candidates={', '.join(data.get('candidate_action_ids') or []) or '-'}"
    )


@actions_app.command("send-approved-lead-gen-draft")
def actions_send_approved_lead_gen_draft(
    batch_item_id: str = typer.Option(..., "--item", help="Lead-gen batch item id."),
    subject: str = typer.Option(..., "--subject", help="Approved subject."),
    body: str = typer.Option(..., "--body", help="Approved body."),
    approved_by: str = typer.Option("operator", "--approved-by"),
    at: str = typer.Option("", "--at", help='Schedule send time: ISO-8601 with offset, or "HH:MM PT|PDT|PST" today.'),
    execute_now: bool = typer.Option(True, "--execute/--no-execute", help="Execute immediately after creating the action."),
    json_output: bool = typer.Option(False, "--json"),
):
    """Create, policy-check, and optionally execute an approved lead-gen email draft."""
    scheduled_for = None
    if at:
        from app.services.scheduled_time import format_pt, format_utc, parse_scheduled_time
        try:
            scheduled_for = parse_scheduled_time(at)
        except ValueError as exc:
            console.print(f"[red]Invalid --at: {exc}[/red]")
            raise typer.Exit(code=1) from exc
        execute_now = False
    data = _post(
        f"/api/actions/lead-gen/send-approved-draft?execute_now={'true' if execute_now else 'false'}",
        json_body={
            "batch_item_id": batch_item_id,
            "subject": subject,
            "body": body,
            "requested_by": approved_by,
            "approved_by": approved_by,
            "scheduled_for": scheduled_for.isoformat() if scheduled_for else None,
        },
        timeout=120.0,
    )
    if json_output:
        console.print_json(data=data)
        return
    action = data.get("action") or {}
    result = data.get("result") or {}
    if scheduled_for:
        policy = data.get("policy") or {}
        console.print(
            f"action={action.get('id')} status={action.get('status')} policy={policy.get('reason')} "
            f"scheduled_pt={format_pt(action.get('scheduled_for'))} "
            f"scheduled_utc={format_utc(action.get('scheduled_for'))}"
        )
        return
    console.print(
        f"action={action.get('id')} status={action.get('status')} "
        f"sent_to={result.get('sent_to', '—')} message_id={result.get('sent_message_id', '—')}"
    )


@actions_app.command("send-test-email")
def actions_send_test_email(
    to: str = typer.Option(..., "--to", help="Approved test recipient."),
    subject: str = typer.Option("Possible OS durable action test", "--subject", help="Approved subject."),
    body: str = typer.Option(
        "This is a controlled test email sent through the Possible OS durable action executor.",
        "--body",
        help="Approved body.",
    ),
    approved_by: str = typer.Option("operator", "--approved-by"),
    from_addr: str = typer.Option("", "--from", help="Optional configured From override."),
    execute_now: bool = typer.Option(True, "--execute/--no-execute", help="Execute immediately after creating the action."),
    json_output: bool = typer.Option(False, "--json"),
):
    """Create, policy-check, and optionally execute a controlled test email action."""
    data = _post(
        f"/api/actions/email/send?execute_now={'true' if execute_now else 'false'}",
        json_body={
            "mode": "test",
            "to": to,
            "subject": subject,
            "body": body,
            "requested_by": approved_by,
            "approved_by": approved_by,
            "from_addr": from_addr or None,
        },
        timeout=120.0,
    )
    if json_output:
        console.print_json(data=data)
        return
    action = data.get("action") or {}
    result = data.get("result") or {}
    console.print(
        f"action={action.get('id')} status={action.get('status')} "
        f"sent_to={result.get('sent_to', '—')} message_id={result.get('sent_message_id', '—')}"
    )


@actions_app.command("send-email")
def actions_send_email(
    to: str = typer.Option(..., "--to", help="Approved recipient."),
    subject: str = typer.Option(..., "--subject", help="Approved subject."),
    body: str = typer.Option(..., "--body", help="Approved body."),
    mode: str = typer.Option("test", "--mode", help="Email mode: test or lead_gen."),
    approved_by: str = typer.Option("operator", "--approved-by"),
    from_addr: str = typer.Option("", "--from", help="Optional configured From override."),
    contact_id: str = typer.Option("", "--contact", help="Lead-gen contact id for --mode=lead_gen."),
    batch_item_id: str = typer.Option("", "--item", help="Lead-gen batch item id for --mode=lead_gen."),
    pif_id: str = typer.Option("", "--pif", help="Lead-gen firm pif_id for --mode=lead_gen."),
    firm_name: str = typer.Option("", "--firm", help="Lead-gen firm name for --mode=lead_gen."),
    at: str = typer.Option("", "--at", help='Schedule send time: ISO-8601 with offset, or "HH:MM PT|PDT|PST" today.'),
    execute_now: bool = typer.Option(True, "--execute/--no-execute", help="Execute immediately after creating the action."),
    json_output: bool = typer.Option(False, "--json"),
):
    """Create, policy-check, and optionally execute a durable email action."""
    scheduled_for = None
    if at:
        from app.services.scheduled_time import format_pt, format_utc, parse_scheduled_time
        try:
            scheduled_for = parse_scheduled_time(at)
        except ValueError as exc:
            console.print(f"[red]Invalid --at: {exc}[/red]")
            raise typer.Exit(code=1) from exc
        execute_now = False
    data = _post(
        f"/api/actions/email/send?execute_now={'true' if execute_now else 'false'}",
        json_body={
            "mode": mode,
            "to": to,
            "subject": subject,
            "body": body,
            "requested_by": approved_by,
            "approved_by": approved_by,
            "from_addr": from_addr or None,
            "contact_id": contact_id or None,
            "batch_item_id": batch_item_id or None,
            "pif_id": pif_id or None,
            "firm_name": firm_name or None,
            "scheduled_for": scheduled_for.isoformat() if scheduled_for else None,
        },
        timeout=120.0,
    )
    if json_output:
        console.print_json(data=data)
        return
    action = data.get("action") or {}
    result = data.get("result") or {}
    if scheduled_for:
        policy = data.get("policy") or {}
        console.print(
            f"action={action.get('id')} status={action.get('status')} mode={mode} "
            f"policy={policy.get('reason')} scheduled_pt={format_pt(action.get('scheduled_for'))} "
            f"scheduled_utc={format_utc(action.get('scheduled_for'))}"
        )
        return
    console.print(
        f"action={action.get('id')} status={action.get('status')} "
        f"mode={mode} sent_to={result.get('sent_to', '—')} "
        f"message_id={result.get('sent_message_id', '—')}"
    )


# ---------------------------------------------------------------------------
# agents — master-agent heartbeat and durable subagent task board
# ---------------------------------------------------------------------------

@agents_app.command("status")
def agents_status(json_output: bool = typer.Option(False, "--json", help="Print raw JSON.")):
    """Show master-agent heartbeat configuration and last heartbeat result."""
    data = _get("/api/agents/status")
    if json_output:
        console.print_json(data=data)
        return
    console.print(f"heartbeat_enabled: {data.get('heartbeat_enabled')}")
    console.print(f"heartbeat_interval_seconds: {data.get('heartbeat_interval_seconds')}")
    console.print(f"tool_runner_enabled: {data.get('tool_runner_enabled')}")
    console.print(f"tool_runner_max_iterations: {data.get('tool_runner_max_iterations')}")
    last = data.get("last_heartbeat") or {}
    if last:
        console.print(f"last_completed_at: {last.get('completed_at')}")
        console.print(f"active_task_count: {last.get('active_task_count')}")
        console.print(f"stale_task_ids: {', '.join(last.get('stale_task_ids') or []) or '-'}")
        human_status = last.get("human_status") or {}
        objective_status = last.get("objective_status") or {}
        status_llm = last.get("status_llm") or {}
        if objective_status:
            console.print(f"objective_status: {objective_status.get('status')}")
            console.print(f"objective_next: {objective_status.get('next_best_action')}")
        if human_status:
            console.print(f"state: {human_status.get('state')}")
            console.print(f"goal: {human_status.get('goal')}")
            console.print(f"current_focus: {human_status.get('current_focus')}")
            console.print(f"needs_from_user: {human_status.get('needs_from_user')}")
        writer = "openclaw" if status_llm.get("used_llm") else "fallback"
        model_suffix = f" ({status_llm.get('model')})" if status_llm.get("model") else ""
        console.print(f"status_writer: {writer}{model_suffix}")
    else:
        console.print("last_heartbeat: none recorded in this process")


@agents_app.command("heartbeat")
def agents_heartbeat(json_output: bool = typer.Option(False, "--json", help="Print raw JSON.")):
    """Run one master-agent heartbeat tick now."""
    data = _post("/api/agents/heartbeat/run", timeout=240.0)
    if json_output:
        console.print_json(data=data)
        return
    hb = data.get("heartbeat") or {}
    console.print(f"[green]heartbeat {hb.get('status')}[/green]")
    console.print(f"active_task_count: {hb.get('active_task_count')}")
    console.print(f"queued_task_count: {hb.get('queued_task_count')}")
    console.print(f"blocked_task_count: {hb.get('blocked_task_count')}")
    console.print(f"stale_task_ids: {', '.join(hb.get('stale_task_ids') or []) or '-'}")


@agents_app.command("config")
def agents_config(
    interval_seconds: Optional[int] = typer.Option(
        None,
        "--interval-seconds",
        "--period",
        min=60,
        max=3600,
        help="Set the master heartbeat period in seconds.",
    ),
    enabled: Optional[bool] = typer.Option(
        None,
        "--enabled/--disabled",
        help="Enable or disable the master heartbeat loop.",
    ),
    tool_runner_enabled: Optional[bool] = typer.Option(
        None,
        "--tool-runner-enabled/--tool-runner-disabled",
        help="Enable or disable the bounded master-agent read-only tool runner.",
    ),
    tool_runner_iterations: Optional[int] = typer.Option(
        None,
        "--tool-runner-iterations",
        min=1,
        max=5,
        help="Maximum read-only tool decisions per heartbeat.",
    ),
    tool_runner_runtime_seconds: Optional[int] = typer.Option(
        None,
        "--tool-runner-runtime-seconds",
        min=15,
        max=180,
        help="Maximum runtime budget for the heartbeat tool runner.",
    ),
    tool_runner_persist_continuation: Optional[bool] = typer.Option(
        None,
        "--tool-runner-persist-continuation/--no-tool-runner-persist-continuation",
        help="Persist compact continuation state for the next heartbeat.",
    ),
    auto_send_approved_lead_gen: Optional[bool] = typer.Option(
        None,
        "--auto-send-approved-lead-gen/--no-auto-send-approved-lead-gen",
        help="Allow heartbeat to execute already-approved lead-gen email actions through policy checks.",
    ),
    auto_send_limit: Optional[int] = typer.Option(
        None,
        "--auto-send-limit",
        min=1,
        max=25,
        help="Maximum approved lead-gen email actions heartbeat may execute per run.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """Update master-agent heartbeat settings without restarting the backend."""
    payload: dict[str, object] = {"actor": "operator"}
    if interval_seconds is not None:
        payload["heartbeat_interval_seconds"] = interval_seconds
    if enabled is not None:
        payload["heartbeat_enabled"] = enabled
    if tool_runner_enabled is not None:
        payload["tool_runner_enabled"] = tool_runner_enabled
    if tool_runner_iterations is not None:
        payload["tool_runner_max_iterations"] = tool_runner_iterations
    if tool_runner_runtime_seconds is not None:
        payload["tool_runner_max_runtime_seconds"] = tool_runner_runtime_seconds
    if tool_runner_persist_continuation is not None:
        payload["tool_runner_persist_continuation"] = tool_runner_persist_continuation
    if auto_send_approved_lead_gen is not None:
        payload["auto_execute_approved_lead_gen_email_enabled"] = auto_send_approved_lead_gen
    if auto_send_limit is not None:
        payload["auto_execute_approved_lead_gen_email_limit"] = auto_send_limit
    if len(payload) == 1:
        data = _get("/api/agents/status")
        if json_output:
            console.print_json(data=data)
            return
        console.print(f"heartbeat_enabled: {data.get('heartbeat_enabled')}")
        console.print(f"heartbeat_interval_seconds: {data.get('heartbeat_interval_seconds')}")
        console.print(f"tool_runner_enabled: {data.get('tool_runner_enabled')}")
        console.print(f"tool_runner_max_iterations: {data.get('tool_runner_max_iterations')}")
        console.print(f"tool_runner_max_runtime_seconds: {data.get('tool_runner_max_runtime_seconds')}")
        console.print(f"tool_runner_persist_continuation: {data.get('tool_runner_persist_continuation')}")
        console.print(
            "auto_execute_approved_lead_gen_email_enabled: "
            f"{data.get('auto_execute_approved_lead_gen_email_enabled')}"
        )
        console.print(
            "auto_execute_approved_lead_gen_email_limit: "
            f"{data.get('auto_execute_approved_lead_gen_email_limit')}"
        )
        return
    data = _patch("/api/agents/config", json_body=payload)
    if json_output:
        console.print_json(data=data)
        return
    config = data.get("config") or {}
    console.print("[green]updated master-agent config[/green]")
    console.print(f"heartbeat_enabled: {config.get('heartbeat_enabled')}")
    console.print(f"heartbeat_interval_seconds: {config.get('heartbeat_interval_seconds')}")
    console.print(f"tool_runner_enabled: {config.get('tool_runner_enabled')}")
    console.print(f"tool_runner_max_iterations: {config.get('tool_runner_max_iterations')}")
    console.print(f"tool_runner_max_runtime_seconds: {config.get('tool_runner_max_runtime_seconds')}")
    console.print(f"tool_runner_persist_continuation: {config.get('tool_runner_persist_continuation')}")
    console.print(
        "auto_execute_approved_lead_gen_email_enabled: "
        f"{config.get('auto_execute_approved_lead_gen_email_enabled')}"
    )
    console.print(
        "auto_execute_approved_lead_gen_email_limit: "
        f"{config.get('auto_execute_approved_lead_gen_email_limit')}"
    )


@agents_app.command("list")
def agents_list(
    status: str = typer.Option("all", "--status", help="Filter by task status."),
    assigned_agent: str = typer.Option("", "--agent", help="Filter by assigned agent."),
    limit: int = typer.Option(100, "--limit", min=1, max=500),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """List durable master/subagent tasks."""
    data = _get(
        "/api/agents/tasks",
        status=status if status != "all" else None,
        assigned_agent=assigned_agent or None,
        limit=limit,
    )
    if json_output:
        console.print_json(data=data)
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("id", no_wrap=True)
    table.add_column("agent", no_wrap=True)
    table.add_column("status", no_wrap=True)
    table.add_column("priority", no_wrap=True)
    table.add_column("title")
    for row in data.get("tasks") or []:
        table.add_row(
            row.get("id") or "",
            row.get("assigned_agent") or "",
            row.get("status") or "",
            str(row.get("priority") or ""),
            row.get("title") or "",
        )
    console.print(table)


@agents_app.command("show")
def agents_show(task_id: str = typer.Argument(...), json_output: bool = typer.Option(False, "--json")):
    """Show one task with recent events and reports."""
    data = _get(f"/api/agents/tasks/{task_id}")
    if json_output:
        console.print_json(data=data)
        return
    task = data.get("task") or {}
    console.print(f"[bold]{task.get('title')}[/bold]")
    console.print(f"id: {task.get('id')}")
    console.print(f"agent: {task.get('assigned_agent')}")
    console.print(f"status: {task.get('status')}")
    console.print(f"objective: {task.get('objective')}")
    console.print(f"last_heartbeat_at: {task.get('last_heartbeat_at') or '-'}")
    console.print(f"reports: {len(data.get('reports') or [])}")
    console.print(f"events: {len(data.get('events') or [])}")


@agents_app.command("create")
def agents_create(
    assigned_agent: str = typer.Option(..., "--agent", help="Assigned subagent name."),
    title: str = typer.Option(..., "--title", help="Task title."),
    objective: str = typer.Option(..., "--objective", help="Task objective."),
    priority: int = typer.Option(50, "--priority", min=0, max=1000),
    risk_level: str = typer.Option("low", "--risk"),
    created_by: str = typer.Option("operator", "--created-by"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Create a minimal durable subagent task."""
    data = _post(
        "/api/agents/tasks",
        json_body={
            "assigned_agent": assigned_agent,
            "title": title,
            "objective": objective,
            "priority": priority,
            "risk_level": risk_level,
            "created_by": created_by,
        },
    )
    if json_output:
        console.print_json(data=data)
        return
    task = data.get("task") or {}
    console.print(f"[green]created[/green] {task.get('id')} {task.get('title')}")


@agents_app.command("create-research-scout")
def agents_create_research_scout(json_output: bool = typer.Option(False, "--json")):
    """Create the first safe web-learning subagent task."""
    data = _post("/api/agents/tasks/research-scout")
    if json_output:
        console.print_json(data=data)
        return
    task = data.get("task") or {}
    console.print(f"[green]created[/green] {task.get('id')} {task.get('title')}")


@agents_app.command("create-systems-health")
def agents_create_systems_health(json_output: bool = typer.Option(False, "--json")):
    """Create the next safe SystemsHealthAgent observation/delegation task."""
    data = _post("/api/agents/tasks/systems-health")
    if json_output:
        console.print_json(data=data)
        return
    task = data.get("task") or {}
    console.print(f"[green]created[/green] {task.get('id')} {task.get('title')}")


@agents_app.command("run-research-scout")
def agents_run_research_scout(
    task_id: str = typer.Option("", "--task", help="Specific ResearchScout task id. Defaults to next queued task."),
    json_output: bool = typer.Option(False, "--json"),
):
    """Run one ResearchScoutAgent task now and write its learning note/report."""
    data = _post(
        "/api/agents/tasks/research-scout/run",
        json_body={},
        timeout=90.0,
    ) if not task_id else _post(
        f"/api/agents/tasks/research-scout/run?task_id={task_id}",
        json_body={},
        timeout=90.0,
    )
    if json_output:
        console.print_json(data=data)
        return
    report = data.get("report")
    if not report:
        console.print("[yellow]No queued ResearchScoutAgent task found.[/yellow]")
        return
    console.print(f"[green]completed[/green] {report.get('id')}: {report.get('summary')}")


@agents_app.command("run-systems-health")
def agents_run_systems_health(
    task_id: str = typer.Option("", "--task", help="Specific SystemsHealth task id. Defaults to next queued task."),
    json_output: bool = typer.Option(False, "--json"),
):
    """Run one SystemsHealthAgent read-only observation task now."""
    data = _post(
        "/api/agents/tasks/systems-health/run",
        json_body={},
        timeout=90.0,
    ) if not task_id else _post(
        f"/api/agents/tasks/systems-health/run?task_id={task_id}",
        json_body={},
        timeout=90.0,
    )
    if json_output:
        console.print_json(data=data)
        return
    report = data.get("report")
    if not report:
        console.print("[yellow]No queued SystemsHealthAgent task found.[/yellow]")
        return
    console.print(f"[green]completed[/green] {report.get('id')}: {report.get('summary')}")


@agents_app.command("capabilities")
def agents_capabilities(
    refresh: bool = typer.Option(False, "--refresh", help="Refresh the registry before listing."),
    no_probe: bool = typer.Option(False, "--no-probe", help="Do not run safe verification probes on refresh."),
    limit: int = typer.Option(100, "--limit", min=1, max=500),
    json_output: bool = typer.Option(False, "--json"),
):
    """List or refresh the master-agent capability registry."""
    data = (
        _post(f"/api/agents/capabilities/refresh?probe={'false' if no_probe else 'true'}", json_body={}, timeout=60.0)
        if refresh
        else _get("/api/agents/capabilities", limit=limit)
    )
    if json_output:
        console.print_json(data=data)
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("name")
    table.add_column("type", no_wrap=True)
    table.add_column("risk", no_wrap=True)
    table.add_column("status", no_wrap=True)
    table.add_column("source")
    for cap in data.get("capabilities") or []:
        table.add_row(
            cap.get("name") or "",
            cap.get("capability_type") or "",
            cap.get("risk_level") or "",
            cap.get("last_status") or "",
            cap.get("source") or "",
        )
    console.print(table)


@fs_app.command("list")
def fs_list(
    path: str = typer.Argument(".", help="Repo-relative path to list."),
    pattern: str = typer.Option("", "--pattern", help="Optional glob pattern."),
    limit: int = typer.Option(200, "--limit", min=1, max=1000),
    actor: str = typer.Option("operator", "--actor"),
    json_output: bool = typer.Option(False, "--json"),
):
    """List repo files through the read-only filesystem service."""
    data = _run_fs_payload(
        {"operation": "list_files", "path": path, "pattern": pattern or None, "limit": limit},
        actor=actor,
    )
    _print_fs_result(data, json_output=json_output)


@fs_app.command("read")
def fs_read(
    path: str = typer.Argument(..., help="Repo-relative file path."),
    start: int = typer.Option(1, "--start", min=1, help="First line to read."),
    end: int | None = typer.Option(None, "--end", min=1, help="Last line to read."),
    max_bytes: int = typer.Option(50_000, "--max-bytes", min=1, max=50_000),
    actor: str = typer.Option("operator", "--actor"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Read a text file with line numbers through the read-only service."""
    data = _run_fs_payload(
        {
            "operation": "read_file",
            "path": path,
            "start_line": start,
            "end_line": end,
            "max_bytes": max_bytes,
        },
        actor=actor,
    )
    _print_fs_result(data, json_output=json_output)


@fs_app.command("search")
def fs_search(
    query: str = typer.Argument(..., help="Literal text to search for."),
    path: str = typer.Argument(".", help="Repo-relative path to search."),
    glob: str = typer.Option("", "--glob", help="Optional rg-style glob, e.g. '*.py'."),
    limit: int = typer.Option(100, "--limit", min=1, max=100),
    actor: str = typer.Option("operator", "--actor"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Search repo text through the read-only service."""
    data = _run_fs_payload(
        {
            "operation": "search_text",
            "query": query,
            "path": path,
            "glob": glob or None,
            "limit": limit,
        },
        actor=actor,
    )
    _print_fs_result(data, json_output=json_output)


@fs_app.command("git-status")
def fs_git_status(
    actor: str = typer.Option("operator", "--actor"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Show read-only git status."""
    data = _run_fs_payload({"operation": "git_status"}, actor=actor)
    _print_fs_result(data, json_output=json_output)


@fs_app.command("git-diff")
def fs_git_diff(
    path: str = typer.Option("", "--path", help="Optional repo-relative path."),
    max_bytes: int = typer.Option(50_000, "--max-bytes", min=1, max=50_000),
    actor: str = typer.Option("operator", "--actor"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Show read-only git diff."""
    data = _run_fs_payload(
        {"operation": "git_diff", "path": path or None, "max_bytes": max_bytes},
        actor=actor,
    )
    _print_fs_result(data, json_output=json_output)


@fs_app.command("git-log")
def fs_git_log(
    limit: int = typer.Option(20, "--limit", min=1, max=20),
    actor: str = typer.Option("operator", "--actor"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Show recent git commits."""
    data = _run_fs_payload({"operation": "git_log", "limit": limit}, actor=actor)
    _print_fs_result(data, json_output=json_output)


@fs_app.command("git-show")
def fs_git_show(
    ref: str = typer.Argument("HEAD", help="Git ref to show."),
    path: str = typer.Option("", "--path", help="Optional repo-relative path."),
    max_bytes: int = typer.Option(50_000, "--max-bytes", min=1, max=50_000),
    actor: str = typer.Option("operator", "--actor"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Show a git ref or file at a ref."""
    data = _run_fs_payload(
        {"operation": "git_show", "ref": ref, "path": path or None, "max_bytes": max_bytes},
        actor=actor,
    )
    _print_fs_result(data, json_output=json_output)


@fs_app.command("sandbox-list")
def fs_sandbox_list(
    path: str = typer.Argument(".", help="Sandbox-relative path to list."),
    recursive: bool = typer.Option(True, "--recursive/--no-recursive"),
    limit: int = typer.Option(200, "--limit", min=1, max=500),
    actor: str = typer.Option("operator", "--actor"),
    json_output: bool = typer.Option(False, "--json"),
):
    """List files in the bounded agent sandbox."""
    data = _run_sandbox_payload(
        {"operation": "list", "path": path, "recursive": recursive, "limit": limit},
        actor=actor,
    )
    _print_sandbox_result(data, json_output=json_output)


@fs_app.command("sandbox-read")
def fs_sandbox_read(
    path: str = typer.Argument(..., help="Sandbox-relative file path."),
    max_bytes: int = typer.Option(50_000, "--max-bytes", min=1, max=50_000),
    actor: str = typer.Option("operator", "--actor"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Read a text file from the bounded agent sandbox."""
    data = _run_sandbox_payload(
        {"operation": "read", "path": path, "max_bytes": max_bytes},
        actor=actor,
    )
    _print_sandbox_result(data, json_output=json_output)


@fs_app.command("sandbox-write")
def fs_sandbox_write(
    path: str = typer.Argument(..., help="Sandbox-relative file path."),
    content: str = typer.Option(..., "--content", help="UTF-8 content to write."),
    append: bool = typer.Option(False, "--append", help="Append instead of overwrite."),
    actor: str = typer.Option("operator", "--actor"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Write or append a text file inside the bounded agent sandbox."""
    data = _run_sandbox_payload(
        {"operation": "append" if append else "write", "path": path, "content": content},
        actor=actor,
    )
    _print_sandbox_result(data, json_output=json_output)


@fs_app.command("sandbox-mkdir")
def fs_sandbox_mkdir(
    path: str = typer.Argument(..., help="Sandbox-relative directory path."),
    actor: str = typer.Option("operator", "--actor"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Create a directory inside the bounded agent sandbox."""
    data = _run_sandbox_payload({"operation": "mkdir", "path": path}, actor=actor)
    _print_sandbox_result(data, json_output=json_output)


@fs_app.command("sandbox-delete")
def fs_sandbox_delete(
    path: str = typer.Argument(..., help="Sandbox-relative file or directory path."),
    actor: str = typer.Option("operator", "--actor"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Delete a file or directory inside the bounded agent sandbox."""
    data = _run_sandbox_payload({"operation": "delete", "path": path}, actor=actor)
    _print_sandbox_result(data, json_output=json_output)


@agents_app.command("goals")
def agents_goals(
    status: str = typer.Option("all", "--status", help="Filter by goal status."),
    limit: int = typer.Option(20, "--limit", min=1, max=100),
    json_output: bool = typer.Option(False, "--json"),
):
    """List durable adaptive master-agent goals."""
    data = _get("/api/agents/goals", status=status if status != "all" else None, limit=limit)
    if json_output:
        console.print_json(data=data)
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("created", no_wrap=True)
    table.add_column("status", no_wrap=True)
    table.add_column("confidence", no_wrap=True)
    table.add_column("goal")
    for goal in data.get("goals") or []:
        table.add_row(
            goal.get("created_at") or "",
            goal.get("status") or "",
            goal.get("confidence") or "",
            goal.get("goal") or "",
        )
    console.print(table)


@agents_app.command("set-goal")
def agents_set_goal(
    goal: str = typer.Argument(..., help="Manual master-agent goal."),
    why: str = typer.Option("", "--why"),
    next_action: list[str] = typer.Option([], "--next-action", help="Repeat for each next action."),
    success_metric: str = typer.Option("", "--success-metric"),
    time_horizon: str = typer.Option("manual operating slice", "--time-horizon"),
    confidence: str = typer.Option("high", "--confidence"),
    created_by: str = typer.Option("operator", "--created-by"),
    expires_hours: int = typer.Option(24, "--expires-hours", min=1, max=168),
    json_output: bool = typer.Option(False, "--json"),
):
    """Set a manual master-agent goal that heartbeat respects until expiry."""
    data = _post(
        "/api/agents/goals/set",
        json_body={
            "goal": goal,
            "why": why,
            "next_actions": list(next_action),
            "success_metric": success_metric,
            "time_horizon": time_horizon,
            "confidence": confidence,
            "created_by": created_by,
            "expires_hours": expires_hours,
        },
    )
    if json_output:
        console.print_json(data=data)
        return
    row = data.get("goal") or {}
    console.print(f"[green]Set active goal[/green] {row.get('id')}: {row.get('goal')}")


@agents_app.command("set-status")
def agents_set_status(
    task_id: str = typer.Argument(...),
    status: str = typer.Argument(...),
    message: str = typer.Option("", "--message"),
    actor: str = typer.Option("operator", "--actor"),
):
    """Set a subagent task status."""
    console.print_json(data=_patch(
        f"/api/agents/tasks/{task_id}/status",
        json_body={"status": status, "message": message, "actor": actor},
    ))


@agents_app.command("task-heartbeat")
def agents_task_heartbeat(
    task_id: str = typer.Argument(...),
    agent_id: str = typer.Option(..., "--agent"),
    message: str = typer.Option("", "--message"),
    status: str = typer.Option("", "--status"),
):
    """Record a heartbeat from a subagent task."""
    console.print_json(data=_post(
        f"/api/agents/tasks/{task_id}/heartbeat",
        json_body={
            "agent_id": agent_id,
            "message": message,
            "status": status or None,
            "metadata": {},
        },
    ))


@agents_app.command("report")
def agents_report(
    task_id: str = typer.Argument(...),
    agent_id: str = typer.Option(..., "--agent"),
    summary: str = typer.Option(..., "--summary"),
    status: str = typer.Option("reported", "--status"),
):
    """Create a structured report for a task."""
    console.print_json(data=_post(
        f"/api/agents/tasks/{task_id}/reports",
        json_body={
            "agent_id": agent_id,
            "status": status,
            "summary": summary,
        },
    ))


@agents_app.command("events")
def agents_events(
    task_id: str = typer.Option("", "--task"),
    limit: int = typer.Option(100, "--limit", min=1, max=500),
):
    """List recent master/subagent events."""
    console.print_json(data=_get("/api/agents/events", task_id=task_id or None, limit=limit))


@agents_app.command("reports")
def agents_reports(
    task_id: str = typer.Option("", "--task"),
    limit: int = typer.Option(100, "--limit", min=1, max=500),
):
    """List recent subagent reports."""
    console.print_json(data=_get("/api/agents/reports", task_id=task_id or None, limit=limit))


# ---------------------------------------------------------------------------
# lead-gen — cybernetic lead-generation loop
# ---------------------------------------------------------------------------

@lead_gen_app.command("policy")
def lead_gen_policy():
    """Show the active lead-generation policy version."""
    console.print_json(data=_get("/api/lead-gen/policy/current"))


@lead_gen_app.command("recommend")
def lead_gen_recommend(
    template_key: str = typer.Option(
        "possible_minds_dynamic",
        "--template-key",
        "--template",
        help="Strategy/composer template key.",
    ),
    limit: int = typer.Option(50, "--limit", "-n", min=1, max=200),
    name: str = typer.Option("", "--name", help="Operator-visible batch name."),
    created_by: str = typer.Option("operator", "--created-by"),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """Create a persistent recommendation batch for approval.

    This writes batch/item rows but does not start sequences or send email.
    """
    data = _post(
        "/api/lead-gen/batches",
        json_body={
            "name": name or None,
            "template_key": template_key,
            "limit": limit,
            "created_by": created_by,
        },
        timeout=120.0,
    )
    if json_output:
        console.print_json(data=data)
        return
    batch = data["batch"]
    items = data.get("items") or []
    console.print(
        f"[green]Created batch[/green] {batch['id']} "
        f"({len(items)} item(s), template={batch['template_key']})"
    )
    _print_lead_gen_items(items)


@lead_gen_app.command("email-agent-slice")
def lead_gen_email_agent_slice(
    limit: int = typer.Option(3, "--limit", "-n", min=1, max=10, help="Number of decision-maker contacts to draft."),
    template_key: str = typer.Option(
        "possible_minds_dynamic",
        "--template-key",
        "--template",
        help="Composer template key.",
    ),
    created_by: str = typer.Option("master-agent", "--created-by"),
    composer_variant_key: str = typer.Option("", "--composer-variant", help="Optional composer skill variant key."),
    approve_actions: bool = typer.Option(
        False,
        "--approve-actions/--approval-ready",
        help="Create exact approved actions for no-send policy checks. Default leaves actions waiting for approval.",
    ),
    policy_check_first_action: bool = typer.Option(
        False,
        "--policy-check-first-action",
        help="Policy-check the first created action without executing it.",
    ),
    batch_id: str = typer.Option(
        "",
        "--batch",
        help="Compose for an existing batch's pending undrafted items instead of selecting contacts.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """Create a no-send agent slice: select contacts, research context, compose drafts, create actions."""
    data = _post(
        "/api/lead-gen/email-agent/slice",
        json_body={
            "limit": limit,
            "template_key": template_key,
            "created_by": created_by,
            "composer_variant_key": composer_variant_key or None,
            "approve_actions": approve_actions,
            "policy_check_first_action": policy_check_first_action,
            "batch_id": batch_id or None,
        },
        timeout=240.0,
    )
    if json_output:
        console.print_json(data=data)
        return
    batch = data.get("batch") or {}
    drafts = data.get("drafts") or []
    console.print(
        f"[green]Created lead-gen email agent slice[/green] {batch.get('id')} "
        f"({len(drafts)} draft(s), no_email_sent={data.get('no_email_sent')})"
    )
    for draft in drafts:
        console.print(
            f"- {draft.get('contact_name') or draft.get('firm_name')} "
            f"<{draft.get('contact_email')}> action={draft.get('action_id')} "
            f"status={draft.get('action_status')} subject={draft.get('subject')}"
        )
    if data.get("first_policy"):
        policy = data["first_policy"]
        console.print(f"first_policy allowed={policy.get('allowed')} reason={policy.get('reason')}")


def _print_daily_run(data: dict) -> None:
    console.print(
        f"[bold]daily-run[/bold] date={data.get('run_date')} status={data.get('status')} "
        f"stage={data.get('stage')} batch={data.get('batch_id') or '-'}"
    )
    table = Table(show_header=True, header_style="bold")
    table.add_column("stage", no_wrap=True)
    table.add_column("status", no_wrap=True)
    table.add_column("counts")
    table.add_column("error")
    stages = data.get("stages") or {}
    for stage in [
        "gates",
        "signals",
        "research",
        "personas",
        "select",
        "batch",
        "compose",
        "schedule",
        "notify",
    ]:
        entry = stages.get(stage) or {}
        counts = entry.get("counts")
        if isinstance(counts, dict):
            compact = json.dumps(counts, sort_keys=True, default=str)
        else:
            compact = "" if counts is None else str(counts)
        table.add_row(
            stage,
            str(entry.get("status") or "-"),
            compact[:220],
            str(entry.get("error") or entry.get("reason") or "")[:160],
        )
    console.print(table)


@lead_gen_app.command("daily-run")
def lead_gen_daily_run(
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan without DB writes, research API calls, actions, or WhatsApp."),
    force: bool = typer.Option(False, "--force", help="Re-run today's checkpointed pipeline."),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """Run the deterministic daily lead-selection and drafting pipeline now."""
    data = _post(
        "/api/lead-gen/daily-run",
        json_body={"dry_run": dry_run, "force": force, "created_by": "operator"},
        timeout=900.0,
    )
    if json_output:
        console.print_json(data=data)
        return
    _print_daily_run(data)


@lead_gen_app.command("daily-status")
def lead_gen_daily_status(
    date_: str = typer.Option("", "--date", help="Run date YYYY-MM-DD. Defaults to latest/today."),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """Show daily lead-gen pipeline run state."""
    data = _get("/api/lead-gen/daily-runs", limit=100)
    runs = data.get("runs") or []
    if date_:
        runs = [row for row in runs if row.get("run_date") == date_]
    if json_output:
        console.print_json(data={"runs": runs})
        return
    if not runs:
        console.print("[dim]No daily runs found.[/dim]")
        return
    _print_daily_run(runs[0])


@lead_gen_app.command("daily-enable")
def lead_gen_daily_enable(json_output: bool = typer.Option(False, "--json", help="Print raw JSON.")):
    """Enable the persisted daily lead-gen loop flag."""
    data = _put("/api/lead-gen/daily-run/enabled", {"enabled": True})
    if json_output:
        console.print_json(data=data)
        return
    console.print(f"daily_run_enabled={data.get('enabled')} key={data.get('key')}")


@lead_gen_app.command("daily-disable")
def lead_gen_daily_disable(json_output: bool = typer.Option(False, "--json", help="Print raw JSON.")):
    """Disable the persisted daily lead-gen loop flag."""
    data = _put("/api/lead-gen/daily-run/enabled", {"enabled": False})
    if json_output:
        console.print_json(data=data)
        return
    console.print(f"daily_run_enabled={data.get('enabled')} key={data.get('key')}")


@lead_gen_app.command("batches")
def lead_gen_batches(
    status: str = typer.Option("", "--status", help="recommended | approved | sequencing | observing | completed | archived"),
    limit: int = typer.Option(50, "--limit", "-n", min=1, max=200),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """List lead-generation batches."""
    data = _get("/api/lead-gen/batches", status=status or None, limit=limit)
    if json_output:
        console.print_json(data=data)
        return
    rows = data.get("batches") or []
    if not rows:
        console.print("[dim]No batches.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("id", no_wrap=True)
    table.add_column("status", no_wrap=True)
    table.add_column("template", no_wrap=True)
    table.add_column("items", justify="right", no_wrap=True)
    table.add_column("created", no_wrap=True)
    table.add_column("name")
    for r in rows:
        counts = r.get("counts") or {}
        table.add_row(
            r["id"][:8] + "…",
            r["status"],
            r["template_key"],
            str(counts.get("returned") or ""),
            (r.get("created_at") or "")[:19],
            r["name"],
        )
    console.print(table)


@lead_gen_app.command("show")
def lead_gen_show(
    batch_id: str = typer.Argument(..., help="lead_gen_batches.id"),
    observations: bool = typer.Option(False, "--observations", help="Include feedback observations."),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """Show one batch and its recommended contacts."""
    data = _get(f"/api/lead-gen/batches/{batch_id}", include_observations=observations)
    if json_output:
        console.print_json(data=data)
        return
    batch = data["batch"]
    console.print(
        f"[bold]{batch['name']}[/bold] "
        f"[dim]id={batch['id']} status={batch['status']} template={batch['template_key']}[/dim]"
    )
    _print_lead_gen_items(data.get("items") or [])
    if observations:
        _print_lead_gen_observations(data.get("observations") or [])


@lead_gen_app.command("compose-variants")
def lead_gen_compose_variants(
    batch_item_id: str = typer.Argument(..., help="lead_gen_batch_items.id"),
):
    """Compose this item's email with every active composer variant (on-demand)
    so the preview can compare them. Persists reason_json.variant_drafts."""
    console.print_json(
        data=_post(f"/api/lead-gen/batch-items/{batch_item_id}/compose-variants", json_body=None, timeout=180.0)
    )


@lead_gen_app.command("select-variant")
def lead_gen_select_variant(
    batch_item_id: str = typer.Argument(..., help="lead_gen_batch_items.id"),
    variant_key: str = typer.Argument(..., help="composer variant key to send (see composer-ab list)"),
):
    """Set which composed variant is the active draft / will be sent for an item."""
    console.print_json(
        data=_post(f"/api/lead-gen/batch-items/{batch_item_id}/select-variant", json_body={"variant_key": variant_key})
    )


@lead_gen_app.command("edit-draft")
def lead_gen_edit_draft(
    batch_item_id: str = typer.Argument(..., help="lead_gen_batch_items.id"),
    at: str = typer.Option("", "--at", help='Optional scheduled send time: ISO-8601 with offset, or "HH:MM PT|PDT|PST" today.'),
    use_editor: bool = typer.Option(True, "--editor/--no-editor", help="Open $EDITOR before saving."),
    execute_now: bool = typer.Option(False, "--execute/--no-execute", help="Execute immediately after creating a new unscheduled action."),
    actor: str = typer.Option("operator", "--actor", help="Actor recorded on action events/traces."),
    json_output: bool = typer.Option(False, "--json"),
):
    """Edit a lead-gen draft and create or update its approved action."""
    scheduled_for = None
    if at:
        from app.services.scheduled_time import parse_scheduled_time

        try:
            scheduled_for = parse_scheduled_time(at)
        except ValueError as exc:
            console.print(f"[red]Invalid --at: {exc}[/red]")
            raise typer.Exit(code=1) from exc
        execute_now = False
    loaded = _get(f"/api/lead-gen/batch-items/{batch_item_id}/draft")
    draft = loaded.get("draft") or {}
    subject, body = _edit_subject_body(
        str(draft.get("subject") or ""),
        str(draft.get("body") or ""),
        use_editor=use_editor,
    )
    data = _post(
        f"/api/lead-gen/batch-items/{batch_item_id}/edit-draft",
        json_body={
            "subject": subject,
            "body": body,
            "actor": actor,
            "scheduled_for": scheduled_for.isoformat() if scheduled_for else None,
            "execute_now": execute_now,
        },
        timeout=120.0,
    )
    if json_output:
        console.print_json(data=data)
        return
    action = data.get("action") or {}
    scheduled_pt = data.get("scheduled_for_pt") or ""
    scheduled_utc = data.get("scheduled_for_utc") or ""
    suffix = f" scheduled_pt={scheduled_pt} scheduled_utc={scheduled_utc}" if scheduled_pt else ""
    console.print(
        f"action={action.get('id')} status={action.get('status')} "
        f"created={data.get('created')} updated_existing={data.get('updated_existing')} "
        f"executed={data.get('executed')}{suffix}"
    )


@lead_gen_app.command("approve")
def lead_gen_approve(
    batch_id: str = typer.Argument(..., help="lead_gen_batches.id"),
    approved_by: str = typer.Option("operator", "--approved-by"),
    start_sequences: bool = typer.Option(
        False,
        "--start-sequences",
        help="Also create email_sequence rows. Sending remains gated by ALLOW_SEQUENCE_SEND.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """Approve a batch. With --start-sequences, queue sequence rows."""
    data = _post(
        f"/api/lead-gen/batches/{batch_id}/approve",
        json_body={"approved_by": approved_by, "start_sequences": start_sequences},
        timeout=120.0,
    )
    if json_output:
        console.print_json(data=data)
        return
    batch = data["batch"]
    console.print(
        f"[green]Batch {batch['id']} is {batch['status']}[/green] "
        f"(start_sequences={start_sequences})"
    )
    _print_lead_gen_items(data.get("items") or [])


@lead_gen_app.command("observe")
def lead_gen_observe(
    event_type: str = typer.Option(..., "--event-type", help="email_reply | email_bounce | booking | manual_note | etc."),
    batch_id: str = typer.Option("", "--batch", help="Batch id."),
    contact_id: str = typer.Option("", "--contact", help="Contact id."),
    batch_item_id: str = typer.Option("", "--item", help="Batch item id."),
    text: str = typer.Option("", "--text", help="Raw note/reply text."),
    raw_json_file: str = typer.Option("", "--raw-json-file", help="Path to raw event JSON."),
    model: str = typer.Option("", "--model", help="Override OpenClaw model id."),
):
    """Classify and store one feedback observation via the OpenClaw gateway."""
    raw_event: dict
    if raw_json_file:
        raw_event = json.loads(Path(raw_json_file).read_text(encoding="utf-8"))
    else:
        raw_event = {"text": text}
    data = _post(
        "/api/lead-gen/observations/classify",
        json_body={
            "event_type": event_type,
            "raw_event": raw_event,
            "batch_id": batch_id or None,
            "contact_id": contact_id or None,
            "batch_item_id": batch_item_id or None,
            "model": model or None,
        },
        timeout=180.0,
    )
    console.print_json(data=data)


@lead_gen_observations_app.callback(invoke_without_command=True)
def lead_gen_observations(
    ctx: typer.Context,
    since: str = typer.Option("7d", "--since", help='Window such as "7d", "24h", or an ISO timestamp.'),
    event_type: str = typer.Option("", "--type", help="Filter by event_type."),
    contact_id: str = typer.Option("", "--contact", help="Filter by firm_contacts.id."),
    limit: int = typer.Option(200, "--limit", "-n", min=1, max=1000),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """List automatic lead-generation observations with linkage."""
    if ctx.invoked_subcommand:
        return
    from app.services.lead_gen_cybernetic import list_observations, parse_observation_since

    try:
        since_dt = parse_observation_since(since)
    except ValueError as exc:
        console.print(f"[red]Invalid --since: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    rows = asyncio.run(list_observations(
        since=since_dt,
        event_type=event_type or None,
        contact_id=contact_id or None,
        limit=limit,
    ))
    if json_output:
        console.print_json(data={"observations": rows})
        return
    _print_lead_gen_observations(rows)


@lead_gen_observations_app.command("summary")
def lead_gen_observations_summary(
    since: str = typer.Option("7d", "--since", help='Window such as "7d", "24h", or an ISO timestamp.'),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """Print counts by automatic observation event type."""
    from app.services.lead_gen_cybernetic import parse_observation_since, summarize_observations

    try:
        since_dt = parse_observation_since(since)
    except ValueError as exc:
        console.print(f"[red]Invalid --since: {exc}[/red]")
        raise typer.Exit(code=1) from exc
    rows = asyncio.run(summarize_observations(since=since_dt))
    if json_output:
        console.print_json(data={"since": since, "summary": rows})
        return
    if not rows:
        console.print("[dim]No observations.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("event_type", no_wrap=True)
    table.add_column("count", justify="right", no_wrap=True)
    for row in rows:
        table.add_row(row["event_type"], str(row["count"]))
    console.print(table)


@lead_gen_app.command("propose")
def lead_gen_propose(
    batch_id: str = typer.Argument(..., help="lead_gen_batches.id"),
    created_by: str = typer.Option("system", "--created-by"),
):
    """Create a human-reviewed policy proposal from stored observations."""
    data = _post(
        f"/api/lead-gen/batches/{batch_id}/proposal",
        json_body={"created_by": created_by},
        timeout=60.0,
    )
    console.print_json(data=data)


def _print_lead_gen_items(items: list[dict]) -> None:
    if not items:
        console.print("[dim]No batch items.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", justify="right", no_wrap=True)
    table.add_column("item", no_wrap=True)
    table.add_column("approval", no_wrap=True)
    table.add_column("firm")
    table.add_column("contact")
    table.add_column("email")
    table.add_column("persona", no_wrap=True)
    table.add_column("score", justify="right", no_wrap=True)
    table.add_column("outcome", no_wrap=True)
    for i, item in enumerate(items, start=1):
        table.add_row(
            str(i),
            item["id"][:8] + "…",
            item["approval_status"],
            item["firm_name"],
            item["contact_name"] or "—",
            item["contact_email"],
            item["persona"] or "—",
            str(item["score"]),
            item.get("outcome") or "—",
        )
    console.print(table)


def _print_lead_gen_observations(observations: list[dict]) -> None:
    if not observations:
        console.print("[dim]No observations.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("when", no_wrap=True)
    table.add_column("obs", no_wrap=True)
    table.add_column("event", no_wrap=True)
    table.add_column("contact", no_wrap=True)
    table.add_column("item", no_wrap=True)
    table.add_column("outcome", no_wrap=True)
    table.add_column("conf", justify="right", no_wrap=True)
    table.add_column("next", no_wrap=True)
    table.add_column("reasoning")
    for obs in observations:
        table.add_row(
            (obs.get("created_at") or "")[:19],
            (obs.get("id") or "")[:8] + "…",
            obs.get("event_type") or "",
            ((obs.get("contact_id") or "")[:8] + "…") if obs.get("contact_id") else "—",
            ((obs.get("batch_item_id") or "")[:8] + "…") if obs.get("batch_item_id") else "—",
            obs.get("classified_outcome") or "—",
            str(obs.get("confidence") or ""),
            obs.get("next_action") or "—",
            (obs.get("llm_reasoning") or "")[:80],
        )
    console.print(table)


# ---------------------------------------------------------------------------
# inbound — Zoho IMAP reply ingestion
# ---------------------------------------------------------------------------

@inbound_app.command("status")
def inbound_status():
    """Show whether Zoho IMAP credentials are configured. Does not connect."""
    console.print_json(data=_get("/api/inbound-email/config"))


@inbound_app.command("poll")
def inbound_poll(
    limit: int = typer.Option(20, "--limit", "-n", min=1, max=200),
    all_messages: bool = typer.Option(False, "--all", help="Poll all recent messages, not only unread."),
    since_days: int = typer.Option(14, "--since-days", min=0, max=365),
    classify: bool = typer.Option(False, "--classify", help="Use the OpenClaw gateway to classify matched replies."),
    mark_seen: bool = typer.Option(False, "--mark-seen", help="Mark fetched Zoho messages as seen."),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """Fetch recent Zoho inbox messages, store them, and create lead-gen
    observations for replies matched to known contacts.

    By default this only reads unread messages and does not mark them seen.
    """
    data = _post(
        "/api/inbound-email/poll",
        json_body={
            "limit": limit,
            "unseen_only": not all_messages,
            "since_days": since_days,
            "classify": classify,
            "mark_seen": mark_seen,
        },
        timeout=240.0,
    )
    if json_output:
        console.print_json(data=data)
        return
    console.print(
        f"[green]fetched={data['fetched']} stored={data['stored']} "
        f"matched={data['matched']} observations={data['observations']}[/green]"
    )
    _print_inbound_messages(data.get("messages") or [])


@inbound_app.command("list")
def inbound_list(
    limit: int = typer.Option(50, "--limit", "-n", min=1, max=200),
    matched: str = typer.Option("all", "--matched", help="all | yes | no"),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """List stored inbound emails."""
    matched_value = None
    if matched.lower() in {"yes", "true", "1"}:
        matched_value = "true"
    elif matched.lower() in {"no", "false", "0"}:
        matched_value = "false"
    params = {"limit": limit}
    if matched_value is not None:
        params["matched"] = matched_value
    data = _get("/api/inbound-email", **params)
    if json_output:
        console.print_json(data=data)
        return
    _print_inbound_messages(data.get("messages") or [])


def _print_inbound_messages(messages: list[dict]) -> None:
    if not messages:
        console.print("[dim]No inbound messages.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("received", no_wrap=True)
    table.add_column("from")
    table.add_column("subject")
    table.add_column("matched", no_wrap=True)
    table.add_column("status", no_wrap=True)
    table.add_column("excerpt")
    for msg in messages:
        table.add_row(
            (msg.get("received_at") or msg.get("ingested_at") or "")[:19],
            msg.get("from_email") or "",
            (msg.get("subject") or "")[:60],
            "yes" if msg.get("matched_contact_id") else "no",
            msg.get("classification_status") or "",
            (msg.get("text_excerpt") or "").replace("\n", " ")[:80],
        )
    console.print(table)


# ===========================================================================
# Outreach — LLM-composed blog-post outreach with per-recipient tracking
# ===========================================================================
#
# Talks directly to outreach_service (no REST hop). Send commands have real
# side effects (Resend API + DB writes) — keep them gated behind explicit
# --send IDs or --auto flags, never run on a whole campaign by default.

def _outreach_svc():
    """Lazy import so the rest of the CLI doesn't pay the import cost."""
    from app.services import outreach_service
    return outreach_service


@outreach_campaigns_app.command("create")
def outreach_campaigns_create(
    post_slug: str = typer.Option(..., "--post-slug", "-s", help="Blog post slug (e.g. musk-algorithm-ai-pi-firm)."),
    name: str = typer.Option("", "--name", help="Campaign display name. Defaults to post title + date."),
    sender_email: str = typer.Option("", "--sender-email", help="From: address. Defaults to OUTREACH_SENDER_EMAIL env."),
    sender_name: str = typer.Option("", "--sender-name", help="Display name. Defaults to OUTREACH_SENDER_NAME env."),
    sender_title: str = typer.Option("", "--sender-title", help="Signature title."),
    intent: str = typer.Option("share", "--intent", help="share | nudge | book. Hint for the composer's framing."),
    notes: str = typer.Option("", "--notes", help="Free-form operator notes (not sent to LLM)."),
    no_excerpts: bool = typer.Option(False, "--no-excerpts", help="Skip live-fetch of post excerpts (uses index meta only)."),
):
    """Create a new outreach campaign for a published blog post. Fetches
    post metadata (and live excerpts unless --no-excerpts) and freezes the
    snapshot on the campaign — same post context for every recipient."""
    svc = _outreach_svc()
    summary = _run(svc.create_campaign(
        post_slug=post_slug,
        name=name or None,
        sender_email=sender_email or None,
        sender_name=sender_name or None,
        sender_title=sender_title or None,
        intent=intent,
        notes=notes or None,
        with_excerpts=not no_excerpts,
    ))
    console.print(f"[green]Created campaign #{summary.id}[/green]")
    console.print(f"  name:    {summary.name}")
    console.print(f"  post:    {summary.post_slug} — {summary.post_title}")
    console.print(f"  sender:  {summary.sender_name} <{summary.sender_email}>")
    console.print(f"  intent:  {summary.intent}")
    console.print(f"  status:  {summary.status}")


@outreach_campaigns_app.command("list")
def outreach_campaigns_list(
    status: str = typer.Option("", "--status", help="draft | ready | sending | paused | complete | archived"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max rows."),
):
    """List recent campaigns (newest first)."""
    svc = _outreach_svc()
    rows = _run(svc.list_campaigns(status=status or None, limit=limit))
    if not rows:
        console.print("[dim]No campaigns match.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("id", no_wrap=True, justify="right")
    table.add_column("name")
    table.add_column("post slug")
    table.add_column("intent", no_wrap=True)
    table.add_column("status", no_wrap=True)
    table.add_column("sender")
    table.add_column("created (UTC)", no_wrap=True)
    for r in rows:
        table.add_row(
            str(r.id),
            r.name[:60] + ("…" if len(r.name) > 60 else ""),
            r.post_slug,
            r.intent,
            r.status,
            r.sender_email,
            r.created_at.isoformat()[:19],
        )
    console.print(table)
    console.print(f"[dim]{len(rows)} campaign(s)[/dim]")


@outreach_campaigns_app.command("show")
def outreach_campaigns_show(
    campaign_id: int = typer.Argument(..., help="Campaign ID."),
):
    """Show a campaign's full row + per-status send counts."""
    svc = _outreach_svc()
    async def _both():
        return await svc.get_campaign(campaign_id), await svc.campaign_stats(campaign_id)
    camp, stats = _run(_both())
    console.print(f"[bold]Campaign #{camp.id}[/bold] — {camp.name}")
    console.print(f"  post:        {camp.post_slug}")
    console.print(f"  post title:  {camp.post_title}")
    console.print(f"  category:    {camp.post_category or '—'}")
    console.print(f"  tags:        {', '.join(camp.post_tags or []) or '—'}")
    console.print(f"  intent:      {camp.intent}")
    console.print(f"  status:      {camp.status}")
    console.print(f"  sender:      {camp.sender_name} <{camp.sender_email}>")
    console.print(f"  model:       {camp.composer_model}")
    console.print(f"  created:     {camp.created_at.isoformat()[:19]} UTC")
    if camp.notes:
        console.print(f"  notes:       {camp.notes}")
    console.print()
    console.print("[bold]Audience[/bold]")
    console.print(
        f"  total={stats.total}  pending={stats.pending}  composed={stats.composed}  "
        f"sent={stats.sent}  skipped={stats.skipped}  failed={stats.failed}"
    )
    console.print(
        f"  opens: {stats.opens} ({stats.unique_opens} unique)  "
        f"clicks: {stats.clicks} ({stats.unique_clicks} unique)"
    )


@outreach_audience_app.command("add")
def outreach_audience_add(
    campaign_id: int = typer.Option(..., "--campaign", "-c", help="Campaign ID."),
    contact_ids: str = typer.Option("", "--contact-ids", help="Comma-separated firm_contacts.id values."),
    pif_ids: str = typer.Option("", "--pif-ids", help="Comma-separated PIF firm ids — expands to all contacts at those firms with an email."),
    exclude_recent_days: int = typer.Option(14, "--exclude-recent-days", help="Skip contacts emailed in the last N days (across all campaigns). 0 disables."),
):
    """Add recipients to a campaign. Pass either --contact-ids directly,
    or --pif-ids to expand a firm list into all its emailable contacts.
    Skips contacts without an email and dedupes against the campaign."""
    svc = _outreach_svc()
    ids = [s.strip() for s in (contact_ids or "").split(",") if s.strip()]
    if pif_ids:
        firm_ids = [s.strip() for s in pif_ids.split(",") if s.strip()]
        expanded = _run(svc.resolve_contacts_by_pif_ids(firm_ids))
        ids.extend(expanded)
        ids = list(dict.fromkeys(ids))  # de-dupe, preserve order
    if not ids:
        console.print("[red]No contacts to add — pass --contact-ids or --pif-ids.[/red]")
        raise typer.Exit(code=2)
    res = _run(svc.add_contacts_to_campaign(
        campaign_id=campaign_id,
        contact_ids=ids,
        exclude_recent_days=exclude_recent_days,
    ))
    console.print(
        f"[green]Added {res.added}[/green]  "
        f"(skipped: {res.skipped_no_email} no-email, "
        f"{res.skipped_duplicate} dup, "
        f"{res.skipped_recent_outreach} recent)"
    )


@outreach_app.command("compose")
def outreach_compose(
    send_id: int = typer.Option(..., "--send", "-S", help="outreach_sends.id"),
    regenerate: bool = typer.Option(False, "--regenerate", help="Force a re-render even if a composed body is cached."),
    model: str = typer.Option("", "--model", help="Override composer model (default: campaign's composer_model)."),
):
    """Call the LLM composer for one send. Cached — second call is a no-op
    unless --regenerate. Prints subject + reasoning + a plaintext preview."""
    svc = _outreach_svc()
    row = _run(svc.compose_for_send(send_id, regenerate=regenerate, model=model or None))
    console.print(f"[bold]Send #{row.id}[/bold]  →  {row.recipient_email}  ({row.firm_name or '—'})")
    console.print(f"[dim]model: {row.composer_model}  status: {row.status}[/dim]")
    console.print(f"[bold]Subject:[/bold] {row.composed_subject}")
    console.print(f"[bold]Preheader:[/bold] {row.composed_preheader}")
    if row.composed_reasoning:
        console.print()
        console.print(f"[dim]Reasoning:[/dim] {row.composed_reasoning}")
    console.print()
    console.print("[bold]Plaintext preview[/bold]")
    console.print(row.composed_plaintext)


@outreach_app.command("compose-all")
def outreach_compose_all(
    campaign_id: int = typer.Option(..., "--campaign", "-c", help="Campaign ID."),
    limit: int = typer.Option(0, "--limit", "-n", help="Stop after N composes (0 = all pending)."),
    regenerate: bool = typer.Option(False, "--regenerate", help="Recompose rows that already have a composed body."),
):
    """Batch-compose every pending recipient in a campaign. Useful before
    a step-through review session so previews don't block on the LLM."""
    svc = _outreach_svc()
    statuses = ("pending",) if not regenerate else ("pending", "composed", "failed")
    rows = _run(svc.list_sends(campaign_id, limit=10_000))
    targets = [r for r in rows if r.status in statuses]
    if limit:
        targets = targets[:limit]
    if not targets:
        console.print("[dim]Nothing to compose.[/dim]")
        return
    console.print(f"Composing {len(targets)} send(s)…")
    ok = err = 0
    for r in targets:
        try:
            _run(svc.compose_for_send(r.id, regenerate=regenerate))
            ok += 1
            console.print(f"  [green]✓[/green] #{r.id} {r.recipient_email}")
        except Exception as e:
            err += 1
            console.print(f"  [red]✗[/red] #{r.id} {r.recipient_email} — {type(e).__name__}: {e}")
    console.print(f"[bold]Done.[/bold]  composed={ok}  failed={err}")


@outreach_app.command("preview")
def outreach_preview(
    send_id: int = typer.Option(..., "--send", "-S", help="outreach_sends.id"),
    html_out: str = typer.Option("", "--html-out", help="Write the exact HTML that would be sent to this file path."),
    show_plain: bool = typer.Option(True, "--plain/--no-plain", help="Print plaintext body to stdout."),
):
    """Render exactly what send_now would post to Resend — subject,
    wrapped HTML with tracking pixel + signature, plaintext — without
    sending. Pass --html-out=preview.html and open in a browser."""
    svc = _outreach_svc()
    rendered = _run(svc.render_send(send_id))
    console.print(f"[bold]From:[/bold]    {rendered.from_header}")
    console.print(f"[bold]To:[/bold]      {rendered.to}")
    console.print(f"[bold]Subject:[/bold] {rendered.subject}")
    console.print(f"[dim]click → {rendered.tracked_click_url}[/dim]")
    console.print(f"[dim]pixel → {rendered.open_pixel_url}[/dim]")
    if html_out:
        Path(html_out).write_text(rendered.full_html, encoding="utf-8")
        console.print(f"[green]Wrote {len(rendered.full_html)} chars to {html_out}[/green]")
    if show_plain:
        console.print()
        console.print("[bold]Plaintext[/bold]")
        console.print(rendered.full_plaintext)


@outreach_app.command("next")
def outreach_next(
    campaign_id: int = typer.Option(..., "--campaign", "-c", help="Campaign ID."),
):
    """Show the next send the step-through UI would surface — composed
    rows first, then pending. Prints `none` if the campaign is drained."""
    svc = _outreach_svc()
    row = _run(svc.get_next_for_review(campaign_id))
    if not row:
        console.print("[dim]none — campaign drained.[/dim]")
        return
    console.print(f"[bold]Send #{row.id}[/bold]  status={row.status}  to={row.recipient_email}  ({row.firm_name or '—'})")
    if row.composed_subject:
        console.print(f"[bold]Subject:[/bold] {row.composed_subject}")


@outreach_app.command("send")
def outreach_send(
    send_id: int = typer.Option(..., "--send", "-S", help="outreach_sends.id"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
):
    """Send ONE composed email (real Resend call). Confirms before firing
    unless --yes. Use `outreach send-batch` for many at once."""
    svc = _outreach_svc()
    row = _run(svc.get_send(send_id))
    if not yes:
        confirm = typer.confirm(
            f"Send email to {row.recipient_email} ({row.firm_name or '—'}) "
            f"with subject {row.composed_subject!r}?",
            default=False,
        )
        if not confirm:
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit(code=1)
    res = _run(svc.send_now(send_id))
    console.print(
        f"[green]Sent #{res.send_id}[/green]  message_id={res.message_id}  transport={res.transport}"
    )


@outreach_app.command("send-batch")
def outreach_send_batch(
    campaign_id: int = typer.Option(..., "--campaign", "-c", help="Campaign ID."),
    limit: int = typer.Option(10, "--limit", "-n", help="Max sends this batch (safety cap)."),
    auto: bool = typer.Option(False, "--auto", help="Skip the per-send confirmation prompt."),
    pause_seconds: float = typer.Option(0.0, "--pause", help="Sleep this many seconds between sends."),
):
    """Send all composed-but-not-sent rows in a campaign, up to --limit.
    Without --auto, prompts before each send. Skips composed rows you
    don't confirm — they stay composed for later review."""
    svc = _outreach_svc()
    rows = _run(svc.list_sends(campaign_id, status="composed", limit=limit))
    if not rows:
        console.print("[dim]Nothing composed-and-unsent in this campaign.[/dim]")
        return
    console.print(f"{len(rows)} composed send(s) up for delivery (limit={limit}).")
    sent = skipped = failed = 0
    for r in rows:
        if not auto:
            confirm = typer.confirm(
                f"  → send #{r.id} to {r.recipient_email} — {r.composed_subject!r}?",
                default=False,
            )
            if not confirm:
                skipped += 1
                continue
        try:
            res = _run(svc.send_now(r.id))
            sent += 1
            console.print(f"  [green]✓ sent[/green] #{r.id}  msg={res.message_id}")
        except Exception as e:
            failed += 1
            console.print(f"  [red]✗ failed[/red] #{r.id} — {type(e).__name__}: {e}")
        if pause_seconds > 0 and (sent + failed) < len(rows):
            import time
            time.sleep(pause_seconds)
    console.print(f"[bold]Done.[/bold]  sent={sent}  skipped={skipped}  failed={failed}")
    _run(svc.mark_campaign_complete_if_drained(campaign_id))


@outreach_app.command("skip")
def outreach_skip(
    send_id: int = typer.Option(..., "--send", "-S", help="outreach_sends.id"),
    reason: str = typer.Option(..., "--reason", "-r", help="Why you're skipping (recorded)."),
):
    """Mark a send as skipped — it won't be sent and won't surface in
    `outreach next`. Already-sent rows can't be skipped."""
    svc = _outreach_svc()
    _run(svc.skip(send_id, reason=reason))
    console.print(f"[yellow]Skipped #{send_id}[/yellow] — {reason}")


@outreach_app.command("edit")
def outreach_edit(
    send_id: int = typer.Option(..., "--send", "-S", help="outreach_sends.id"),
    subject: str = typer.Option("", "--subject", help="Override the subject. Empty string clears the override."),
    body_html_file: str = typer.Option("", "--body-html-file", help="Read HTML body fragment from this file (must contain {{TRACKED_POST_URL}})."),
    plaintext_file: str = typer.Option("", "--plaintext-file", help="Read plaintext body from this file (must contain {{TRACKED_POST_URL}})."),
    editor: str = typer.Option("", "--by", help="Your name/handle — recorded as edited_by."),
):
    """Apply operator hand-edits over the composed body. Edited fields
    override composed fields at send time. Body fields must still contain
    the literal {{TRACKED_POST_URL}} placeholder so tracking survives."""
    svc = _outreach_svc()
    body_html = None
    plaintext = None
    if body_html_file:
        body_html = Path(body_html_file).read_text(encoding="utf-8")
    if plaintext_file:
        plaintext = Path(plaintext_file).read_text(encoding="utf-8")
    row = _run(svc.apply_edits(
        send_id,
        edited_subject=subject if subject != "" else None,
        edited_body_html=body_html,
        edited_plaintext=plaintext,
        edited_by=editor or None,
    ))
    console.print(f"[green]Edits applied to #{row.id}[/green]")
    if row.edited_subject:
        console.print(f"  edited subject: {row.edited_subject}")
    if row.edited_body_html:
        console.print(f"  edited body_html: {len(row.edited_body_html)} chars")
    if row.edited_plaintext:
        console.print(f"  edited plaintext: {len(row.edited_plaintext)} chars")


@outreach_app.command("stats")
def outreach_stats(
    campaign_id: int = typer.Option(..., "--campaign", "-c", help="Campaign ID."),
):
    """Per-status send counts plus open/click totals for a campaign."""
    svc = _outreach_svc()
    s = _run(svc.campaign_stats(campaign_id))
    table = Table(show_header=True, header_style="bold")
    table.add_column("metric")
    table.add_column("value", justify="right")
    for k, v in (
        ("total", s.total), ("pending", s.pending), ("composed", s.composed),
        ("sent", s.sent), ("skipped", s.skipped), ("failed", s.failed),
        ("opens (raw)", s.opens), ("opens (unique)", s.unique_opens),
        ("clicks (raw)", s.clicks), ("clicks (unique)", s.unique_clicks),
    ):
        table.add_row(k, str(v))
    console.print(f"[bold]Campaign #{s.campaign_id}[/bold]")
    console.print(table)


@outreach_app.command("sends")
def outreach_sends(
    campaign_id: int = typer.Option(..., "--campaign", "-c", help="Campaign ID."),
    status: str = typer.Option("", "--status", help="pending | composed | sent | skipped | failed"),
    limit: int = typer.Option(200, "--limit", "-n"),
):
    """List individual sends in a campaign."""
    svc = _outreach_svc()
    rows = _run(svc.list_sends(campaign_id, status=status or None, limit=limit))
    if not rows:
        console.print("[dim]No sends match.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("id", no_wrap=True, justify="right")
    table.add_column("status", no_wrap=True)
    table.add_column("to")
    table.add_column("firm")
    table.add_column("subject")
    table.add_column("sent (UTC)", no_wrap=True)
    for r in rows:
        subj = (r.edited_subject or r.composed_subject or "—")
        table.add_row(
            str(r.id),
            r.status,
            r.recipient_email,
            (r.firm_name or "—")[:30],
            subj[:50] + ("…" if len(subj) > 50 else ""),
            r.sent_at.isoformat()[:19] if r.sent_at else "—",
        )
    console.print(table)
    console.print(f"[dim]{len(rows)} send(s)[/dim]")


@outreach_app.command("events")
def outreach_events(
    campaign_id: int = typer.Option(..., "--campaign", "-c", help="Campaign ID."),
    send_id: int = typer.Option(0, "--send", "-S", help="Filter to one send (0 = all)."),
    limit: int = typer.Option(100, "--limit", "-n"),
):
    """Show open/click events for a campaign — newest first."""
    async def _q():
        from sqlalchemy import select, desc
        from app.db import AsyncSessionLocal
        from app.db.models import LinkEventRow, OutreachSendRow
        async with AsyncSessionLocal() as s:
            q = (
                select(LinkEventRow, OutreachSendRow.recipient_email)
                .join(OutreachSendRow, LinkEventRow.send_id == OutreachSendRow.id)
                .where(OutreachSendRow.campaign_id == campaign_id)
                .order_by(desc(LinkEventRow.ts))
                .limit(limit)
            )
            if send_id:
                q = q.where(LinkEventRow.send_id == send_id)
            return list((await s.execute(q)).all())

    rows = _run(_q())
    if not rows:
        console.print("[dim]No events yet.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("ts (UTC)", no_wrap=True)
    table.add_column("kind", no_wrap=True)
    table.add_column("send", no_wrap=True, justify="right")
    table.add_column("to")
    table.add_column("ip", no_wrap=True)
    table.add_column("user agent")
    for ev, recipient in rows:
        table.add_row(
            ev.ts.isoformat()[:19],
            ev.kind,
            str(ev.send_id),
            recipient,
            ev.ip or "—",
            (ev.user_agent or "—")[:60],
        )
    console.print(table)
    console.print(f"[dim]{len(rows)} event(s)[/dim]")


@composer_ab_app.command("variants")
def composer_ab_variants():
    """List composer skill variants with allocation and active state."""
    from app.services.lead_email_composer_variants import discover_composer_skill_variants

    table = Table(title="Composer A/B variants")
    for col in ("key", "label", "active", "weight", "baseline"):
        table.add_column(col)
    for v in discover_composer_skill_variants():
        table.add_row(v.key, v.label, str(v.active), str(v.allocation_weight), str(v.is_baseline))
    console.print(table)


@composer_ab_app.command("assign")
def composer_ab_assign(contact_id: str = typer.Argument(..., help="Contact id to preview assignment for.")):
    """Preview the deterministic variant assignment for a contact."""
    from app.services.lead_email_composer_variants import choose_composer_skill_variant

    v = choose_composer_skill_variant(contact_id)
    console.print(f"{contact_id} -> {v.key} ({v.label})")


@composer_ab_app.command("report")
def composer_ab_report_cmd(
    days: int = typer.Option(60, "--days", help="Lookback window."),
    as_json: bool = typer.Option(False, "--json", help="Print raw JSON."),
):
    """Persona-blocked A/B report with beta-binomial verdicts vs baseline."""
    import asyncio as _asyncio

    from app.services.lead_email_composer_variants import composer_ab_report

    report = _asyncio.run(composer_ab_report(days=days))
    if as_json:
        console.print_json(json.dumps(report))
        return
    table = Table(title=f"Composer A/B — {report['axis']} ({report['days']}d)")
    for col in ("variant", "sent", "opened", "replied", "declined", "open_rate", "reply_rate", "P>base(opens)", "P>base(replies)", "verdict"):
        table.add_column(col)
    for arm in report["arms"]:
        table.add_row(
            arm["variant"], str(arm["sent"]), str(arm["opened"]), str(arm["replied"]),
            str(arm["declined"]),
            "-" if arm["open_rate"] is None else f"{arm['open_rate']:.2f}",
            "-" if arm["reply_rate"] is None else f"{arm['reply_rate']:.2f}",
            "-" if arm["p_beats_baseline_opens"] is None else f"{arm['p_beats_baseline_opens']:.2f}",
            "-" if arm["p_beats_baseline_replies"] is None else f"{arm['p_beats_baseline_replies']:.2f}",
            arm["verdict"],
        )
    console.print(table)
    for w in report["warnings"]:
        console.print(f"[yellow]warning:[/yellow] {w}")


@pif_app.command("status")
def pif_status():
    """Show the native PI-firm directory status (firm count, ICP tiers, last sync)."""
    console.print_json(data=_get("/api/pif/status"))


@pif_app.command("sync")
def pif_sync():
    """Pull the full PI-firm directory from emailtag's pif-info API into possibleos.

    Safe to run regardless of the PIF_DIRECTORY_NATIVE flag — the flag only
    governs whether lead-gen *matching* reads from this table, so you can warm
    it before cutover."""
    console.print_json(data=_post("/api/pif/sync", json_body=None, timeout=600.0))


@pif_app.command("ingest-contacts")
def pif_ingest_contacts():
    """Populate firm_contacts from the directory's titled contacts + leadership,
    then map personas. Local-only; this is the lead-supply unlock (titles ->
    personas, firm names) that lifts daily eligible leads."""
    console.print_json(data=_post("/api/pif/ingest-contacts", json_body=None, timeout=600.0))


@reviews_app.command("extract")
def reviews_extract(
    pif_id: str = typer.Argument(..., help="Firm pif_id whose pasted Yelp reviews to extract."),
    force: bool = typer.Option(False, "--force", help="Re-extract even if the raw text is unchanged."),
):
    """Extract citable pain-point quotes from a firm's pasted raw Yelp reviews
    (writes the structured block read by the lead-gen gate + composer)."""
    console.print_json(data=_post(f"/api/firms/{pif_id}/extract?force={str(force).lower()}", json_body=None, timeout=240.0))


@reviews_app.command("extract-all-pending")
def reviews_extract_all(
    limit: int = typer.Option(200, help="Max firms to process."),
    force: bool = typer.Option(False, "--force", help="Re-extract even if unchanged."),
):
    """Backfill: extract every firm with raw Yelp reviews but a missing/stale
    extraction. Runs the service directly (bulk/offline; avoids HTTP timeout)."""
    import asyncio as _asyncio
    from app.services.review_extraction import extract_all_pending
    console.print_json(data=_asyncio.run(extract_all_pending(limit=limit, force=force)))


_DECISION_AREAS = {"lead-gen", "deliverability", "data-arch", "website", "infra", "process", "product"}


def _decisions_dir() -> Path:
    # app/cli.py -> repo root is parents[1]
    return Path(__file__).resolve().parents[1] / "docs" / "decisions"


def _decision_file_for(day: str) -> Path:
    return _decisions_dir() / f"{day}.md"


def _next_decision_id(text: str, day: str) -> str:
    nums = [int(m) for m in re.findall(rf"^## D-{re.escape(day)}-(\d+)", text, re.M)]
    return f"D-{day}-{(max(nums) + 1) if nums else 1:02d}"


@decisions_app.command("add")
def decisions_add(
    title: str = typer.Argument(..., help="Short decision title."),
    area: str = typer.Option(..., "--area", help=f"One of: {', '.join(sorted(_DECISION_AREAS))}"),
    why: str = typer.Option("", "--why", help="Rationale / what it beats."),
    decision: str = typer.Option("", "--decision", help="Full decision text (defaults to the title)."),
    status: str = typer.Option("accepted", "--status", help="accepted | superseded by D-… | reversed"),
    refs: str = typer.Option("", "--refs", help="commit sha / flag / file / PR (optional)."),
):
    """Append a formatted decision to today's (UTC) decision log.

    Creates docs/decisions/<UTC-date>.md with a header if it doesn't exist, and
    auto-assigns the next D-<date>-NN id. Append-only — never rewrites history.
    """
    from datetime import datetime, timezone

    if area not in _DECISION_AREAS:
        console.print(f"[yellow]warning:[/yellow] area '{area}' not in taxonomy ({', '.join(sorted(_DECISION_AREAS))}). "
                      f"Add it to docs/decisions/README.md if it's a real new area.")
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = _decision_file_for(day)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text() if path.exists() else ""
    if not existing:
        existing = f"# Decisions — {day}\n"
    did = _next_decision_id(existing, day)
    entry = [
        f"\n## {did} — {title}",
        f"- **Area:** {area}",
        f"- **Status:** {status}",
        f"- **Decision:** {decision.strip() or title}",
        f"- **Why:** {why.strip()}",
    ]
    if refs.strip():
        entry.append(f"- **Refs:** {refs.strip()}")
    entry.append("")
    path.write_text(existing.rstrip("\n") + "\n" + "\n".join(entry))
    console.print(f"[green]logged[/green] {did} → {path.relative_to(_decisions_dir().parents[1])}")


@decisions_app.command("today")
def decisions_today():
    """Print today's (UTC) decision log file."""
    from datetime import datetime, timezone

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = _decision_file_for(day)
    if not path.exists():
        console.print(f"[dim]No decisions logged yet for {day} ({path}).[/dim]")
        return
    console.print(path.read_text())


@decisions_app.command("areas")
def decisions_areas():
    """List the decision-log area taxonomy."""
    for a in sorted(_DECISION_AREAS):
        console.print(f"- {a}")


if __name__ == "__main__":
    app()
