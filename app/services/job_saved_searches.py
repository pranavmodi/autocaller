"""Saved search intent, durable run queue, and immutable run observations."""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import DateTime, Integer, String, select, func, text
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base, AsyncSessionLocal, async_engine
from app.db.models import CareerSearchRunRow
from app.services import daily_career_search as career
from app.services.job_search_sources import source_urls, validate_source_ids

log = logging.getLogger(__name__)
WAKE = asyncio.Event()

class SearchSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=120)
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
    source_ids: list[str] = Field(default_factory=list, max_length=30)
    employer_urls: list[str] = Field(default_factory=list, max_length=30)
    max_candidates: int = Field(10, ge=1, le=100)
    max_sources: int = Field(6, ge=1, le=30)
    schedule_enabled: bool = False
    timezone: str = 'Asia/Kolkata'
    local_time: str = '01:00'

    @model_validator(mode='after')
    def valid(self):
        validate_source_ids(self.source_ids)
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
        if not self.source_ids and not self.employer_urls:
            raise ValueError('Select at least one source or employer careers URL')
        return self

class SaveSearch(BaseModel):
    revision: int = Field(0, ge=0)
    config: SearchSettings

class ParseSearch(BaseModel):
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
        max_candidates=schedule.max_candidates, max_sources=schedule.max_sources,
        schedule_enabled=schedule.enabled, timezone=schedule.timezone, local_time=schedule.local_time)
    async with AsyncSessionLocal() as session:
        await session.execute(insert(SavedSearch).values(id='default', revision=1, config=initial.model_dump(),
            created_at=career.now_utc(), updated_at=career.now_utc()).on_conflict_do_nothing(index_elements=['id']))
        await session.commit()


def profile(config: SearchSettings):
    return career.SearchProfile(name=config.name, target_roles=config.target_roles,
        preferred_industries=config.preferred_industries, location_preferences=config.location_preferences,
        prefer_overseas_employers=config.prefer_overseas_employers, source_ids=config.source_ids,
        source_urls=[*source_urls(config.source_ids), *config.employer_urls],
        precise=True, industry_mode=config.industry_mode, location_mode=config.location_mode,
        employment_type=config.employment_type, employment_mode=config.employment_mode,
        exclusions=config.exclusions, additional_preferences=config.additional_preferences,
        posted_within_days=config.posted_within_days)


def view(row):
    return {'id': row.id, 'revision': row.revision, 'config': row.config,
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
        payload = {'saved_search_id': identity, 'saved_search_revision': row.revision,
            'settings_snapshot': row.config, 'search_profile': profile(settings).model_dump(mode='json'),
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
        return {**summary(row), 'settings': a.get('settings_snapshot') or a.get('search_profile'),
            'results': sorted(results, key=lambda r: ({'match': 0, 'uncertain': 1, 'pending': 2, 'excluded': 3, 'error': 4}.get(r.get('outcome'), 5), -r.get('preference_score', 0))), 'queries': a.get('queries_used') or a.get('queries', []),
            'sources': a.get('search_sources_consulted', []), 'source_checks': a.get('source_checks', []),
            'activity': a.get('activity', []), 'retry_errors': a.get('attempt_errors', []),
            'errors_detail': a.get('errors', []), 'legacy': 'results' not in a}

async def draft(body: ParseSearch):
    from app.services.llm_gateway import call_skill_json
    from app.services.job_search_sources import catalog_payload
    response = await call_skill_json(skill_path=Path(__file__).resolve().parents[1]/'skills/job-search-settings/SKILL.md',
        payload={'description': body.description, 'sources': catalog_payload([]), 'schema': SearchSettings.model_json_schema()},
        required_fields=['config'], model='openclaw/main', timeout_s=90, retries=1, allow_tools=False,
        lane='possibleos-interactive', prompt_cache_key='possibleos:search-settings:v1')
    config = SearchSettings.model_validate(response.parsed['config'])
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
