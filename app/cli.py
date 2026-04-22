"""Autocaller CLI — headless ops over the FastAPI backend + DB.

The CLI is a thin client: call-related commands talk to the running FastAPI
daemon on loopback, while bulk-lead and config commands touch the DB / .env
directly. Uses Typer for arg parsing + Rich for tabular output.

Entry point: `python -m app.cli <command>` or `bin/autocaller <command>`.
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

import httpx
import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    help="Headless autocaller CLI — cold-call PI attorneys via Twilio + OpenAI + Cal.com.",
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

console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _api_base() -> str:
    """Base URL of the FastAPI daemon (loopback by default)."""
    port = os.getenv("BACKEND_PORT", "8000").strip() or "8000"
    return os.getenv("AUTOCALLER_API_BASE", f"http://127.0.0.1:{port}").rstrip("/")


def _get(path: str, **params) -> dict:
    try:
        resp = httpx.get(f"{_api_base()}{path}", params=params or None, timeout=15.0)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        console.print(f"[red]API request failed: {e}[/red]")
        raise typer.Exit(code=1) from e
    return resp.json()


def _post(path: str, json_body: Optional[dict] = None) -> dict:
    try:
        resp = httpx.post(f"{_api_base()}{path}", json=json_body or {}, timeout=30.0)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        console.print(f"[red]API request failed: {e}[/red]")
        raise typer.Exit(code=1) from e
    return resp.json() if resp.content else {}


def _run(coro):
    """Run an async coroutine to completion for DB-direct CLI commands."""
    return asyncio.run(coro)


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
# by default so the autocaller starts on actual partners/owners.
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
# status + doctor
# ---------------------------------------------------------------------------

@app.command()
def status():
    """One-shot system status summary."""
    try:
        s = _get("/api/status")
        console.print_json(data=s)
    except typer.Exit:
        console.print("[yellow]Daemon unreachable — run `autocaller serve`.[/yellow]")


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

    table = Table(title="autocaller doctor")
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
        "[dim]Switch default: [/dim][bold]autocaller carrier twilio[/bold][dim] / [/dim]"
        "[bold]autocaller carrier telnyx[/bold][dim]. "
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
    """Pull researched firms from PIF Stats into the autocaller leads table.

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

        # Normalize to E.164-ish
        digits = "".join(c for c in phone if c.isdigit())
        if len(digits) == 10:
            phone = f"+1{digits}"
        elif len(digits) == 11 and digits.startswith("1"):
            phone = f"+{digits}"
        elif not phone.startswith("+"):
            phone = f"+{digits}" if digits else ""

        if not phone or len(digits) < 10 or len(digits) > 15:
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


if __name__ == "__main__":
    app()
