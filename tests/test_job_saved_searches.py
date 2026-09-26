"""Behavior checks for targeting, independent schedules and immutable runs."""
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import copy
import pytest
from app.services import job_saved_searches as saved
from app.services import daily_career_search as career


def settings(**kwargs):
    return saved.SearchSettings(name='Legal AI LATAM', target_roles='AI agents', preferred_industries='Legal technology',
        location_preferences='Remote from Colombia', source_ids=['remotive'], **kwargs)


def decision(**kwargs):
    evidence = {'source_url': 'https://example.com/job', 'text': 'AI engineer, legal technology, remote Colombia'}
    checks = [{'criterion': k, 'result': 'met', 'reason': f'{k} supported', 'confidence': .9, 'evidence': evidence}
              for k in ['role', 'industry', 'location', 'employment', 'exclusions', 'preferences']]
    return career.Decision(candidate_id='1', status='active', title='AI Engineer', reason='Matches the stated duties',
        posted_date=date(2026,9,25), search_checks=checks, **kwargs)


def test_required_and_preferred_industry_have_different_outcomes():
    d = decision()
    d.search_checks[1].result = 'not_met'
    d.search_checks[1].reason = 'Employer is outside legal technology'
    required = saved.profile(settings(industry_mode='required'))
    preferred = saved.profile(settings(industry_mode='preferred'))
    assert career.assess_search_match(d, required, today=date(2026,9,26))['outcome'] == 'excluded'
    assert career.assess_search_match(d, preferred, today=date(2026,9,26))['outcome'] == 'match'


def test_missing_required_evidence_and_unknown_dates_are_uncertain():
    d = decision()
    d.search_checks = []
    assert career.assess_search_match(d, saved.profile(settings()), today=date(2026,9,26))['outcome'] == 'uncertain'
    d = decision()
    d.posted_date = None
    assert career.assess_search_match(d, saved.profile(settings()), today=date(2026,9,26))['outcome'] == 'uncertain'
    d = decision()
    d.search_checks[0].result = 'not_met'
    d.search_checks[0].evidence = None
    assert career.assess_search_match(d, saved.profile(settings()), today=date(2026,9,26))['outcome'] == 'uncertain'


def test_posting_window_and_required_contract_are_enforced():
    d = decision()
    d.posted_date = date(2026,9,1)
    p = saved.profile(settings(posted_within_days=7))
    assert career.assess_search_match(d,p,today=date(2026,9,26))['outcome'] == 'excluded'
    d = decision()
    d.search_checks[3].result = 'not_met'
    assert career.assess_search_match(d,saved.profile(settings(employment_type='contract', employment_mode='required')),
                                     today=date(2026,9,26))['outcome'] == 'excluded'


def test_schema_rejects_bad_time_sources_and_empty_scope():
    for changes in [{'local_time':'25:00'}, {'timezone':'not/a/zone'}, {'max_candidates':0},
                    {'target_roles':' '}, {'employer_urls':['file:///etc/passwd']}]:
        with pytest.raises(ValueError):
            saved.SearchSettings.model_validate({**settings().model_dump(), **changes})


@pytest.mark.asyncio
async def test_timer_dispatches_saved_schedules_not_legacy_search(monkeypatch):
    enqueue = AsyncMock(return_value={'status':'scheduled'})
    monkeypatch.setattr(saved,'enqueue_due',enqueue)
    monkeypatch.setattr(career,'configuration',AsyncMock(side_effect=AssertionError('legacy path called')))
    assert await career.run(due_only=True) == {'status':'scheduled'}
    enqueue.assert_awaited_once()


@pytest.mark.asyncio
async def test_independent_schedule_timezones_and_disabled_search(monkeypatch):
    rows = [{'id':'india','config':settings(schedule_enabled=True,timezone='Asia/Kolkata',local_time='01:00').model_dump()},
            {'id':'bogota','config':settings(schedule_enabled=True,timezone='America/Bogota',local_time='08:00').model_dump()},
            {'id':'off','config':settings(schedule_enabled=False).model_dump()}]
    monkeypatch.setattr(saved,'list_searches',AsyncMock(return_value={'items':rows}))
    monkeypatch.setattr(career,'now_utc',lambda:datetime(2026,9,26,12,tzinfo=timezone.utc))
    queue = AsyncMock(return_value={'status':'queued'})
    monkeypatch.setattr(saved,'enqueue',queue)
    await saved.enqueue_due()
    queue.assert_awaited_once_with('india','scheduled','2026-09-26')


class Session:
    def __init__(self, row, scalar_values=None):
        self.row=row;self.values=iter(scalar_values or []);self.added=[]
    async def __aenter__(self): return self
    async def __aexit__(self,*args): pass
    async def get(self,*args,**kwargs): return self.row
    async def scalar(self,*args,**kwargs): return next(self.values,None)
    def add(self,row): self.added.append(row)
    async def commit(self): pass


@pytest.mark.asyncio
async def test_run_snapshot_is_saved_before_dispatch_and_repeat_click_returns_same(monkeypatch):
    config=settings().model_dump()
    row=SimpleNamespace(id='s',revision=3,config=config)
    session=Session(row)
    monkeypatch.setattr(saved,'ensure',AsyncMock())
    monkeypatch.setattr(saved,'AsyncSessionLocal',lambda:session)
    result=await saved.enqueue('s')
    assert result['status']=='queued'
    run=session.added[0]
    assert run.result['saved_search_revision']==3
    assert run.result['settings_snapshot']==config
    row.config={**config,'target_roles':'Engineering manager'}
    assert run.result['settings_snapshot']['target_roles']=='AI agents'
    session.values=iter([SimpleNamespace(id=run.id,status='queued')])
    assert (await saved.enqueue('s'))['id']==run.id
    assert len(session.added)==1


@pytest.mark.asyncio
async def test_stale_editor_cannot_overwrite_search(monkeypatch):
    row=SimpleNamespace(revision=2,config=settings().model_dump())
    monkeypatch.setattr(saved,'ensure',AsyncMock())
    monkeypatch.setattr(saved,'AsyncSessionLocal',lambda:Session(row))
    with pytest.raises(ValueError,match='another window'):
        await saved.save(saved.SaveSearch(revision=1,config=settings()),'s')


@pytest.mark.asyncio
async def test_legacy_search_button_queues_default_without_application(monkeypatch):
    from app.services import job_agent
    enqueue=AsyncMock(return_value={'id':'r','status':'queued'})
    monkeypatch.setattr(saved,'enqueue',enqueue)
    assert (await job_agent.request_search())['id']=='r'
    enqueue.assert_awaited_once_with('default')


@pytest.mark.asyncio
async def test_history_includes_failed_findings_without_changing_audit(monkeypatch):
    now=datetime.now(timezone.utc)
    audit={'search_profile':{'name':'Test'},'results':[],
           'discovery_candidates':[{'source_url':'https://example.com/job','title':'AI Engineer'}],
           'errors':[{'source_url':'https://example.com/job','error':'HTTP 403'}]}
    original=copy.deepcopy(audit)
    row=SimpleNamespace(id='r',result=audit,status='partial',started_at=now,completed_at=now)
    monkeypatch.setattr(saved,'ensure',AsyncMock())
    monkeypatch.setattr(saved,'AsyncSessionLocal',lambda:Session(row))
    detail=await saved.run_detail('r')
    assert detail['results'][0]['outcome']=='error'
    assert detail['results'][0]['reason']=='HTTP 403'
    assert audit==original

@pytest.mark.asyncio
async def test_rediscovered_job_is_rechecked_and_links_same_canonical_record(monkeypatch):
    from tests.test_daily_career_search import candidate, decision as old_decision, pages
    from app.services import job_agent, job_contract_classification
    prospect = candidate()
    d = old_decision()
    d.posted_date = None
    audit = {'new_jobs':0,'verified':0,'closed':0,'rejected':0,'candidates':0,'duplicates_skipped':0,
             'llm_calls':0,'errors':[],'stored':[],'decisions':[],'usage':[]}
    monkeypatch.setattr(career,'llm',AsyncMock(return_value={'candidates':[prospect.model_dump(mode='json')]}))
    monkeypatch.setattr(career,'known_source_identities',AsyncMock(return_value={career.source_identity(str(prospect.source_url))}))
    monkeypatch.setattr(career,'checkpoint',AsyncMock())
    monkeypatch.setattr(career,'fetch_page',AsyncMock(side_effect=lambda url: {'requested_url':url,'final_url':url,'http_status':200,'content':'public evidence'}))
    async def verified(batch,*args,**kwargs):
        yield batch[0], d
    monkeypatch.setattr(career,'verified_decisions',verified)
    async def classify(rows): return rows,None
    monkeypatch.setattr(job_contract_classification,'classify_extracted_postings',classify)
    ingest=AsyncMock(return_value={'firm_id':'same-firm','job_id':'same-job','added':0,'source_url':str(prospect.source_url)})
    monkeypatch.setattr(career,'ingest',ingest)
    monkeypatch.setattr(career,'ingest_application_contacts',AsyncMock(return_value={'verified':1,'inserted':0}))
    monkeypatch.setattr(job_agent,'open_stored_listing',AsyncMock(return_value={'candidate':{'id':'existing-canonical'}}))
    monkeypatch.setattr(career,'AsyncSessionLocal',lambda:Session(SimpleNamespace(config={'source_urls':[str(prospect.employer_evidence_url)]})))
    await career.execute('run',career.SearchConfig(),seed_only=False,audit=audit,search_profile=saved.profile(settings()))
    assert not audit['errors']
    assert audit['new_jobs']==0 and audit['duplicates_skipped']==1
    assert audit['results'][0]['candidate_id']=='existing-canonical'
    assert audit['results'][0]['already_known'] is True
    assert audit['results'][0]['outcome']=='uncertain'  # required checks missing, never an invented match
    ingest.assert_awaited_once()


@pytest.mark.asyncio
async def test_daily_slot_is_idempotent_even_for_failed_run(monkeypatch):
    row=SimpleNamespace(id='s',revision=1,config=settings().model_dump())
    session=Session(row,[None,'already-attempted-run'])
    monkeypatch.setattr(saved,'ensure',AsyncMock())
    monkeypatch.setattr(saved,'AsyncSessionLocal',lambda:session)
    assert await saved.enqueue('s','scheduled','2026-09-26') == {'status':'not_due'}
    assert not session.added
