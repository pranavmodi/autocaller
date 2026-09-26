"""Operator endpoints for the Job agent workspace."""
from fastapi import APIRouter, HTTPException, Query
from app.services import job_agent as service
from app.services import job_agent_processing as processing
from app.services import job_browser
from app.services import job_applicant_profile as applicant_profile

router = APIRouter(prefix="/api/job-agent", tags=["job-agent"])


@router.get('/profile')
async def profile():
    return await applicant_profile.list_answers()


@router.post('/profile')
async def profile_save(body: applicant_profile.ProfileSave):
    return await processing_response(applicant_profile.save(body))


@router.post('/profile/import-answers')
async def profile_import():
    return await applicant_profile.import_browser_answers()


@router.post('/profile/{identity}/remove')
async def profile_remove(identity: str, body: applicant_profile.ProfileArchive):
    return await processing_response(applicant_profile.archive(identity, body))


@router.get('/browser-applications')
async def browser_applications():
    return await job_browser.list_runs()


@router.get('/jobs/{identity}/browser')
async def browser_status(identity: str, after: int | None = Query(None, ge=0)):
    return await processing_response(job_browser.get(identity, after=after))


@router.post('/jobs/{identity}/browser/start')
async def browser_start(identity: str, body: job_browser.StartRequest):
    return await processing_response(job_browser.start(identity, body))


@router.post('/jobs/{identity}/browser/control')
async def browser_control(identity: str, body: job_browser.ControlRequest):
    return await processing_response(job_browser.control(identity, body))


@router.post('/jobs/{identity}/browser/quit-reasons')
async def browser_quit_reasons(identity: str):
    return await processing_response(job_browser.quit_reasons(identity))


@router.get('/jobs/{identity}/browser/screenshot')
async def browser_screenshot(identity: str):
    from fastapi.responses import FileResponse
    path = await processing_response(job_browser.screenshot_path(identity))
    return FileResponse(path, media_type='image/png', headers={'Cache-Control': 'no-store'})


@router.get("/overview")
async def overview():
    return await service.overview()


@router.get("/config")
async def config():
    return await service.configuration()


@router.get("/sources")
async def sources():
    return await service.search_sources()


@router.post("/config")
async def update_config(body: service.ConfigUpdate):
    try:
        return await service.update_config(body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/jobs")
async def jobs(status: service.ReviewStatus | None = None,
               search: str = Query("", max_length=255), page: int = Query(1, ge=1),
               order: service.JobOrder = "posted_desc", category: str = Query("", max_length=64),
               source: service.JobSource | None = None,
               legal_degree: service.LegalDegreeFilter = "exclude",
               contract: service.ContractFilter = "all"):
    return await service.candidates(status, search, page, order, category, source, legal_degree, contract)


@router.post("/collect")
async def collect():
    try:
        return await service.collect()
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, "Could not import listings. See the activity log and retry.") from exc


@router.post("/search")
async def search():
    """Start evidence-backed external discovery; never classifies or applies."""
    try:
        return await service.request_search()
    except Exception as exc:
        raise HTTPException(503, "Could not start job search. Saved jobs and settings are unchanged.") from exc


@router.post("/listings/open")
async def open_listing(body: service.ListingSelection):
    """Open one canonical Leads job listing in the shared Job Agent workflow."""
    try:
        return await service.open_stored_listing(body)
    except KeyError as exc:
        raise HTTPException(404, "Stored job listing not found. Refresh Job Listings and try again.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/listings/import")
async def import_listing(body: service.UrlImportRequest):
    """Verify and store one public job URL; never classifies, prepares or sends."""
    try:
        return await service.import_listing_url(body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            503, "Could not import this job URL. No application or email was started."
        ) from exc


@router.post("/jobs/{identity}/review")
async def review(identity: str, body: service.ReviewUpdate):
    try:
        return await service.review(identity, body)
    except KeyError as exc:
        raise HTTPException(404, "Job not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/events")
async def events(page: int = Query(1, ge=1)):
    return await service.events(page)


@router.get('/resumes')
async def resumes():
    return await processing.resumes()


@router.get('/applications')
async def applications(search: str = Query('', max_length=255),
                       status: str = Query('', max_length=32),
                       page: int = Query(1, ge=1),
                       order: processing.ApplicationOrder = 'updated_desc'):
    return await processing_response(processing.applications(
        search=search, status=status, page=page, order=order))


@router.get('/resume')
async def resume(path: str = Query(..., max_length=1000), download: bool = False):
    from fastapi.responses import FileResponse
    from app.services.job_agent_resumes import resolve_resume
    try:
        file = resolve_resume(path)
        return FileResponse(file, media_type='application/pdf', filename=file.name,
                            content_disposition_type='attachment' if download else 'inline')
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


async def processing_response(operation):
    try:
        return await operation
    except KeyError as exc:
        raise HTTPException(404, 'Job not found') from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get('/jobs/{identity}')
async def job_detail(identity: str):
    return await processing_response(processing.detail(identity))


@router.post('/jobs/{identity}/category')
async def choose_category(identity: str, body: processing.CategoryChoice):
    return await processing_response(processing.choose_category(identity, body))


@router.post('/jobs/{identity}/classify')
async def classify(identity: str):
    return await processing_response(processing.request_classification(identity))


@router.post('/jobs/{identity}/application')
async def application(identity: str, body: processing.ApplicationRequest):
    return await processing_response(processing.request_application(identity, body))


@router.post('/jobs/{identity}/verify-sent')
async def verify_sent(identity: str):
    return await processing_response(processing.verify_application(identity))


@router.post('/sync-comms')
async def sync_comms():
    """Backfill or repair Communications rows for attempted application emails."""
    return await processing.sync_application_comms()


# Saved searches are independent from resume/application actions.
from app.services import job_saved_searches as saved_searches

@router.get('/searches')
async def searches_list():
    return await saved_searches.list_searches()

@router.post('/searches')
async def searches_create(body: saved_searches.SaveSearch):
    return await processing_response(saved_searches.save(body))

@router.post('/searches/draft')
async def searches_draft(body: saved_searches.ParseSearch):
    return await processing_response(saved_searches.draft(body))

@router.post('/searches/{identity}')
async def searches_update(identity: str, body: saved_searches.SaveSearch):
    return await processing_response(saved_searches.save(body, identity))

@router.post('/searches/{identity}/run')
async def searches_run(identity: str):
    return await processing_response(saved_searches.enqueue(identity))

@router.get('/search-runs')
async def search_runs(search_id: str | None = None, page: int = Query(1, ge=1)):
    return await saved_searches.runs(search_id, page)

@router.get('/search-runs/{identity}')
async def search_run(identity: str):
    return await processing_response(saved_searches.run_detail(identity))
