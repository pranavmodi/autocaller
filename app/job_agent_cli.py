"""CLI parity for the Job agent workspace. HTTP helpers supplied by app.cli."""
import json
import shutil
from pathlib import Path

import typer


def register(app, get, post, console):
    group = typer.Typer(help="Job agent: preferences, listing imports, review queue and activity.", no_args_is_help=True)
    app.add_typer(group, name="job-agent")

    def output(value):
        console.print_json(data=value)

    @group.command("status")
    def status():
        output(get("/api/job-agent/overview"))

    @group.command("config")
    def config():
        output(get("/api/job-agent/config"))

    @group.command("configure")
    def configure(file: Path = typer.Option(..., "--file", exists=True, readable=True, dir_okay=False)):
        """Merge a JSON object of preferences into the current saved settings."""
        try:
            changes = json.loads(file.read_text())
            if not isinstance(changes, dict):
                raise ValueError("Expected a JSON object")
        except (ValueError, OSError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        current = get("/api/job-agent/config")
        output(post("/api/job-agent/config", {"revision": current["revision"], "config": {**current["config"], **changes}}))

    @group.command("collect")
    def collect():
        """Queue or resume collection of all matching stored listings; inspect status for progress."""
        output(post("/api/job-agent/collect", {}, timeout=120))

    @group.command("search")
    def search():
        """Search public sources using saved role, industry and location preferences."""
        output(post("/api/job-agent/search", {}))

    @group.command("open-listing")
    def open_listing(
        firm_id: str = typer.Option(..., "--firm-id"),
        source_url: str = typer.Option(..., "--source-url"),
        title: str = typer.Option(..., "--title"),
        job_id: str = typer.Option("", "--job-id"),
        location: str = typer.Option("", "--location"),
    ):
        """Resolve a stored Leads job listing into its canonical Job Agent record."""
        output(post("/api/job-agent/listings/open", {
            "firm_id": firm_id,
            "job_id": job_id or None,
            "source_url": source_url,
            "title": title,
            "location": location or None,
        }))

    @group.command("jobs")
    def jobs(status: str = typer.Option(None), search: str = typer.Option(""),
             page: int = typer.Option(1, min=1), order: str = typer.Option("posted_desc"),
             category: str = typer.Option(""), source: str = typer.Option(None)):
        """Read the queue, optionally filtering by possibleos or external_search provenance."""
        output(get("/api/job-agent/jobs", status=status, search=search, page=page,
                   order=order, category=category, source=source))

    @group.command("review")
    def review(identity: str, status: str = typer.Option(...), revision: int = typer.Option(..., min=1), note: str = typer.Option("")):
        """Record an operator decision; use the revision shown by jobs."""
        output(post(f"/api/job-agent/jobs/{identity}/review", {"revision": revision, "status": status, "note": note}))

    @group.command("events")
    def events(page: int = typer.Option(1, min=1)):
        output(get("/api/job-agent/events", page=page))

    @group.command("resumes")
    def resumes():
        """List reusable CVs and company-specific PDFs prepared for emails."""
        output(get("/api/job-agent/resumes"))

    @group.command("resume-download")
    def resume_download(path: str, output_path: Path = typer.Option(..., "--output", "-o")):
        """Copy one CV returned by job-agent resumes to a local path."""
        from app.services.job_agent_resumes import resolve_resume
        try:
            source = resolve_resume(path)
            target = output_path / source.name if output_path.is_dir() else output_path
            if target.exists():
                raise ValueError(f"Output already exists: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(str(target.resolve()))

    @group.command("show")
    def show(identity: str):
        """Inspect a job's category, selected resume and application progress."""
        output(get(f"/api/job-agent/jobs/{identity}"))

    @group.command("classify")
    def classify(identity: str):
        """Classify this job on demand or retry its classification."""
        output(post(f"/api/job-agent/jobs/{identity}/classify", {}))

    @group.command("category")
    def category(identity: str, category: str = typer.Option(...), revision: int = typer.Option(...)):
        """Choose a category manually, using processing_revision from show."""
        output(post(f"/api/job-agent/jobs/{identity}/category", {"category_id": category or None, "revision": revision}))

    @group.command("prepare")
    def prepare(identity: str, revision: int = typer.Option(...)):
        """Research and prepare an application email without sending."""
        output(post(f"/api/job-agent/jobs/{identity}/application", {"mode": "prepare", "revision": revision}))

    @group.command("apply")
    def apply(identity: str, revision: int = typer.Option(...)):
        """Authorize this job's application email through Zoho CLI."""
        output(post(f"/api/job-agent/jobs/{identity}/application", {"mode": "send", "revision": revision}))

    @group.command("verify-sent")
    def verify_sent(identity: str):
        """Check Zoho Sent and PDF hash; never resends a message."""
        output(post(f"/api/job-agent/jobs/{identity}/verify-sent", {}, timeout=180))

    @group.command("sync-comms")
    def sync_comms():
        """Backfill or repair Communications rows for attempted application emails."""
        output(post("/api/job-agent/sync-comms", {}))
