"""CLI parity for the Job agent workspace. HTTP helpers supplied by app.cli."""
import asyncio
import json
import shutil
from pathlib import Path

import typer


def register(app, get, post, console):
    group = typer.Typer(help="Job agent: preferences, listing imports, review queue and activity.", no_args_is_help=True)
    app.add_typer(group, name="job-agent")

    def output(value):
        console.print_json(data=value)

    @group.command("searches")
    def searches():
        """List saved targeted searches and schedules."""
        output(get('/api/job-agent/searches'))

    @group.command("search-save")
    def search_save(file: Path = typer.Option(..., '--file', exists=True, dir_okay=False),
                    identity: str = typer.Option('', '--id'), revision: int = typer.Option(0, '--revision')):
        """Create or edit a search; edits require the current revision."""
        config = json.loads(file.read_text())
        output(post('/api/job-agent/searches' + ('/' + identity if identity else ''),
                    {'revision': revision, 'config': config}))

    @group.command("search-draft")
    def search_draft(description: str, provider: str = typer.Option("gateway", "--provider"),
                     model: str = typer.Option("gpt-5.6-luna", "--model")):
        """Convert plain language to editable search settings; does not save or run."""
        output(post('/api/job-agent/searches/draft', {'description': description, 'ai_provider': provider, 'openai_model': model}, timeout=120))

    @group.command("search-run")
    def search_run(identity: str):
        """Queue a saved search once; returns its durable run ID."""
        output(post(f'/api/job-agent/searches/{identity}/run', {}))

    @group.command("search-runs")
    def search_runs(search_id: str = typer.Option('', '--search-id'), page: int = typer.Option(1, min=1)):
        output(get('/api/job-agent/search-runs', search_id=search_id or None, page=page))

    @group.command("search-results")
    def search_results(identity: str):
        """Inspect snapshot, queries, sources, per-job outcomes and errors."""
        output(get(f'/api/job-agent/search-runs/{identity}'))

    @group.command("status")
    def status():
        output(get("/api/job-agent/overview"))

    @group.command("config")
    def config():
        output(get("/api/job-agent/config"))

    @group.command("sources")
    def sources():
        """List available, enabled and disabled public job-search sources."""
        output(get("/api/job-agent/sources"))

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

    @group.command("import-url")
    def import_url(source_url: str):
        """Verify one public job URL and add or reuse its Job Agent record; never sends."""
        output(post("/api/job-agent/listings/import", {"source_url": source_url}, timeout=900))

    @group.command("jobs")
    def jobs(status: str = typer.Option(None), search: str = typer.Option(""),
             page: int = typer.Option(1, min=1), order: str = typer.Option("posted_desc"),
             category: str = typer.Option(""), source: str = typer.Option(None),
             legal_degree: str = typer.Option("exclude", "--legal-degree"),
             contract: str = typer.Option("all", "--contract")):
        """Read the queue; legal-degree roles are excluded by default."""
        output(get("/api/job-agent/jobs", status=status, search=search, page=page,
                   order=order, category=category, source=source, legal_degree=legal_degree,
                   contract=contract))

    @group.command("backfill-contract-status")
    def backfill_contract_status(
        batch_size: int = typer.Option(20, "--batch-size", min=1, max=50),
        limit: int = typer.Option(None, "--limit", min=1),
        force: bool = typer.Option(False, "--force"),
    ):
        """Classify stored jobs as contract, non-contract or unknown with Jev."""
        from app.services.job_contract_classification import backfill_existing_jobs
        output(asyncio.run(backfill_existing_jobs(
            batch_size=batch_size, limit=limit, force=force,
        )))

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

    @group.command("applications")
    def applications(status: str = typer.Option(""), search: str = typer.Option(""),
                     page: int = typer.Option(1, min=1),
                     order: str = typer.Option("updated_desc")):
        """List every started application workflow, including drafts and stopped attempts."""
        output(get("/api/job-agent/applications", status=status, search=search,
                   page=page, order=order))

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

    @group.command('profile')
    def applicant_profile():
        """Read reusable applicant answers with source context and scope."""
        output(get('/api/job-agent/profile'))

    @group.command('profile-save')
    def profile_save(file: Path = typer.Option(..., '--file', exists=True)):
        """Save profile JSON: question, answer, scope, scope_value; id/revision to edit."""
        output(post('/api/job-agent/profile', json.loads(file.read_text())))

    @group.command('profile-remove')
    def profile_remove(identity: str, revision: int = typer.Option(...)):
        """Stop reusing a saved answer; preserve historical application records."""
        output(post(f'/api/job-agent/profile/{identity}/remove', {'revision':revision}))

    @group.command('profile-import-answers')
    def profile_import_answers():
        """Idempotently import previous operator answers from website applications."""
        output(post('/api/job-agent/profile/import-answers', {}))

    @group.command('browser-applications')
    def browser_applications():
        """List website application runs separately from email applications."""
        output(get('/api/job-agent/browser-applications'))

    @group.command('browser-start')
    def browser_start(identity: str, revision: int = typer.Option(...),
                      provider: str = typer.Option(None, '--provider'),
                      authorize_submit: bool = typer.Option(False, '--authorize-submit')):
        """Authorize one website application with the selected resume."""
        if not authorize_submit:
            raise typer.BadParameter('Use --authorize-submit only when the user authorized website submission.')
        output(post(f'/api/job-agent/jobs/{identity}/browser/start',
                    {'revision': revision, 'authorize_submit': True, 'provider': provider}))

    @group.command('browser-provider')
    def browser_provider(provider: str, model: str = typer.Option(None, '--model')):
        """Set the default gateway/openai provider and optional OpenAI model."""
        if provider not in {'gateway', 'openai'}:
            raise typer.BadParameter('Provider must be gateway or openai.')
        current = get('/api/job-agent/config')
        config = {**current['config'], 'browser_ai_provider': provider}
        if model is not None:
            config['browser_openai_model'] = model
        output(post('/api/job-agent/config', {'revision': current['revision'], 'config': config}))

    @group.command('browser-status')
    def browser_status(identity: str, after: int = typer.Option(None, min=0)):
        """Inspect page, pending question, confirmation and paginated events."""
        output(get(f'/api/job-agent/jobs/{identity}/browser', after=after))

    @group.command('browser-control')
    def browser_control(identity: str, action: str = typer.Option(...),
                        revision: int = typer.Option(...),
                        reason: str = typer.Option('', '--reason', help='Optional reason for quitting this application.'),
                        provider: str = typer.Option(None, '--provider'),
                        question_id: str = typer.Option(None, '--question-id'),
                        answer_file: Path = typer.Option(None, '--answer-file', exists=True),
                        remember: bool = typer.Option(True, '--remember/--this-application-only')):
        """Control a run; challenge uses a human-supplied one-time code without saving it."""
        output(post(f'/api/job-agent/jobs/{identity}/browser/control', {
            'revision': revision, 'action': action, 'question_id': question_id, 'provider': provider, 'reason': reason,
            'answer': answer_file.read_text() if answer_file else '', 'remember': remember}))

    @group.command('browser-quit-reasons')
    def browser_quit_reasons(identity: str):
        """Suggest editable reasons for stopping; does not quit or save answers."""
        output(post(f'/api/job-agent/jobs/{identity}/browser/quit-reasons', {}))

    @group.command('browser-screenshot')
    def browser_screenshot(identity: str, output_path: Path = typer.Option(..., '--output')):
        """Copy the current browser screenshot on the server to a local file."""
        from app.services.job_browser import screenshot_path
        if output_path.exists():
            raise typer.BadParameter('Output file already exists.')
        shutil.copyfile(asyncio.run(screenshot_path(identity)), output_path)
        console.print(str(output_path.resolve()))

    @group.command("sync-comms")
    def sync_comms():
        """Backfill or repair Communications rows for attempted application emails."""
        output(post("/api/job-agent/sync-comms", {}))
