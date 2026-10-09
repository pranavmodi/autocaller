"""Saved search intent, durable run queue, and immutable run observations."""
from __future__ import annotations
import asyncio
import hashlib
import logging
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import DateTime, Integer, String, select, func, text
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base, AsyncSessionLocal, async_engine
from app.db.models import CareerSearchRunRow
from app.services import daily_career_search as career
from app.services.job_search_sources import ALL_SOURCE_IDS, all_source_catalog, resolved_source_urls, source_urls
from app.services.career_job_store import source_identity

log = logging.getLogger(__name__)
WAKE = asyncio.Event()

class SearchSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=120)
    description: str = Field('', max_length=5000)
    target_roles: str = Field(min_length=1, max_length=2000)
    preferred_industries: str = Field(min_length=1, max_length=2000)
    industry_mode: Literal['required', 'preferred'] = 'required'
    location_preferences: str = Field(min_length=1, max_length=2000)
    location_mode: Literal['required', 'preferred'] = 'preferred'
    employment_type: Literal['any', 'contract', 'non_contract'] = 'any'
    employment_mode: Literal['required', 'preferred'] = 'preferred'
    exclusions: str = Field('', max_length=2000)
    additional_preferences: str = Field('', max_length=2000)
    prefer_overseas_employers: bool = True
    posted_within_days: int = Field(30, ge=1, le=365)
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    include_quick_save_portals: bool = True
    employer_urls: list[str] = Field(default_factory=list, max_length=30)
    max_candidates: int = Field(10, ge=1, le=100)
    max_sources: int = Field(200, ge=1, le=200)
    ai_provider: Literal['gateway', 'openai'] = 'openai'
    openai_model: str = Field('gpt-5.6-luna', min_length=1, max_length=120, pattern=r'^\S+$')
    schedule_enabled: bool = False
    timezone: str = 'Asia/Kolkata'
    local_time: str = '01:00'

    @model_validator(mode='after')
    def valid(self):
        self.source_ids = list(ALL_SOURCE_IDS)
        self.include_quick_save_portals = True
        self.max_sources = 200
        try:
            ZoneInfo(self.timezone)
            time.fromisoformat(self.local_time)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError('Choose a valid timezone and HH:MM daily time') from exc
        if len(self.local_time) != 5:
            raise ValueError('Daily time must be HH:MM')
        from pydantic import HttpUrl, TypeAdapter
        for url in self.employer_urls:
            TypeAdapter(HttpUrl).validate_python(url)
        for field in ('name', 'target_roles', 'preferred_industries', 'location_preferences'):
            if not getattr(self, field).strip():
                raise ValueError(f'{field} cannot be blank')
        return self

class SaveSearch(BaseModel):
    revision: int = Field(0, ge=0)
    config: SearchSettings

class ParseSearch(BaseModel):
    ai_provider: Literal['gateway', 'openai'] = 'openai'
    openai_model: str = Field('gpt-5.6-luna', min_length=1, max_length=120, pattern=r'^\S+$')
    description: str = Field(min_length=5, max_length=5000)

class SavedSearch(Base):
    __tablename__ = 'job_agent_saved_searches'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

async def ensure():
    from app.services import job_agent
    await job_agent.ensure_tables()
    await career.ensure_tables()
    async with async_engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('possibleos:job-saved-searches:schema', 0))"))
        await conn.run_sync(SavedSearch.__table__.create, checkfirst=True)
    async with AsyncSessionLocal() as session:
        if await session.get(SavedSearch, 'default') is not None: return
    # Preserve the existing broad search and its schedule exactly once.
    config = (await job_agent.configuration())['config']
    schedule = await career.configuration()
    initial = SearchSettings(name='Broad career search', target_roles=config['target_roles'],
        preferred_industries=config['preferred_industries'], location_preferences=config['location_preferences'],
        prefer_overseas_employers=config['prefer_overseas_employers'], source_ids=config['search_source_ids'],
        include_quick_save_portals=config.get('include_quick_save_portals', True),
        max_candidates=schedule.max_candidates, max_sources=schedule.max_sources,
        schedule_enabled=schedule.enabled, timezone=schedule.timezone, local_time=schedule.local_time)
    async with AsyncSessionLocal() as session:
        await session.execute(insert(SavedSearch).values(id='default', revision=1, config=initial.model_dump(),
            created_at=career.now_utc(), updated_at=career.now_utc()).on_conflict_do_nothing(index_elements=['id']))
        await session.commit()


def profile(config: SearchSettings, resolved_urls: list[str] | None = None):
    return career.SearchProfile(name=config.name, target_roles=config.target_roles,
        preferred_industries=config.preferred_industries, location_preferences=config.location_preferences,
        prefer_overseas_employers=config.prefer_overseas_employers, source_ids=list(ALL_SOURCE_IDS),
        source_urls=[*(resolved_urls if resolved_urls is not None else source_urls(ALL_SOURCE_IDS)), *config.employer_urls],
        precise=True, industry_mode=config.industry_mode, location_mode=config.location_mode,
        employment_type=config.employment_type, employment_mode=config.employment_mode,
        exclusions=config.exclusions, additional_preferences=config.additional_preferences,
        posted_within_days=config.posted_within_days)


async def resolved_profile(config: SearchSettings):
    urls = await resolved_source_urls()
    return profile(config, urls)


def view(row):
    return {'id': row.id, 'revision': row.revision, 'config': SearchSettings.model_validate(row.config).model_dump(),
            'created_at': row.created_at.isoformat(), 'updated_at': row.updated_at.isoformat()}

async def list_searches():
    await ensure()
    async with AsyncSessionLocal() as session:
        rows = (await session.scalars(select(SavedSearch).order_by(SavedSearch.created_at))).all()
        return {'items': [view(r) for r in rows]}

async def save(body: SaveSearch, identity: str | None = None):
    await ensure()
    from app.services.career_search_web import public_url
    for url in body.config.employer_urls:
        await public_url(url)
    async with AsyncSessionLocal() as session:
        row = await session.get(SavedSearch, identity, with_for_update=True) if identity else None
        if identity and row is None:
            raise KeyError(identity)
        if row:
            if body.revision != row.revision:
                raise ValueError('This search changed in another window. Reload before saving.')
            row.config = body.config.model_dump()
            row.revision += 1
            row.updated_at = career.now_utc()
        else:
            row = SavedSearch(id=uuid4().hex, revision=1, config=body.config.model_dump(),
                              created_at=career.now_utc(), updated_at=career.now_utc())
            session.add(row)
        await session.commit()
        return view(row)

async def enqueue(identity: str, trigger='manual', scheduled_day: str | None = None):
    await ensure()
    async with AsyncSessionLocal() as session:
        row = await session.get(SavedSearch, identity, with_for_update=True)
        if row is None: raise KeyError(identity)
        previous = await session.scalar(select(CareerSearchRunRow).where(
            CareerSearchRunRow.result['saved_search_id'].astext == identity,
            CareerSearchRunRow.status.in_(['queued', 'running'])).order_by(CareerSearchRunRow.started_at.desc()))
        if previous: return {'id': previous.id, 'run_id': previous.id, 'status': previous.status}
        if trigger == 'scheduled':
            # The row lock makes overlapping timer/worker requests idempotent.
            done = await session.scalar(select(CareerSearchRunRow.id).where(
                CareerSearchRunRow.result['saved_search_id'].astext == identity,
                CareerSearchRunRow.result['search_trigger'].astext == 'scheduled',
                CareerSearchRunRow.scheduled_day == scheduled_day).limit(1))
            if done: return {'status': 'not_due'}
        settings = SearchSettings.model_validate(row.config)
        run_id = uuid4().hex
        resolved = await resolved_profile(settings)
        payload = {'saved_search_id': identity, 'saved_search_revision': row.revision,
            'settings_snapshot': settings.model_dump(), 'search_profile': resolved.model_dump(mode='json'),
            'search_trigger': trigger, 'job_agent_search': True, 'manual_search': trigger == 'manual',
            'phase': 'queued', 'results': [], 'errors': []}
        career.activity(payload, 'queued', 'Search queued; waiting for the research worker.')
        session.add(CareerSearchRunRow(id=run_id, scheduled_day=scheduled_day or career.now_utc().date().isoformat(),
            status='queued', started_at=career.now_utc(), result=payload))
        await session.commit()
    WAKE.set()
    return {'id': run_id, 'run_id': run_id, 'status': 'queued'}

async def enqueue_due():
    searches = (await list_searches())['items']
    queued = []
    for item in searches:
        c = SearchSettings.model_validate(item['config'])
        local = career.now_utc().astimezone(ZoneInfo(c.timezone))
        if not c.schedule_enabled or local.time().replace(tzinfo=None) < time.fromisoformat(c.local_time): continue
        # Do not repeat today's legacy broad scheduled run during migration.
        if item['id'] == 'default':
            async with AsyncSessionLocal() as session:
                legacy = (await session.scalars(select(CareerSearchRunRow).where(
                    CareerSearchRunRow.scheduled_day == local.date().isoformat(),
                    CareerSearchRunRow.status.in_(['running', 'completed', 'partial'])))).all()
                if any(not r.result.get('saved_search_id') and career.run_consumes_daily_slot(r) for r in legacy): continue
        queued.append(await enqueue(item['id'], 'scheduled', local.date().isoformat()))
    return {'status': 'scheduled', 'runs': queued}


def run_results(a: dict, status: str) -> list[dict]:
    results = a.get('results')
    if results is None:
        results = [{'candidate': d.get('candidate'), 'decision': d.get('decision'),
                    'outcome': 'legacy', 'reason': (d.get('decision') or {}).get('reason', '')}
                   for d in a.get('decisions', [])]
    seen = {str((r.get('candidate') or {}).get('source_url')) for r in results}
    for candidate in a.get('discovery_candidates', []):
        if not isinstance(candidate, dict) or str(candidate.get('source_url')) in seen: continue
        url = str(candidate.get('source_url'))
        errors = [e.get('error', '') for e in a.get('errors', []) if e.get('source_url') == url]
        decision = next((d.get('decision', {}) for d in a.get('decisions', [])
                         if (d.get('candidate') or {}).get('source_url') == url), {})
        outcome = 'error' if errors else 'uncertain' if status not in ('running', 'queued') else 'pending'
        results = [*results, {'candidate': candidate, 'decision': decision, 'outcome': outcome,
            'reason': '; '.join(errors) or decision.get('reason') or ('Found during discovery; waiting for verification.' if status in ('running', 'queued') else 'No completed assessment was saved.')}]
        seen.add(url)
    return results


def progress(row):
    a = row.result or {}
    results = run_results(a, row.status)
    seen = {str((r.get('candidate') or {}).get('source_url')) for r in results}
    return {'found': len(seen), 'assessed': len(a.get('decisions', [])),
            'saved': len(a.get('stored', [])), 'errors': len(a.get('errors', [])),
            'updated_at': a.get('updated_at'), 'heartbeat_at': a.get('heartbeat_at'),
            'last_activity_at': a.get('last_activity_at'),
            'waiting_for_model': a.get('waiting_for_model', False),
            'model_request': a.get('model_request'),
            'execution_started_at': a.get('execution_started_at'),
            'live_telemetry': bool(a.get('activity'))}


def summary(row):
    audit = row.result or {}
    results = run_results(audit, row.status)
    return {'id': row.id, 'status': row.status, 'search_id': audit.get('saved_search_id'),
        'name': (audit.get('search_profile') or {}).get('name', 'Earlier career search'),
        'trigger': audit.get('search_trigger', 'legacy'), 'phase': audit.get('phase', row.status),
        'started_at': row.started_at.isoformat(),
        'completed_at': row.completed_at.isoformat() if row.completed_at else None,
        'progress': progress(row),
        'ai_provider': (audit.get('settings_snapshot') or {}).get('ai_provider', 'gateway'),
        'model': ((audit.get('settings_snapshot') or {}).get('openai_model', 'gpt-5.6-luna')
                  if (audit.get('settings_snapshot') or {}).get('ai_provider') == 'openai' else 'openclaw/main'),
        'counts': {k: sum(r.get('outcome') == k for r in results) for k in ['match','uncertain','excluded','error']},
        'new_jobs': audit.get('new_jobs', 0), 'verified': audit.get('verified', 0),
        'duplicates': audit.get('duplicates_skipped', 0), 'errors': len(audit.get('errors', []))}

async def runs(search_id: str | None = None, page: int = 1):
    await ensure()
    conditions = [CareerSearchRunRow.result['saved_search_id'].astext == search_id] if search_id else []
    async with AsyncSessionLocal() as session:
        total = await session.scalar(select(func.count()).select_from(CareerSearchRunRow).where(*conditions))
        rows = (await session.scalars(select(CareerSearchRunRow).where(*conditions)
            .order_by(CareerSearchRunRow.started_at.desc()).offset((page-1)*20).limit(20))).all()
    return {'items': [summary(r) for r in rows], 'total': total, 'page': page, 'total_pages': max(1, (total+19)//20)}

async def run_detail(identity: str):
    await ensure()
    async with AsyncSessionLocal() as session:
        row = await session.get(CareerSearchRunRow, identity)
        if not row: raise KeyError(identity)
        a = row.result or {}
        results = run_results(a, row.status)
        detail = {**summary(row), 'settings': a.get('settings_snapshot') or a.get('search_profile'),
            'results': sorted(results, key=lambda r: ({'match': 0, 'uncertain': 1, 'pending': 2, 'excluded': 3, 'error': 4}.get(r.get('outcome'), 5), -r.get('preference_score', 0))), 'queries': a.get('queries_used') or a.get('queries', []),
            'sources': a.get('search_sources_consulted', []), 'source_checks': a.get('source_checks', []),
            'activity': a.get('activity', []), 'retry_errors': a.get('attempt_errors', []),
            'errors_detail': a.get('errors', []), 'legacy': 'results' not in a}
    if a.get('source_coverage_enabled'):
        from app.services.job_search_source_adapters import coverage
        detail['coverage'] = await coverage(identity)
    else:
        detail['coverage'] = {'run_id': identity, 'total': 0, 'statuses': {},
                              'listings_seen': 0, 'candidates_emitted': 0,
                              'closed': 0, 'items': []}
    return detail


def _discovery_time(row: CareerSearchRunRow, audit: dict) -> str:
    events = [event.get('at') for event in audit.get('activity', [])
              if isinstance(event, dict) and event.get('kind') == 'discovered' and event.get('at')]
    return str(events[-1] if events else row.started_at.isoformat())


def _discovery_occurrences(rows: list[CareerSearchRunRow]) -> list[dict]:
    occurrences = []
    for row in rows:
        audit = row.result or {}
        if audit.get('search_trigger') == 'url_import':
            continue
        row_search_id = str(audit.get('saved_search_id') or '')
        name = (audit.get('search_profile') or {}).get('name') or 'Earlier career search'
        found_at = _discovery_time(row, audit)
        for result in run_results(audit, row.status):
            candidate = result.get('candidate') or {}
            if not isinstance(candidate, dict):
                continue
            job_url = str(candidate.get('source_url') or '')
            title = str(candidate.get('title') or '').strip()
            employer = str(candidate.get('firm_name') or '').strip()
            if not job_url and not title:
                continue
            decision = result.get('decision') or {}
            host = urlsplit(job_url).netloc.lower().removeprefix('www.') if job_url else ''
            candidate_id = str(result.get('candidate_id') or '')
            aliases = []
            if candidate_id:
                aliases.append(f'candidate:{candidate_id}')
            if job_url:
                aliases.append(f'url:{source_identity(job_url)}')
            if not candidate_id and not job_url and (title or employer):
                aliases.append(f'text:{employer.casefold()}|{title.casefold()}')
            occurrences.append({
                'aliases': aliases,
                'candidate_id': candidate_id or None,
                'job_url': job_url or None,
                'title': title or 'Unresolved job',
                'employer_name': employer or 'Employer unknown',
                'location': str(decision.get('location') or ''),
                'posted_date': decision.get('posted_date'),
                'source': host or 'unknown source',
                'outcome': str(result.get('outcome') or 'unknown'),
                'reason': str(result.get('reason') or ''),
                'saved_to_queue': bool(candidate_id),
                'search_id': row_search_id or None,
                'search_name': str(name),
                'run_id': row.id,
                'run_status': row.status,
                'trigger': str(audit.get('search_trigger') or 'legacy'),
                'found_at': found_at,
                'run_started_at': row.started_at.isoformat(),
            })
    return occurrences


def _group_discoveries(occurrences: list[dict]) -> list[dict]:
    """Group the same job while retaining every run-level discovery tag."""
    groups: list[dict] = []
    alias_to_group: dict[str, int] = {}
    for occurrence in sorted(occurrences, key=lambda item: item['found_at']):
        matched = sorted({alias_to_group[alias] for alias in occurrence['aliases']
                          if alias in alias_to_group})
        if matched:
            target = matched[0]
            group = groups[target]
            for other in reversed(matched[1:]):
                if other == target or not groups[other]:
                    continue
                group['discoveries'].extend(groups[other]['discoveries'])
                for alias in groups[other]['aliases']:
                    alias_to_group[alias] = target
                    group['aliases'].add(alias)
                groups[other] = {}
        else:
            target = len(groups)
            group = {'aliases': set(), 'discoveries': []}
            groups.append(group)
        for alias in occurrence['aliases']:
            alias_to_group[alias] = target
            group['aliases'].add(alias)
        public_occurrence = {key: value for key, value in occurrence.items() if key != 'aliases'}
        group['discoveries'].append(public_occurrence)

    output = []
    for group in groups:
        if not group:
            continue
        discoveries = sorted(group['discoveries'], key=lambda item: item['found_at'], reverse=True)
        latest = discoveries[0]
        candidate_id = next((item['candidate_id'] for item in discoveries if item['candidate_id']), None)
        job_url = next((item['job_url'] for item in discoveries if item['job_url']), None)
        identity = candidate_id or job_url or '|'.join(sorted(group['aliases']))
        output.append({
            'id': hashlib.sha256(str(identity).encode()).hexdigest()[:24],
            'candidate_id': candidate_id,
            'job_url': job_url,
            'title': latest['title'],
            'employer_name': latest['employer_name'],
            'location': latest['location'],
            'posted_date': latest['posted_date'],
            'source': latest['source'],
            'latest_outcome': latest['outcome'],
            'latest_reason': latest['reason'],
            'saved_to_queue': any(item['saved_to_queue'] for item in discoveries),
            'first_found_at': discoveries[-1]['found_at'],
            'latest_found_at': latest['found_at'],
            'discoveries': discoveries,
        })
    return sorted(output, key=lambda item: item['latest_found_at'], reverse=True)


async def discoveries(*, search: str = '', search_id: str = '', outcome: str = '',
                      run_id: str = '', page: int = 1, page_size: int = 25) -> dict:
    """Read every final discovery across every saved-search run.

    This is a projection over immutable run history. It does not create another
    job store, and one job may retain several run/search discovery tags.
    """
    await ensure()
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    if outcome not in {'', 'match', 'uncertain', 'excluded', 'error', 'pending', 'legacy'}:
        raise ValueError('outcome must be match, uncertain, excluded, error, pending or legacy')
    async with AsyncSessionLocal() as session:
        rows = (await session.scalars(select(CareerSearchRunRow)
            .order_by(CareerSearchRunRow.started_at.desc()))).all()
    all_occurrences = _discovery_occurrences(list(rows))
    search_options = {}
    run_options = {}
    for occurrence in all_occurrences:
        if occurrence['search_id']:
            search_options[occurrence['search_id']] = {
                'id': occurrence['search_id'], 'name': occurrence['search_name']}
        run_options[occurrence['run_id']] = {
            'id': occurrence['run_id'], 'search_id': occurrence['search_id'],
            'search_name': occurrence['search_name'], 'status': occurrence['run_status'],
            'trigger': occurrence['trigger'], 'started_at': occurrence['run_started_at'],
        }
    items = _group_discoveries(all_occurrences)
    if search_id:
        items = [item for item in items if any(
            discovery['search_id'] == search_id for discovery in item['discoveries'])]
    if run_id:
        items = [item for item in items if any(
            discovery['run_id'] == run_id for discovery in item['discoveries'])]
    if outcome:
        items = [item for item in items if any(
            discovery['outcome'] == outcome for discovery in item['discoveries'])]
    term = search.strip().casefold()
    if term:
        items = [item for item in items if term in item['title'].casefold()
                 or term in item['employer_name'].casefold()
                 or term in (item['location'] or '').casefold()]
    total = len(items)
    start = (page - 1) * page_size
    return {
        'items': items[start:start + page_size],
        'total': total,
        'occurrences': sum(len(item['discoveries']) for item in items),
        'page': page,
        'page_size': page_size,
        'total_pages': max(1, (total + page_size - 1) // page_size),
        'filters': {
            'searches': sorted(search_options.values(), key=lambda item: item['name'].casefold()),
            'runs': sorted(run_options.values(), key=lambda item: item['started_at'], reverse=True),
        },
    }

async def draft(body: ParseSearch):
    from app.services.llm_gateway import call_skill_json
    skill = Path(__file__).resolve().parents[1]/'skills/job-search-settings/SKILL.md'
    payload = {'mode': 'settings', 'description': body.description, 'sources': await all_source_catalog(),
               'schema': SearchSettings.model_json_schema()}
    if body.ai_provider == 'openai':
        from app.services.job_search_ai import direct_search
        async def observe(_event): pass
        response = await direct_search(payload=payload, required='config', model=body.openai_model,
            skill_path=skill, timeout_s=90, allow_tools=False, attempt_observer=observe)
    else:
        response = await call_skill_json(skill_path=skill, payload=payload,
            required_fields=['config'], model='openclaw/main', timeout_s=90, retries=1, allow_tools=False,
            lane='possibleos-interactive', prompt_cache_key='possibleos:search-settings:v1')
    config = SearchSettings.model_validate(response.parsed['config'])
    config.description = body.description
    config.ai_provider = body.ai_provider
    config.openai_model = body.openai_model
    config.schedule_enabled = False  # A draft never schedules itself.
    return {'config': config.model_dump()}

async def worker():
    await ensure()
    while True:
        WAKE.clear()
        try:
            async with AsyncSessionLocal() as session:
                pending = await session.scalar(select(CareerSearchRunRow).where(CareerSearchRunRow.status == 'queued')
                    .order_by(CareerSearchRunRow.started_at).limit(1))
            if pending:
                result = await career.run(queued_run_id=pending.id)
                if result.get('status') != 'busy': continue
        except asyncio.CancelledError: raise
        except Exception: log.exception('Saved search worker failed')
        try: await asyncio.wait_for(WAKE.wait(), 10)
        except TimeoutError: pass
