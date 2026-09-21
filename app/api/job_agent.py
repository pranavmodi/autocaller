"""Operator endpoints for the Job agent workspace."""
from fastapi import APIRouter, HTTPException, Query
from app.services import job_agent as service

router = APIRouter(prefix="/api/job-agent", tags=["job-agent"])


@router.get("/overview")
async def overview():
    return await service.overview()


@router.get("/config")
async def config():
    return await service.configuration()


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
               legal_degree: service.LegalDegreeFilter = "exclude"):
    return await service.candidates(status, search, page, order, category, source, legal_degree)


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


from app.services import job_agent_processing as processing


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
