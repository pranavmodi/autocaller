"""Durable job classification and explicitly requested application processing."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import DateTime, Integer, String, func, select, text
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import FirmContactRow
from app.services import job_agent as core
from app.services.job_agent_resumes import RESUME_ROOT, inspect_resume, resolve_resume, resume_catalog
from app.services.llm_gateway import LLMGatewayError, call_skill_json

logger = logging.getLogger(__name__)
SKILL = Path(__file__).resolve().parents[1] / 'skills/job-application-agent/SKILL.md'
CLASSIFICATION_BATCH_SIZE = 15
TYPESAFE_SYSTEM_ONE_URL = 'https://api.typesafe.ai/v1/systemone'
JEV_NO_MATCH = '__no_clear_match__'
SENT_RECHECK_DELAYS_SECONDS = (30, 120, 600)
_wakeup = asyncio.Event()


class JobProcessing(core.Base):
    __tablename__ = 'job_agent_processing'
    candidate_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    classification_status: Mapped[str] = mapped_column(String(32), default='pending', index=True)
    classification: Mapped[dict] = mapped_column(JSONB, default=dict)
    application_status: Mapped[str] = mapped_column(String(32), default='not_started', index=True)
    application: Mapped[dict] = mapped_column(JSONB, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    requested_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=core.now)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=core.now)


class CategoryChoice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=0)
    category_id: str | None = None


class ApplicationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: int = Field(ge=1)
    mode: Literal['prepare', 'send'] = 'prepare'


class ClassificationDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    candidate_id: str
    category_id: str | None
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=2000)
    probabilities: dict[str, float] = Field(default_factory=dict)
    model: str = Field(min_length=1, max_length=120)
    usage: dict = Field(default_factory=dict)


def taxonomy_key(config):
    return hashlib.sha256(json.dumps([{'id': c.id, 'name': c.name, 'description': c.description}
                                      for c in config.resume_categories], sort_keys=True).encode()).hexdigest()


def job_key(posting):
    return hashlib.sha256(json.dumps({k: posting.get(k) for k in
        ('title', 'description_summary', 'responsibilities', 'qualifications', 'role_category')}, sort_keys=True).encode()).hexdigest()


def classification_view(row, config):
    if not row:
        return {'status': 'pending', 'category_id': None, 'reason': 'Waiting for classification', 'resume': None}
    value = dict(row.classification)
    category = next((c for c in config.resume_categories if c.id == value.get('category_id')), None)
    status = row.classification_status
    if status == 'classified' and value.get('source') == 'model' and value.get('confidence', 0) < config.classification_threshold:
        status = 'needs_review'
    if status == 'classified' and not category:
        status = 'needs_review'
    if status == 'classified' and category and not category.resume_path:
        status = 'needs_review'
    return {**value, 'status': status, 'category_name': category.name if category else None,
            'resume': {'path': category.resume_path, 'filename': Path(category.resume_path).name} if category and category.resume_path else None}


def processing_view(row, config):
    return {'processing_revision': row.revision if row else 0,
            'processing_updated_at': row.updated_at.isoformat() if row and row.updated_at else None,
            'classification': classification_view(row, config),
            'application': {**{k: v for k, v in (row.application if row else {}).items() if k not in {'posting', 'preferences', 'resume'}}, 'status': row.application_status if row else 'not_started'},
            'email_status': row.application_status if row and row.application_status in {'sent_verified', 'delivery_unconfirmed', 'sending'} else 'not_tracked',
            'form_status': 'not_tracked'}


async def attach_details(session, rows):
    state = await session.get(core.JobAgentState, 'default')
    config = core.saved_config(state.config) if state else core.JobAgentConfig()
    processing = {row.candidate_id: row for row in (await session.scalars(select(JobProcessing).where(
        JobProcessing.candidate_id.in_([r.id for r in rows])))).all()}
    firm_ids = {str(row.posting.get('firm_id') or '') for row in rows if row.posting.get('firm_id')}
    contacts_by_firm = {firm_id: [] for firm_id in firm_ids}
    if firm_ids:
        contacts = (await session.scalars(select(FirmContactRow).where(
            FirmContactRow.pif_id.in_(firm_ids), FirmContactRow.email.isnot(None),
        ))).all()
        for contact in contacts:
            contacts_by_firm.setdefault(str(contact.pif_id), []).append(contact)
    from app.services.job_agent_research import rank_possibleos_contacts, website_host
    items = []
    for row in rows:
        serialized = core.serialize_candidate(row)
        posting = serialized['posting']
        firm_id = str(posting.get('firm_id') or '')
        official_host = website_host(posting.get('website') or posting.get('employer_evidence_url'))
        ranked = rank_possibleos_contacts(contacts_by_firm.get(firm_id, []), official_host, {firm_id})
        best = ranked[0] if ranked else None
        contact_view = {
            'available': bool(best),
            'count': len(ranked),
            'best': ({key: best[key] for key in ('contact_id', 'email', 'name', 'title', 'kind', 'source')}
                     if best else None),
        }
        items.append({**serialized, **processing_view(processing.get(row.id), config), 'contact': contact_view})
    return items


async def detail(identity):
    await core.ensure_tables()
    async with core.AsyncSessionLocal() as session:
        row = await session.get(core.JobAgentCandidate, identity)
        if not row:
            raise KeyError(identity)
        return (await attach_details(session, [row]))[0]


async def resumes():
    """Return CVs with category mappings and their Job Agent email context."""
    await core.ensure_tables()
    async with core.AsyncSessionLocal() as session:
        state = await session.get(core.JobAgentState, 'default')
        config = core.saved_config(state.config) if state else core.JobAgentConfig()
        rows = (await session.execute(select(JobProcessing, core.JobAgentCandidate).join(
            core.JobAgentCandidate, core.JobAgentCandidate.id == JobProcessing.candidate_id)
            .where(JobProcessing.application_status != 'not_started'))).all()
        applications = []
        for processing, candidate in rows:
            application = dict(processing.application or {})
            attachment = application.get('attachment') if isinstance(application.get('attachment'), dict) else None
            email = application.get('email') if isinstance(application.get('email'), dict) else None
            if not attachment or not email or not attachment.get('path'):
                continue
            applications.append({
                'path': attachment['path'],
                'filename': attachment.get('filename') or Path(attachment['path']).name,
                'candidate_id': processing.candidate_id,
                'firm_name': candidate.posting.get('firm_name'),
                'role_title': candidate.posting.get('title'),
                'application_status': processing.application_status,
                'recipient': email.get('to'),
                'prepared_at': application.get('prepared_at'),
                'updated_at': processing.updated_at.isoformat() if processing.updated_at else None,
                'sent_verified': processing.application_status == 'sent_verified',
            })
    items = await asyncio.to_thread(resume_catalog, config.resume_categories, applications)
    return {'items': items, 'total': len(items),
            'application_count': sum(item['kind'] == 'application' for item in items),
            'category_count': sum(item['kind'] == 'category' for item in items)}


async def enqueue_missing():
    await core.ensure_tables()
    async with core.AsyncSessionLocal() as session:
        await session.execute(text("""INSERT INTO job_agent_processing
            (candidate_id, classification_status, classification, application_status, application, revision, requested_at, updated_at)
            SELECT id, 'pending', '{}', 'not_started', '{}', 1, created_at, now()
            FROM job_agent_candidates ON CONFLICT (candidate_id) DO NOTHING"""))
        await session.commit()


async def choose_category(identity, request: CategoryChoice):
    await enqueue_missing()
    async with core.AsyncSessionLocal() as session:
        row = await session.get(JobProcessing, identity, with_for_update=True)
        if not row:
            raise KeyError(identity)
        if row.revision != request.revision:
            raise ValueError('This job changed. Reload before changing its category.')
        if row.application_status in {'queued', 'preparing', 'queued_send', 'sending', 'sent_verified', 'delivery_unconfirmed'}:
            raise ValueError('The application is in progress or already sent. Its category is locked.')
        state = await session.get(core.JobAgentState, 'default')
        config = core.saved_config(state.config) if state else core.JobAgentConfig()
        category = next((c for c in config.resume_categories if c.id == request.category_id), None)
        if request.category_id and not category:
            raise ValueError('Choose a configured category.')
        candidate = await session.get(core.JobAgentCandidate, identity)
        row.classification = {'category_id': request.category_id, 'confidence': 1.0 if category else 0,
            'reason': 'Category selected by you.' if category else 'No suitable category selected.',
            'source': 'operator', 'taxonomy_key': taxonomy_key(config), 'job_key': job_key(candidate.posting)}
        row.classification_status = 'classified' if category else 'needs_review'
        row.application_status, row.application = 'not_started', {}
        row.revision += 1
        row.updated_at = core.now()
        session.add(core.JobAgentEvent(kind='category_selected', message='Job category selected by operator',
            details={'candidate_id': identity, 'category_id': request.category_id}))
        await session.commit()
    return await detail(identity)


async def request_classification(identity):
    await enqueue_missing()
    async with core.AsyncSessionLocal() as session:
        row = await session.get(JobProcessing, identity, with_for_update=True)
        if not row:
            raise KeyError(identity)
        if row.application_status not in {'not_started', 'failed', 'needs_review', 'ready'}:
            raise ValueError('Cannot reclassify while an application is active or sent.')
        if row.classification_status == 'classifying' and row.classification.get('requested') is True:
            return await detail(identity)
        row.classification_status, row.classification = 'pending', {'requested': True}
        row.application_status, row.application = 'not_started', {}
        row.requested_at = core.now()
        row.revision += 1
        row.updated_at = core.now()
        session.add(core.JobAgentEvent(kind='classification_requested', message='Job classification requested by operator',
            details={'candidate_id': identity}))
        await session.commit()
    _wakeup.set()
    return await detail(identity)


async def ask_application_model(mode, payload, fields):
    timeout_s = int(os.getenv('JOB_AGENT_GATEWAY_TIMEOUT_S', '420'))
    result = await call_skill_json(skill_path=SKILL, payload={'mode': mode, **payload}, required_fields=fields,
        model=os.getenv('JOB_AGENT_MODEL', 'openclaw/neo'), timeout_s=timeout_s, max_tokens=7000, retries=1,
        schema_repair_retries=1, prompt_cache_key='possibleos:job-application-agent:v2')
    return result.parsed


def _jev_text(value) -> str:
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _jev_request(jobs, categories):
    state_jobs = [{key: _jev_text(job.get(key)) for key in
        ('title', 'description_summary', 'responsibilities', 'qualifications',
         'role_category', 'technology_mentions')} for job in jobs]
    criteria = {
        category.id: {'category': category.name, 'definition': category.description}
        for category in categories
    }
    criteria[JEV_NO_MATCH] = {
        'category': 'No clear match',
        'definition': (
            'Choose this when no configured category fits the primary responsibilities, '
            'the evidence is sparse or ambiguous, or mandatory credentials or direct-experience '
            'requirements conflict with the configured category definitions.'
        ),
    }
    rules = [
        'Judge primary responsibilities and mandatory qualifications, not title or employer sector alone.',
        'Incidental mentions of AI, CRM, software, or automation do not make routine legal, intake, sales, clerical, or customer-service work technical.',
        'Apply every inclusion and exclusion in the category definitions.',
        'Choose exactly one configured category or No clear match.',
    ]
    questions = {
        f'job_{index}': {
            'type': 'choice',
            'instructions': {
                'task': f'Which resume category best fits only `jobs[{index}]`?',
                'rules': rules,
            },
            'criteria': criteria,
        }
        for index in range(len(state_jobs))
    }
    return {'state': {'jobs': state_jobs},
            'model': os.getenv('JOB_AGENT_TYPESAFE_MODEL', 'jev-latest'),
            'questions': questions}


def _classification_reason(category, probability, probabilities, categories):
    names = {item.id: item.name for item in categories}
    alternatives = sorted(
        ((key, value) for key, value in probabilities.items()
         if key not in {category.id, JEV_NO_MATCH}),
        key=lambda item: item[1], reverse=True,
    )
    suffix = ''
    if alternatives and alternatives[0][1] > 0:
        suffix = f'; next closest: {names.get(alternatives[0][0], alternatives[0][0])} {alternatives[0][1]:.0%}'
    return (f'Jev matched {category.name} to the job\'s primary responsibilities and '
            f'qualifications ({probability:.0%} category probability{suffix}).')


def _parse_jev_decisions(response, identities, categories):
    if not isinstance(response, dict) or not isinstance(response.get('answers'), dict):
        raise ValueError('TypeSafe response is missing answers.')
    model = response.get('model')
    if not isinstance(model, str) or not model:
        raise ValueError('TypeSafe response is missing its model version.')
    usage = response.get('usage') if isinstance(response.get('usage'), dict) else {}
    by_id = {category.id: category for category in categories}
    option_ids = {*by_id, JEV_NO_MATCH}
    decisions = []
    for index, identity in enumerate(identities):
        answer = response['answers'].get(f'job_{index}')
        if not isinstance(answer, dict) or answer.get('type') != 'choice':
            raise ValueError(f'TypeSafe response is missing Choice answer job_{index}.')
        choice = answer.get('choice')
        probabilities = answer.get('probabilities')
        confidence = answer.get('confidence')
        if choice not in option_ids or not isinstance(probabilities, dict) or set(probabilities) != option_ids:
            raise ValueError(f'TypeSafe Choice answer job_{index} has invalid options.')
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError(f'TypeSafe Choice answer job_{index} has invalid confidence.')
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1
               for value in probabilities.values()) or abs(sum(probabilities.values()) - 1) > 0.02:
            raise ValueError(f'TypeSafe Choice answer job_{index} has invalid probabilities.')
        normalized = {key: float(value) for key, value in probabilities.items()}
        if choice == JEV_NO_MATCH:
            decisions.append(ClassificationDecision(candidate_id=identity, category_id=None,
                confidence=float(confidence), reason='Jev found no clear match among the configured resume categories.',
                probabilities=normalized, model=model, usage=usage))
            continue
        category = by_id[choice]
        decisions.append(ClassificationDecision(candidate_id=identity, category_id=choice,
            confidence=float(confidence),
            reason=_classification_reason(category, normalized[choice], normalized, categories),
            probabilities=normalized, model=model, usage=usage))
    return decisions


async def classify_with_jev(jobs, categories):
    api_key = os.getenv('TYPESAFE_API_KEY', '').strip()
    if not api_key:
        raise RuntimeError('TYPESAFE_API_KEY is not configured.')
    request = _jev_request(jobs, categories)
    timeout_s = int(os.getenv('JOB_AGENT_CLASSIFICATION_TIMEOUT_S', '120'))
    url = os.getenv('TYPESAFE_SYSTEM_ONE_URL', TYPESAFE_SYSTEM_ONE_URL)
    last_error = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=timeout_s, trust_env=False) as client:
                response = await client.post(url, headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                }, json=request)
            if response.status_code in {429, 500, 502, 503, 504} and attempt == 0:
                await asyncio.sleep(0.5)
                continue
            response.raise_for_status()
            return _parse_jev_decisions(response.json(), [job['candidate_id'] for job in jobs], categories)
        except (httpx.TransportError, httpx.HTTPStatusError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt == 0 and isinstance(exc, httpx.TransportError):
                await asyncio.sleep(0.5)
                continue
            break
    raise RuntimeError('TypeSafe Jev classification request failed.') from last_error


async def classify_batch(*, requested_only=False):
    config = core.JobAgentConfig.model_validate((await core.configuration())['config'])
    if not requested_only and not config.classification_enabled:
        return False
    async with core.AsyncSessionLocal() as session:
        query = select(JobProcessing).where(JobProcessing.classification_status == 'pending')
        if requested_only:
            query = query.where(JobProcessing.classification['requested'].astext == 'true')
        else:
            query = query.where(JobProcessing.classification['requested'].astext.is_distinct_from('true'))
        rows = (await session.scalars(query.order_by(JobProcessing.requested_at)
            .limit(1 if requested_only else CLASSIFICATION_BATCH_SIZE).with_for_update(skip_locked=True))).all()
        if not rows:
            return False
        candidates = {r.id: r for r in (await session.scalars(select(core.JobAgentCandidate).where(
            core.JobAgentCandidate.id.in_([r.candidate_id for r in rows])))).all()}
        snapshots = {}
        for row in rows:
            row.classification_status = 'classifying'
            row.revision += 1
            row.updated_at = core.now()
            snapshots[row.candidate_id] = {'revision': row.revision, 'posting': candidates[row.candidate_id].posting}
        await session.commit()
    try:
        jobs = [{'candidate_id': identity, **{key: value['posting'].get(key) for key in
            ('title', 'description_summary', 'responsibilities', 'qualifications',
             'role_category', 'technology_mentions')}} for identity, value in snapshots.items()]
        decisions = await classify_with_jev(jobs, config.resume_categories)
        if len({d.candidate_id for d in decisions}) != len(decisions) or {d.candidate_id for d in decisions} != set(snapshots):
            raise ValueError('Classification response did not match the requested jobs.')
        allowed = {c.id for c in config.resume_categories}
        if any(d.category_id and d.category_id not in allowed for d in decisions):
            raise ValueError('Classification returned an unknown category.')
        async with core.AsyncSessionLocal() as session:
            state = await session.get(core.JobAgentState, 'default')
            current = core.saved_config(state.config) if state else core.JobAgentConfig()
            for decision in decisions:
                row = await session.get(JobProcessing, decision.candidate_id, with_for_update=True)
                if row.revision != snapshots[decision.candidate_id]['revision']:
                    continue  # Never overwrite a newer operator decision.
                candidate = await session.get(core.JobAgentCandidate, decision.candidate_id)
                if taxonomy_key(current) != taxonomy_key(config) or job_key(candidate.posting) != job_key(snapshots[decision.candidate_id]['posting']):
                    row.classification_status = 'pending'
                    continue
                row.classification = {**decision.model_dump(exclude={'candidate_id'}), 'source': 'model',
                    'provider': 'typesafe_jev',
                    'taxonomy_key': taxonomy_key(config), 'job_key': job_key(candidate.posting)}
                row.classification_status = 'classified' if decision.category_id and decision.confidence >= config.classification_threshold else 'needs_review'
                row.revision += 1
                row.updated_at = core.now()
            await session.commit()
    except Exception as exc:
        logger.warning('Job classification failed: %s', type(exc).__name__)
        async with core.AsyncSessionLocal() as session:
            for identity, snapshot in snapshots.items():
                row = await session.get(JobProcessing, identity, with_for_update=True)
                if row.revision == snapshot['revision']:
                    row.classification_status = 'needs_review'
                    row.classification = {'category_id': None, 'reason': 'Classification could not complete. Retry or choose a category.', 'source': 'error'}
                    row.revision += 1
            await session.commit()
    return True


async def request_application(identity, request: ApplicationRequest):
    await enqueue_missing()
    async with core.AsyncSessionLocal() as session:
        row = await session.get(JobProcessing, identity, with_for_update=True)
        if not row:
            raise KeyError(identity)
        # Repeated clicks never create a second send.
        if row.application_status in {'queued', 'preparing', 'queued_send', 'sending', 'sent_verified', 'delivery_unconfirmed'}:
            return await detail(identity)
        if row.revision != request.revision:
            raise ValueError('This job changed. Reload before applying.')
        state = await session.get(core.JobAgentState, 'default')
        config = core.saved_config(state.config) if state else core.JobAgentConfig()
        category = next((c for c in config.resume_categories if c.id == row.classification.get('category_id')), None)
        if classification_view(row, config)['status'] != 'classified' or not category or not category.resume_path:
            raise ValueError('Choose a category with a one-page resume before applying.')
        candidate = await session.get(core.JobAgentCandidate, identity)
        if row.classification.get('job_key') != job_key(candidate.posting):
            raise ValueError('The job responsibilities changed. Classify the current job before applying.')
        if candidate.posting.get('status') == 'closed':
            raise ValueError('This job is marked closed at its source.')
        resume = await asyncio.to_thread(inspect_resume, category.resume_path)
        if row.application_status == 'ready' and request.mode == 'send':
            if row.application.get('resume', {}).get('sha256') != resume['sha256']:
                raise ValueError('The mapped resume changed. Prepare a new email before sending.')
            row.application = {**row.application, 'send_requested': True,
                'authorized_at': core.now().isoformat(), 'phase': 'queued_send',
                'stage': 'Send authorized and queued', 'retryable': False}
            row.application_status = 'queued_send'
        else:
            previous_attempt = int(row.application.get('attempt') or 0)
            row.application = {'run_id': uuid4().hex, 'attempt': previous_attempt + 1,
                'phase': 'queued', 'send_requested': request.mode == 'send',
                'authorized_at': core.now().isoformat() if request.mode == 'send' else None,
                'category_id': category.id, 'resume': resume, 'posting': candidate.posting,
                'preferences': config.model_dump(exclude={'resume_categories'}), 'stage': 'Queued'}
            row.application_status = 'queued'
        row.revision += 1
        row.updated_at = core.now()
        session.add(core.JobAgentEvent(kind='application_requested', message='Application processing requested',
            details={'candidate_id': identity, 'mode': request.mode, 'category_id': category.id}))
        await session.commit()
    _wakeup.set()
    return await detail(identity)


async def set_application(identity, *, status=None, **updates):
    async with core.AsyncSessionLocal() as session:
        row = await session.get(JobProcessing, identity, with_for_update=True)
        row.application = {**row.application, **updates}
        if status:
            row.application_status = status
        row.revision += 1
        row.updated_at = core.now()
        await session.commit()


def next_sent_recheck_at(completed_rechecks, *, now=None):
    """Return the next bounded read-only Sent check, never a send retry."""
    if completed_rechecks >= len(SENT_RECHECK_DELAYS_SECONDS):
        return None
    now = now or core.now()
    return (now + timedelta(seconds=SENT_RECHECK_DELAYS_SECONDS[completed_rechecks])).isoformat()


def sent_recheck_due(application, *, now=None):
    if int(application.get('verification_rechecks') or 0) >= len(SENT_RECHECK_DELAYS_SECONDS):
        return False
    raw = application.get('verification_next_at')
    if not raw:
        return False
    try:
        due = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
    except ValueError:
        return False
    return due <= (now or core.now())


def safe_slug(value):
    return re.sub(r'[^a-zA-Z0-9_-]+', '_', str(value)).strip('_')[:90] or 'job'


async def record_application_communication(identity, application, status, *, verification=None, error=None):
    """Mirror one Job Agent send attempt into the shared Communications log.

    The source identity makes this an idempotent upsert. Sent rechecks can
    therefore enrich the same row with Zoho evidence without implying that a
    second email was sent.
    """
    from app.services.comms_log import log_email

    email = application.get('email') if isinstance(application.get('email'), dict) else None
    if not email:
        return None
    posting = application.get('posting') if isinstance(application.get('posting'), dict) else None
    if not posting:
        async with core.AsyncSessionLocal() as session:
            candidate = await session.get(core.JobAgentCandidate, identity)
            posting = candidate.posting if candidate else {}
    recipient = application.get('recipient') if isinstance(application.get('recipient'), dict) else {}
    verification = verification if isinstance(verification, dict) else {}
    occurred_at = None
    if application.get('send_started_at'):
        try:
            occurred_at = datetime.fromisoformat(str(application['send_started_at']).replace('Z', '+00:00'))
        except ValueError:
            pass
    return await asyncio.to_thread(
        log_email,
        recipient_email=email.get('to', ''),
        recipient_name=recipient.get('name'),
        subject=email.get('subject', ''),
        body=email.get('body_text', ''),
        message_type='job_application',
        transport='zoho_cli',
        message_id=verification.get('provider_message_id') or verification.get('message_id'),
        status=status,
        error=error,
        firm_name=posting.get('firm_name'),
        source_type='job_application',
        source_id=identity,
        occurred_at=occurred_at,
    )


async def sync_application_comms():
    """Backfill or repair Communications rows for attempted Job Agent sends."""
    async with core.AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(JobProcessing, core.JobAgentCandidate)
            .join(core.JobAgentCandidate, core.JobAgentCandidate.id == JobProcessing.candidate_id)
            .where(JobProcessing.application_status.in_(['delivery_unconfirmed', 'sent_verified']))
            .order_by(JobProcessing.updated_at)
        )).all()
    saved = 0
    for processing, candidate in rows:
        application = {**dict(processing.application), 'posting': candidate.posting}
        verification = application.get('verification')
        status = 'sent_verified' if processing.application_status == 'sent_verified' else 'unverified'
        log_id = await record_application_communication(
            processing.candidate_id,
            application,
            status,
            verification=verification,
            error=application.get('error') if status == 'unverified' else None,
        )
        if log_id:
            saved += 1
            await set_application(processing.candidate_id, comms_log_id=log_id)
    return {'considered': len(rows), 'saved': saved, 'failed': len(rows) - saved}


async def duplicate_evidence(email, posting):
    from app.db.models import AgentActionRow, EmailLogRow
    from app.services.job_agent_mail import duplicate_check, _normalized
    async with core.AsyncSessionLocal() as session:
        actions = (await session.scalars(select(AgentActionRow).where(
            AgentActionRow.action_type.in_(['send_email', 'send_approved_lead_gen_draft']),
            AgentActionRow.status.in_(['proposed', 'waiting_for_approval', 'approved', 'queued', 'running', 'succeeded']),
            func.lower(AgentActionRow.input_json['to'].astext) == email['to'].lower()))).all()
        for action in actions:
            payload = action.input_json
            if (_normalized(payload.get('subject', '')) == _normalized(email['subject']) or
                posting['source_url'] in str(payload.get('body', '')) or
                _normalized(posting['title']) in _normalized(payload.get('subject', ''))):
                return {'kind': 'existing_action', 'action_id': action.id, 'status': action.status,
                        'subject': payload.get('subject')}
        logs = (await session.scalars(select(EmailLogRow).where(
            func.lower(EmailLogRow.recipient_email) == email['to'].lower(),
            EmailLogRow.status.in_(['sent', 'sent_verified', 'succeeded'])))).all()
        for log in logs:
            if _normalized(posting['title']) in _normalized(log.subject) or posting['source_url'] in (log.body_excerpt or ''):
                return {'kind': 'email_log', 'email_log_id': log.id, 'subject': log.subject}
    return await asyncio.to_thread(duplicate_check, email, posting)


async def prepare_application(identity, application):
    from app.services.job_agent_research import research_application
    async def update_phase(phase, stage):
        await set_application(identity, phase=phase, stage=stage)

    await set_application(identity, phase='researching', stage='Researching the company, role and recruiting contacts')
    packet = await research_application(application, ask_application_model, update_phase)
    await set_application(identity, phase='checking_duplicates',
        stage='Research and draft verified; checking previous applications', **packet)
    duplicate = await duplicate_evidence(packet['email'], application['posting'])
    if duplicate:
        await set_application(identity, status='needs_review', stage='Possible previous application', duplicate=duplicate,
            phase='needs_review', failed_phase='checking_duplicates', retryable=False,
            error='A matching application or queued email already exists. Check the evidence before proceeding.')
        return
    posting = application['posting']
    directory = RESUME_ROOT / 'applications' / safe_slug(posting['firm_name']) / (safe_slug(posting['title']) + '_' + identity) / ('job-agent_' + application['run_id'])
    directory.mkdir(parents=True, exist_ok=True)
    filename = 'Pranav_Modi_' + safe_slug(posting['firm_name']) + '_' + safe_slug(posting['title']) + '.pdf'
    target = directory / filename
    source = resolve_resume(application['resume']['path'])
    if hashlib.sha256(source.read_bytes()).hexdigest() != application['resume']['sha256']:
        raise ValueError('The resume changed during preparation. Select the current file and try again.')
    await set_application(identity, phase='packaging', stage='Creating the one-page application PDF',
        duplicate_checked_at=core.now().isoformat())
    shutil.copyfile(source, target)
    attachment = await asyncio.to_thread(inspect_resume, str(target))
    attachment.pop('text', None)
    (directory / 'application.json').write_text(json.dumps({**packet, 'resume': attachment, 'job': posting}, indent=2))
    await set_application(identity, status='queued_send' if application['send_requested'] else 'ready',
        stage='Ready to send' if application['send_requested'] else 'Email prepared',
        phase='queued_send' if application['send_requested'] else 'ready', retryable=False,
        error=None, attachment=attachment, prepared_at=core.now().isoformat(), **packet)


async def validate_current_job(identity, posting):
    async with core.AsyncSessionLocal() as session:
        candidate = await session.get(core.JobAgentCandidate, identity)
        if candidate is None or candidate.posting.get('status') == 'closed' or job_key(candidate.posting) != job_key(posting):
            raise ValueError('The job changed or closed after preparation. Review the current listing before sending.')


async def send_application(identity, application):
    from app.services.job_agent_mail import send_cli, verify_sent
    if not application.get('send_requested') or not application.get('authorized_at'):
        raise ValueError('Sending requires an explicit Apply via Zoho action.')
    await validate_current_job(identity, application['posting'])
    attachment = await asyncio.to_thread(inspect_resume, application['attachment']['path'])
    if attachment['sha256'] != application['attachment']['sha256']:
        raise ValueError('The prepared resume changed; sending is blocked.')
    duplicate = await duplicate_evidence(application['email'], application['posting'])
    if duplicate:
        await set_application(identity, status='needs_review', stage='Possible previous application', duplicate=duplicate,
            phase='needs_review', failed_phase='pre_send_checks', retryable=False,
            error='A matching application or queued email already exists.')
        return
    # This is the point of no retry. Crashes/ambiguous transport results require Sent verification.
    send_started_at = core.now().isoformat()
    application = {**application, 'send_started_at': send_started_at}
    await set_application(identity, status='sending', phase='sending', stage='Sending through Zoho CLI',
        send_started_at=send_started_at, retryable=False)
    try:
        result = await asyncio.to_thread(send_cli, application['email'], str(resolve_resume(attachment['path'])))
        comms_log_id = await record_application_communication(identity, application, 'accepted')
        await set_application(identity, provider=result, comms_log_id=comms_log_id,
            phase='verifying_sent', stage='Verifying the copy in Zoho Sent')
        verification = await asyncio.to_thread(verify_sent, application['email'], attachment['sha256'])
        if verification:
            comms_log_id = await record_application_communication(
                identity, application, 'sent_verified', verification=verification)
            await set_application(identity, status='sent_verified', stage='Email verified in Zoho Sent', verification=verification,
                phase='sent_verified', sent_at=core.now().isoformat(), error=None,
                verification_next_at=None, comms_log_id=comms_log_id)
        else:
            checked_at = core.now()
            comms_log_id = await record_application_communication(
                identity, application, 'unverified', error='No matching copy was verified in Zoho Sent.')
            await set_application(identity, status='delivery_unconfirmed', stage='Sent verification needed',
                phase='verification_needed', retryable=True, comms_log_id=comms_log_id,
                verification_checked_at=checked_at.isoformat(), verification_rechecks=0,
                verification_next_at=next_sent_recheck_at(0, now=checked_at),
                error='The send was attempted, but its Sent copy is not verified. No automatic resend will occur.')
    except Exception as exc:
        logger.warning('Job application send needs verification: %s', type(exc).__name__)
        checked_at = core.now()
        comms_log_id = await record_application_communication(
            identity, application, 'unverified', error=f'{type(exc).__name__}: {str(exc)[:300]}')
        await set_application(identity, status='delivery_unconfirmed', stage='Sent verification needed',
            phase='verification_needed', retryable=True, comms_log_id=comms_log_id,
            verification_checked_at=checked_at.isoformat(), verification_rechecks=0,
            verification_next_at=next_sent_recheck_at(0, now=checked_at),
            error='The send result is uncertain. Check Zoho Sent before any further action; no automatic resend will occur.')


async def verify_application(identity):
    from app.services.job_agent_mail import verify_sent
    data = await detail(identity)
    application = data['application']
    if application['status'] not in {'delivery_unconfirmed', 'sending', 'sent_verified'}:
        raise ValueError('No attempted send is available for verification.')
    verified = await asyncio.to_thread(verify_sent, application['email'], application['attachment']['sha256'])
    if verified:
        comms_log_id = await record_application_communication(
            identity, application, 'sent_verified', verification=verified)
        await set_application(identity, status='sent_verified', phase='sent_verified',
            stage='Email verified in Zoho Sent', verification=verified,
            verification_checked_at=core.now().isoformat(), error=None, retryable=False,
            verification_next_at=None,
            comms_log_id=comms_log_id)
    else:
        comms_log_id = await record_application_communication(
            identity, application, 'unverified', error='No matching copy was found in Zoho Sent.')
        await set_application(identity, status='delivery_unconfirmed', phase='verification_needed',
            stage='Sent verification still needed', verification_checked_at=core.now().isoformat(),
            retryable=True, comms_log_id=comms_log_id,
            error='No matching copy was found in Zoho Sent. No resend occurred; check again later or review Zoho Sent manually.')
    return await detail(identity)


async def automatic_sent_recheck(identity, application):
    """Reconcile a delayed Zoho Sent copy. This function has no send path."""
    from app.services.job_agent_mail import verify_sent
    checked_at = core.now()
    verified = await asyncio.to_thread(
        verify_sent, application['email'], application['attachment']['sha256'])
    if verified:
        comms_log_id = await record_application_communication(
            identity, application, 'sent_verified', verification=verified)
        await set_application(identity, status='sent_verified', phase='sent_verified',
            stage='Email verified in Zoho Sent', verification=verified,
            verification_checked_at=checked_at.isoformat(), verification_next_at=None,
            error=None, retryable=False, comms_log_id=comms_log_id)
        return
    count = int(application.get('verification_rechecks') or 0)
    next_at = next_sent_recheck_at(count, now=checked_at)
    comms_log_id = await record_application_communication(
        identity, application, 'unverified', error='No matching copy was found in Zoho Sent.')
    await set_application(identity, status='delivery_unconfirmed', phase='verification_needed',
        stage='Sent verification scheduled' if next_at else 'Automatic Sent checks completed',
        verification_checked_at=checked_at.isoformat(), verification_next_at=next_at,
        retryable=True, comms_log_id=comms_log_id,
        error=('Zoho Sent has not synchronized yet. Another read-only check is scheduled; no resend will occur.'
               if next_at else
               'No matching copy was found after the automatic checks. No resend occurred; review Zoho Sent manually.'))


async def process_sent_recheck():
    """Claim one due delayed-Sent check for the single durable worker."""
    now = core.now()
    async with core.AsyncSessionLocal() as session:
        rows = list((await session.scalars(select(JobProcessing).where(
            JobProcessing.application_status == 'delivery_unconfirmed',
            JobProcessing.application['verification_next_at'].astext.is_not(None))
            .order_by(JobProcessing.updated_at).limit(25).with_for_update(skip_locked=True))).all())
        row = next((item for item in rows if sent_recheck_due(item.application, now=now)), None)
        if row is None:
            return False
        application = dict(row.application)
        count = int(application.get('verification_rechecks') or 0) + 1
        application.update({'verification_rechecks': count,
            'verification_checked_at': now.isoformat(),
            # A future reservation makes a worker crash recoverable without any send retry.
            'verification_next_at': next_sent_recheck_at(count, now=now),
            'phase': 'verifying_sent',
            'stage': f'Checking Zoho Sent automatically ({count}/{len(SENT_RECHECK_DELAYS_SECONDS)})'})
        row.application = application
        row.updated_at = now
        identity = row.candidate_id
        await session.commit()
    await automatic_sent_recheck(identity, application)
    return True


async def process_application():
    async with core.AsyncSessionLocal() as session:
        row = await session.scalar(select(JobProcessing).where(JobProcessing.application_status.in_(['queued', 'queued_send']))
            .order_by(JobProcessing.updated_at).limit(1).with_for_update(skip_locked=True))
        if not row:
            return False
        identity, previous, application = row.candidate_id, row.application_status, dict(row.application)
        # Keep an authorized send visibly queued during its read-only preflight.
        # Only preparation work uses the broader `preparing` state.
        row.application_status = 'preparing' if previous == 'queued' else 'queued_send'
        row.updated_at = core.now()
        await session.commit()
    try:
        if previous == 'queued':
            await prepare_application(identity, application)
        else:
            await send_application(identity, application)
    except Exception as exc:
        logger.warning('Job application preparation failed: %s: %s', type(exc).__name__, exc)
        # No provider action occurs before send_application marks sending.
        current = (await detail(identity))['application']['status']
        if current not in {'sending', 'delivery_unconfirmed', 'sent_verified'}:
            failed_phase = (await detail(identity))['application'].get('phase') or 'preparation'
            if isinstance(exc, ValueError):
                message = str(exc)
            elif isinstance(exc, LLMGatewayError) and ('429' in str(exc) or 'rate_limit' in str(exc)):
                message = 'The drafting service is temporarily rate-limited. Retry preparation shortly.'
            else:
                message = 'Processing could not complete. Retry preparation after checking the source and connection.'
            await set_application(identity, status='needs_review', phase='needs_review',
                failed_phase=failed_phase, retryable=True, stage='Preparation stopped', error=message[:1000])
    return True


async def processing_loop():
    await core.ensure_tables()
    # One durable executor across daemon processes; lock releases on process death.
    async with core.async_engine.connect() as connection:
        if not await connection.scalar(text('SELECT pg_try_advisory_lock(734985219)')):
            return
        await connection.commit()
        try:
            async with core.AsyncSessionLocal() as session:
                await session.execute(text("UPDATE job_agent_processing SET classification_status='pending' WHERE classification_status='classifying'"))
                await session.execute(text("UPDATE job_agent_processing SET application_status='queued' WHERE application_status='preparing'"))
                await session.execute(text("UPDATE job_agent_processing SET application_status='delivery_unconfirmed', application=application || '{\"error\":\"Processing restarted after a send attempt. Verify Zoho Sent; no automatic resend.\"}'::jsonb WHERE application_status='sending'"))
                await session.commit()
            while True:
                _wakeup.clear()
                try:
                    await enqueue_missing()
                    if await process_application():
                        continue
                    if await process_sent_recheck():
                        continue
                    if await classify_batch(requested_only=True):
                        continue
                    if await classify_batch():
                        continue
                except Exception:
                    logger.exception('Job processing worker failed')
                try:
                    await asyncio.wait_for(_wakeup.wait(), timeout=10)
                except asyncio.TimeoutError:
                    pass
        finally:
            await connection.execute(text('SELECT pg_advisory_unlock(734985219)'))
            await connection.commit()
