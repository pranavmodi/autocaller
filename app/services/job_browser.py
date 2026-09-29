"""Durable, operator-authorized browser applications, separate from Zoho sends."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import DateTime, Integer, String, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.services import job_agent as core
from app.services import job_applicant_profile as profile
from app.services.job_agent_resumes import inspect_resume, resolve_resume
from app.services.job_browser_tools import BrowserAction, BrowserSession
from app.services.job_browser_client import PersistentBrowserSession
from app.services.job_browser_mail import MailboxSearchRequest, search_zoho_inbox
from app.services.llm_gateway import call_skill_json

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2] / 'var/job-browser'
SKILL = Path(__file__).resolve().parents[1] / 'skills/job-browser-agent/SKILL.md'
CONTEXT_SKILL = Path(__file__).resolve().parents[1] / 'skills/possibleos-job-applicant-context/SKILL.md'
ACTIVE = {'queued', 'running', 'verifying'}
LOCKED = {'submitted', 'submission_uncertain'}
_wake = asyncio.Event()
_sessions: dict[str, BrowserSession] = {}


class BrowserRun(core.Base):
    __tablename__ = 'job_agent_browser_runs'
    candidate_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), unique=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=core.now)


class BrowserEvent(core.Base):
    __tablename__ = 'job_agent_browser_events'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=core.now)
    detail: Mapped[dict] = mapped_column(JSONB)


class StartRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=1)
    authorize_submit: Literal[True]
    provider: Literal['gateway', 'openai'] | None = None
    model: str | None = Field(None, min_length=1, max_length=120, pattern=r'^\S+$')


class ControlRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=1)
    action: Literal['pause', 'resume', 'answer', 'verify', 'confirm_receipt', 'release',
                    'restart', 'reconnect', 'quit', 'challenge', 'resume_unsubmitted']
    reason: str = Field('', max_length=1000)
    question_id: str | None = None
    answer: str = Field('', max_length=8000)
    provider: Literal['gateway', 'openai'] | None = None
    model: str | None = Field(None, min_length=1, max_length=120, pattern=r'^\S+$')
    remember: bool = True


class HandoffStartRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=1)


class HumanBrowserActionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    observation_id: str = Field(min_length=32, max_length=64)
    action_id: str = Field(min_length=32, max_length=32)
    kind: Literal['click', 'type', 'replace', 'press', 'scroll']
    x: float | None = None
    y: float | None = None
    value: str = Field('', max_length=8000)
    key: str = Field('', max_length=40)
    delta_y: float = Field(0, ge=-1800, le=1800)


class HandoffFinishRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=1)
    outcome: Literal['resume_agent', 'may_have_submitted', 'keep_paused']


def provider_settings(config, provider=None, model=None):
    selected = provider or config.browser_ai_provider
    if selected == 'openai' and not os.getenv('OPENAI_API_KEY', '').strip():
        raise ValueError('Direct OpenAI API requires OPENAI_API_KEY on the server. Choose the gateway or configure the key.')
    return {'ai_provider': selected, 'openai_model': model or config.browser_openai_model}


def undispatched_missing_control(state):
    # Compatibility with the exact local pre-dispatch error from older workers.
    # This is an exception identity check, not a semantic interpretation of a page.
    action = state.get('last_action') or {}
    return (state.get('error') == 'The selected control is no longer in the current page snapshot.'
            and action.get('kind') in {'fill', 'check', 'select', 'press', 'upload', 'click'}
            and bool(action.get('element'))
            and 'snapshot' in state
            and not any(c.get('id') == action['element']
            for f in state['snapshot'].get('frames', []) for c in f.get('controls', [])))


def recoverable_input_interruption(state):
    """Return true when the write-ahead marker can only describe form input.

    The action audit is the authority here: an interrupted submit, navigation,
    or advance remains locked. A separately managed browser can instead be
    re-inspected after an audited input action without replaying that action.
    """
    action = state.get('last_action') or {}
    audit = state.get('audit') or {}
    return (bool(state.get('interaction_started'))
            and not state.get('submit_started_at')
            and not state.get('confirmation')
            and state.get('browser_transport') == 'broker'
            and bool(state.get('session_available'))
            and action.get('kind') in {'fill', 'check', 'select', 'press', 'upload', 'click'}
            and audit.get('allowed') is True
            and audit.get('effect') == 'input')


def recoverable_source_navigation(state):
    """Identify a failed pre-form navigation that cannot have submitted a form.

    The independent action audit supplies the semantic effect. The durable
    form-input marker keeps source recovery limited to the path into the form,
    before the agent has begun completing it.
    """
    action = state.get('last_action') or {}
    audit = state.get('audit') or {}
    return (bool(state.get('interaction_started'))
            and not state.get('submit_started_at')
            and not state.get('confirmation')
            and not state.get('form_input_completed_at')
            and not state.get('application_source_url')
            and action.get('kind') in {'click', 'goto'}
            and audit.get('allowed') is True
            and audit.get('effect') == 'navigation')


def recoverable_navigation_interruption(state):
    """Allow a preserved browser to be re-inspected after audited navigation.

    This covers navigation inside an already verified employer or ATS portal.
    The action must have been independently audited as navigation, before any
    form input or submit attempt, and the original broker session must still be
    available. Earlier input may be a careers-page search or location filter,
    so it is not treated as evidence of an application-form submission.
    Resuming observes the resulting page; it never replays the click.
    """
    action = state.get('last_action') or {}
    audit = state.get('audit') or {}
    return (bool(state.get('interaction_started'))
            and not state.get('submit_started_at')
            and not state.get('confirmation')
            and state.get('browser_transport') == 'broker'
            and bool(state.get('session_available'))
            and bool(state.get('application_source_url'))
            and action.get('kind') in {'click', 'goto'}
            and audit.get('allowed') is True
            and audit.get('effect') == 'navigation')


def recoverable_validation_rejection(state):
    """Allow correction only when the employer explicitly rejected the form.

    A submit click normally stays locked because its outcome may be unknown. An
    exact employer validation message on the preserved application page proves
    that the form was not accepted and can safely be corrected in place.
    """
    snapshot = state.get('snapshot') or {}
    visible = '\n'.join(frame.get('text', '') for frame in snapshot.get('frames', []))
    current_url = state.get('current_url') or ''
    return (bool(state.get('submit_started_at'))
            and not state.get('confirmation')
            and state.get('browser_transport') == 'broker'
            and bool(state.get('session_available'))
            and bool(current_url)
            and snapshot.get('url') == current_url
            and 'You need to add or modify some info before submitting your job application.' in visible
            and 'This info is required.' in visible)


def unopened_recovered_source_browser(row, state):
    """True only when a source-recovery run has never launched its new browser."""
    return (bool(state.get('application_source_url'))
            and state.get('browser_transport') == 'broker'
            and not (ROOT / row.run_id / 'browser-session.json').exists()
            and not state.get('submit_started_at')
            and not state.get('interaction_started'))


def human_verification_controls(snapshot):
    """Return the exact eight code inputs and submit control for a human challenge."""
    controls = [control for frame in snapshot.get('frames', [])
                for control in frame.get('controls', [])]
    first = next((index for index, control in enumerate(controls)
                  if (control.get('label') or '').strip().casefold() == 'security code'
                  and control.get('tag') == 'input'
                  and control.get('type') not in {'password', 'hidden'}), None)
    code = controls[first:first + 8] if first is not None else []
    valid_code_group = (len(code) == 8 and all(
        control.get('tag') == 'input'
        and control.get('type') not in {'password', 'hidden'}
        and not control.get('disabled')
        and (index == 0 or not (control.get('label') or '').strip())
        for index, control in enumerate(code)))
    submit = next((control for control in controls
                   if (control.get('label') or '').strip().casefold() == 'submit application'
                   and control.get('tag') in {'button', 'input'}), None)
    visible = '\n'.join(frame.get('text', '') for frame in snapshot.get('frames', []))
    established = ('A verification code was sent to ' in visible
                   and "enter the 8-character code to confirm you're a human." in visible)
    return (code, submit) if established and valid_code_group else ([], None)


def rejected_human_verification(state):
    """A visible rejected code proves this challenge did not submit the application."""
    snapshot = state.get('snapshot') or {}
    visible = '\n'.join(frame.get('text', '') for frame in snapshot.get('frames', []))
    code_controls, submit = human_verification_controls(snapshot)
    rejected = any(message in visible for message in (
        'Invalid security code',
        'Incorrect security code',
    ))
    # Greenhouse sometimes keeps the submit control enabled after rejecting a
    # code. The explicit rejection text is the proof that no application was
    # accepted, so button state must not prevent a safe clean retry.
    return bool(code_controls) and bool(submit) and rejected


def restart_blocker(row):
    state = row.state
    if row.status == 'human_control':
        return 'Return or pause human control before restarting.'
    if row.status in ACTIVE:
        return 'Pause the application before restarting.'
    if row.status == 'submitted' or state.get('confirmation'):
        return 'A submission was attempted or confirmed. Verify it before starting another application.'
    if rejected_human_verification(state):
        return None
    if recoverable_validation_rejection(state):
        return None
    if state.get('submit_started_at'):
        return 'A submission was attempted or confirmed. Verify it before starting another application.'
    if recoverable_input_interruption(state):
        return None
    if recoverable_source_navigation(state):
        return None
    if state.get('interaction_started') and not undispatched_missing_control(state):
        return 'An earlier browser interaction may have submitted the form. Verify its outcome first.'
    if row.status == 'submission_uncertain' and not undispatched_missing_control(state):
        return 'The previous submission outcome must be verified before restarting.'
    return None


def view(row):
    if not row:
        return {'status': 'not_started', 'revision': 0}
    full_state = row.state
    # Keep resume text / internal page context out of polling responses.
    state = {k: v for k, v in full_state.items() if k not in {
        'resume', 'posting', 'preferences', 'snapshot', 'page_evidence',
        'action_history', 'saved_profile', 'profile_history', 'attempt_history',
        'human_control_token_sha256'}}
    can_resume = ((row.status in {'paused', 'blocked'}
                   and not state.get('submit_started_at') and not state.get('interaction_started'))
                  or (row.status == 'submission_uncertain'
                      and (recoverable_input_interruption(full_state)
                           or recoverable_source_navigation(full_state)
                           or recoverable_navigation_interruption(full_state)
                           or recoverable_validation_rejection(full_state))))
    return {**state, 'status': row.status, 'revision': row.revision,
            'run_id': row.run_id, 'updated_at': row.updated_at.isoformat(),
            'can_restart': restart_blocker(row) is None, 'restart_blocked_reason': restart_blocker(row),
            'can_resume': can_resume,
            'recoverable_input_interruption': recoverable_input_interruption(full_state),
            'recoverable_source_navigation': recoverable_source_navigation(full_state),
            'recoverable_navigation_interruption': recoverable_navigation_interruption(full_state),
            'recoverable_validation_rejection': recoverable_validation_rejection(full_state),
            'can_quit': row.status != 'cancelled' and restart_blocker(row) is None}


async def get(identity, *, after: int | None = None):
    await core.ensure_tables()
    async with core.AsyncSessionLocal() as session:
        if not await session.get(core.JobAgentCandidate, identity):
            raise KeyError(identity)
        row = await session.get(BrowserRun, identity)
        statement = select(BrowserEvent).where(BrowserEvent.candidate_id == identity)
        if after is not None:
            statement = statement.where(BrowserEvent.id > after).order_by(BrowserEvent.id)
        else:
            statement = statement.order_by(BrowserEvent.id.desc())
        events = list((await session.scalars(statement.limit(100))).all())
        if after is None:
            events.reverse()
        result = {**view(row), 'events': [dict(e.detail, id=e.id, at=e.created_at.isoformat()) for e in events],
                'next_cursor': events[-1].id if events else (after or 0)}
    if row and row.state.get('browser_transport') == 'broker' and not row.state.get('browser_closed'):
        try:
            status = await PersistentBrowserSession(row.run_id).status()
            result.update(session_available=status['available'],
                          browser_session_status='available' if status['available'] else 'lost',
                          browser_busy=status['busy'])
        except ValueError:
            result.update(session_available=False, browser_session_status='unreachable')
    return result


HANDOFF_TTL_MINUTES = 30


def _handoff_hash(token: str):
    return hashlib.sha256(token.encode()).hexdigest()


def _handoff_authorized(row, token: str):
    state = row.state
    expected = state.get('human_control_token_sha256', '')
    expires = state.get('human_control_expires_at')
    if row.status != 'human_control' or not expected or not expires:
        return False
    try:
        still_valid = datetime.fromisoformat(expires) > datetime.now(timezone.utc)
    except (TypeError, ValueError):
        return False
    return still_valid and hmac.compare_digest(expected, _handoff_hash(token))


async def start_handoff(identity: str, request: HandoffStartRequest):
    """Lease the preserved page to one human controller.

    The raw lease token is returned once and never stored. Rotating a lease
    invalidates a token lost during a page refresh without changing the page.
    """
    await core.ensure_tables()
    async with core.AsyncSessionLocal() as session:
        current = await session.get(BrowserRun, identity)
        if not current:
            raise KeyError(identity)
        if current.revision != request.revision:
            raise ValueError('The browser progressed. Refresh before taking control.')
        if current.status in ACTIVE:
            raise ValueError('Pause after the current browser action before taking control.')
        if current.status in {'submitted', 'cancelled'}:
            raise ValueError('This application no longer has an active form to control.')
        if current.state.get('browser_transport') != 'broker' or current.state.get('browser_closed'):
            raise ValueError('Human control requires the preserved application browser.')
        await attach_browser(current)
    token = secrets.token_urlsafe(32)
    async with core.AsyncSessionLocal() as session:
        row = await session.get(BrowserRun, identity, with_for_update=True)
        if not row or row.revision != request.revision:
            raise ValueError('The browser progressed. Refresh before taking control.')
        state = dict(row.state)
        expires = core.now() + timedelta(minutes=HANDOFF_TTL_MINUTES)
        state.update(
            human_control_token_sha256=_handoff_hash(token),
            human_control_expires_at=expires.isoformat(),
            human_control_started_at=core.now().isoformat(),
            human_control_previous_status=row.status,
            stage='You have control of the preserved application browser',
            error=None,
        )
        row.status = 'human_control'
        row.state = state
        row.revision += 1
        row.updated_at = core.now()
        add_event(session, row, 'Human control started on the preserved browser page.', 'human_control_started')
        await session.commit()
        result = view(row)
    return {**result, 'handoff_token': token}


async def _authorized_handoff(identity: str, token: str):
    await core.ensure_tables()
    async with core.AsyncSessionLocal() as session:
        row = await session.get(BrowserRun, identity)
        if not row:
            raise KeyError(identity)
        if not _handoff_authorized(row, token):
            raise ValueError('Human-control access expired or was replaced. Take control again to continue.')
        return row


async def handoff_frame(identity: str, token: str):
    row = await _authorized_handoff(identity, token)
    browser = await attach_browser(row)
    path = ROOT / row.run_id / 'page.png'
    snapshot = await browser.observe(path)
    return {'path': path, 'observation_id': browser.observation_id,
            'current_url': snapshot.get('url', '')}


async def handoff_action(identity: str, token: str, request: HumanBrowserActionRequest):
    row = await _authorized_handoff(identity, token)
    browser = await attach_browser(row)
    # Deliberately do not persist request.value, coordinates, or key presses.
    await browser.human_action(
        observation_id=request.observation_id, action_id=request.action_id,
        kind=request.kind, x=request.x, y=request.y, value=request.value,
        key=request.key, delta_y=request.delta_y)
    return {'completed': True}


async def finish_handoff(identity: str, token: str, request: HandoffFinishRequest):
    await core.ensure_tables()
    async with core.AsyncSessionLocal() as session:
        row = await session.get(BrowserRun, identity, with_for_update=True)
        if not row:
            raise KeyError(identity)
        if row.revision != request.revision:
            raise ValueError('The application state changed. Refresh before returning control.')
        if not _handoff_authorized(row, token):
            raise ValueError('Human-control access expired or was replaced. Take control again to continue.')
        state = dict(row.state)
        state.pop('human_control_token_sha256', None)
        state.pop('human_control_expires_at', None)
        state['human_control_finished_at'] = core.now().isoformat()
        state['question'] = None
        state['error'] = None
        state['action_signature'] = None
        state['repeat_count'] = 0
        state['segment_steps'] = 0
        if request.outcome == 'resume_agent':
            if state.get('submit_started_at'):
                browser = await attach_browser(row)
                if not browser:
                    raise ValueError('The preserved application browser is unavailable.')
                snapshot = await browser.observe(ROOT / row.run_id / 'page.png')
                current_url = snapshot.get('url') or ''
                submit_controls = [control for frame in snapshot.get('frames', [])
                                   for control in frame.get('controls', [])
                                   if control.get('type') == 'submit' and not control.get('disabled')]
                if (not current_url or current_url != state.get('current_url')
                        or not submit_controls):
                    raise ValueError(
                        'The preserved page does not prove that the application remains unsubmitted. '
                        'Choose verification-only mode instead.')
                recovered_at = core.now().isoformat()
                state['mistaken_submission_recovery'] = {
                    'at': recovered_at,
                    'human_may_have_submitted_at': state.get('human_may_have_submitted_at'),
                    'evidence_url': current_url,
                    'visible_submit_control': True,
                    'source': 'human_control_return',
                }
                for key in ('submit_started_at', 'human_may_have_submitted_at',
                            'human_verification_submit_started_at'):
                    state.pop(key, None)
                state.update(snapshot=snapshot, current_url=current_url, screenshot=True,
                             browser_action_id=None,
                             force_verified_submit_retry={'recovery_at': recovered_at})
            state.update(
                stage='Agent resuming from the page you completed',
                interaction_started=False,
                verification_only=False,
            )
            row.status = 'queued'
            message = 'Human control returned to the agent. The page will be inspected before the next action.'
        elif request.outcome == 'may_have_submitted':
            state.update(
                stage='Checking whether your manual submission was accepted',
                submit_started_at=state.get('submit_started_at') or core.now().isoformat(),
                human_may_have_submitted_at=core.now().isoformat(),
                interaction_started=False,
                verification_only=True,
            )
            row.status = 'verifying'
            message = 'Human control ended after a possible submission. The agent will verify only and cannot submit again.'
        else:
            state.update(stage='Paused after human control', interaction_started=False)
            row.status = 'paused'
            message = 'Human control ended. The browser remains open and the application is paused.'
        state.pop('human_control_previous_status', None)
        row.state = state
        row.revision += 1
        row.updated_at = core.now()
        add_event(session, row, message, 'human_control_finished', outcome=request.outcome)
        await session.commit()
        result = view(row)
    if row.status in ACTIVE:
        _wake.set()
    return result


async def attach_browser(row):
    """Attach only: never create a session or navigate from a recovery path."""
    browser = _sessions.get(row.candidate_id)
    if row.state.get('browser_transport') == 'broker':
        if row.state.get('browser_closed'):
            raise ValueError('This browser was explicitly closed. Start a fresh attempt if permitted.')
        browser = browser or PersistentBrowserSession(row.run_id)
        await browser.attach()
        _sessions[row.candidate_id] = browser
    return browser


async def close_browser(row):
    browser = _sessions.get(row.candidate_id)
    if not browser and row.state.get('browser_transport') == 'broker':
        browser = PersistentBrowserSession(row.run_id)
    if browser:
        await browser.close()
        _sessions.pop(row.candidate_id, None)


async def switch_to_official_source(row, source):
    """Replace a blocked pre-form browser with the verified official job page."""
    old_run_id = row.run_id
    old_directory = ROOT / old_run_id
    new_run_id = uuid4().hex
    new_directory = ROOT / new_run_id
    new_directory.mkdir(parents=True, mode=0o700)
    resume = old_directory / 'resume.pdf'
    if row.state.get('resume'):
        if hashlib.sha256(resume.read_bytes()).hexdigest() != row.state['resume']['sha256']:
            raise ValueError('The saved resume changed during application-page recovery.')
        shutil.copyfile(resume, new_directory / 'resume.pdf')
        (new_directory / 'resume.pdf').chmod(0o600)
    await close_browser(row)
    async with core.AsyncSessionLocal() as session:
        current = await session.get(BrowserRun, row.candidate_id, with_for_update=True)
        if not current or current.revision != row.revision:
            raise ValueError('The application changed while its official page was being selected.')
        candidate = await session.get(core.JobAgentCandidate, row.candidate_id, with_for_update=True)
        state = dict(current.state)
        posting = dict(state['posting'])
        urls = list(dict.fromkeys([*(posting.get('source_urls') or []), source['url']]))
        posting.update(application_url=source['url'], source_urls=urls)
        history = [*state.get('source_recovery_history', []), {
            'at': core.now().isoformat(), 'previous_run_id': old_run_id,
            'previous_url': state.get('current_url') or posting.get('source_url'),
            'official_url': source['url'], 'source_type': source['source_type'],
            'match_scope': source['match_scope'], 'reason': source['reason'],
            'confidence': source['confidence'],
        }][-10:]
        for key in ('snapshot', 'current_url', 'interaction_started', 'browser_action_id',
                    'action_signature', 'repeat_count', 'error', 'failed_action',
                    'failed_audit', 'failed_model', 'failed_audit_model', 'session_error',
                    'browser_transport'):
            state.pop(key, None)
        state.update(
            posting=posting,
            application_source_url=source['url'],
            application_source={key: source[key] for key in (
                'url', 'source_type', 'match_scope', 'reason', 'confidence',
                'verified_at', 'evidence')},
            source_recovery={'status': 'completed', 'verified_at': source['verified_at']},
            source_recovery_history=history,
            browser_closed=False,
            browser_session_status='opening',
            session_available=False,
            screenshot=False,
            stage='Official application page verified; opening its form',
        )
        current.run_id = new_run_id
        current.status = 'queued'
        current.state = state
        current.revision += 1
        current.updated_at = core.now()
        if candidate:
            candidate.posting = {**candidate.posting, 'application_url': source['url'],
                                 'source_urls': urls}
            candidate.updated_at = core.now()
        message = ('Verified the exact role on an official employer or ATS page. Continuing the application there.'
                   if source['match_scope'] == 'direct_role' else
                   'Verified the employer-linked official jobs portal. Continuing there to locate the exact saved role.')
        add_event(session, current, message,
            'official_source', url=source['url'], source_type=source['source_type'],
            match_scope=source['match_scope'], confidence=source['confidence'])
        await session.commit()
        return current


async def recover_official_source(row):
    from app.services.job_application_source import resolve_official_application_source
    source = await resolve_official_application_source(
        row.state['posting'], provider=row.state.get('ai_provider', 'gateway'),
        model=row.state.get('openai_model', 'gpt-5-mini'))
    return await switch_to_official_source(row, source)


async def list_runs():
    await core.ensure_tables()
    async with core.AsyncSessionLocal() as session:
        rows = (await session.scalars(select(BrowserRun).order_by(BrowserRun.updated_at.desc()))).all()
    return {'items': [dict(view(r), candidate_id=r.candidate_id,
                          title=r.state['posting'].get('title'),
                          firm_name=r.state['posting'].get('firm_name')) for r in rows]}


async def operator_mailbox_search(identity: str, request: MailboxSearchRequest):
    """Run an explicit, non-persisted, read-only search for one saved job."""
    await core.ensure_tables()
    async with core.AsyncSessionLocal() as session:
        if not await session.get(core.JobAgentCandidate, identity):
            raise KeyError(identity)
    return await search_zoho_inbox(request)


async def infer_quit_reasons(state):
    from app.services.job_browser_ai import direct_decision, QuitReasons
    skill = SKILL.parent.parent / 'job-quit-reasons/SKILL.md'
    payload = {'job': state['posting'], 'question': state.get('question'), 'blocker': state.get('error')}
    if state.get('ai_provider') == 'openai':
        result, _ = await direct_decision('suggest_quit_reasons', payload,
            model=state.get('openai_model', 'gpt-5-mini'), instructions=skill.read_text())
    else:
        response = await call_skill_json(skill_path=skill, payload=payload,
            required_fields=['reasons'], model='openclaw/main', lane='possibleos-interactive',
            allow_tools=False, timeout_s=20, retries=0, max_tokens=500)
        result = response.parsed
    return QuitReasons.model_validate(result).reasons


async def quit_reasons(identity):
    await core.ensure_tables()
    async with core.AsyncSessionLocal() as session:
        row = await session.get(BrowserRun, identity)
        if not row:
            raise KeyError(identity)
        if not view(row)['can_quit']:
            raise ValueError('Quit suggestions are available for stopped, unsubmitted applications only.')
    try:
        reasons = await asyncio.wait_for(infer_quit_reasons(row.state), timeout=25)
    except TimeoutError as exc:
        raise ValueError('Reason suggestions took too long. You can still enter your own reason or quit without one.') from exc
    async with core.AsyncSessionLocal() as session:
        current = await session.get(BrowserRun, identity)
        if not current or current.revision != row.revision:
            raise ValueError('The application changed. Refresh before choosing a reason.')
    return {'reasons': [r.strip()[:160] for r in reasons if r.strip()], 'revision': row.revision}


def add_event(session, row, message, kind='progress', **details):
    session.add(BrowserEvent(candidate_id=row.candidate_id,
                            detail={'kind': kind, 'message': message, **details}))


async def request_companion_email(identity: str):
    """Authorize the existing email workflow once for a website application.

    The email processor owns recipient research, duplicate checks, Zoho send,
    and Sent verification. This bridge only grants the same send authorization
    already implied by the saved Job Agent preference and website-apply action.
    """
    from app.services import job_agent_processing as processing

    last_error = None
    for _ in range(2):
        current = await processing.detail(identity)
        try:
            return await processing.request_application(
                identity,
                processing.ApplicationRequest(
                    revision=current['processing_revision'], mode='send'))
        except ValueError as exc:
            last_error = exc
            if 'changed' not in str(exc).casefold():
                raise
    raise last_error or ValueError('The email application could not be queued.')


async def start(identity, request: StartRequest):
    from app.services import job_agent_processing as processing
    await processing.enqueue_missing()
    async with core.AsyncSessionLocal() as session:
        # Candidate lock serializes double-clicks even before the run row exists.
        candidate = await session.get(core.JobAgentCandidate, identity, with_for_update=True)
        if not candidate:
            raise KeyError(identity)
        old = await session.get(BrowserRun, identity)
        if old:
            return view(old)  # Resume existing workflow; never create another submission.
        proc = await session.get(processing.JobProcessing, identity, with_for_update=True)
        if not proc or proc.revision != request.revision:
            raise ValueError('This job changed. Refresh before starting the browser application.')
        settings = await session.get(core.JobAgentState, 'default')
        config = core.saved_config(settings.config) if settings else core.JobAgentConfig()
        ai_settings = provider_settings(config, request.provider, request.model)
        classification = processing.classification_view(proc, config)
        if candidate.posting.get('status') == 'closed':
            raise ValueError('This job is marked closed.')
        # Persist authorization first; the worker handles Jev and PDF selection.
        resume = None
        run_id = uuid4().hex
        directory = ROOT / run_id
        directory.mkdir(parents=True, mode=0o700)
        row = BrowserRun(candidate_id=identity, run_id=run_id, status='queued', revision=1,
            state={'posting': candidate.posting, 'resume': resume, **ai_settings,
                   'preferences': config.model_dump(exclude={'resume_categories'}),
                   'authorized_at': core.now().isoformat(), 'stage': 'Selecting the best resume for this job',
                   'answers': [], 'steps': 0, 'error': None, 'question': None,
                   'resume_filename': None, 'session_available': False})
        session.add(row)
        add_event(session, row, 'Website application authorized. Resume selection will run automatically.', 'authorized')
        await session.commit()
        result = view(row)
    if config.auto_email_with_website_application:
        try:
            email_result = await request_companion_email(identity)
            email = email_result.get('application') or {}
            saved = await checkpoint(
                identity, result['revision'],
                companion_email={
                    'requested': True,
                    'status': email.get('status', 'queued'),
                    'run_id': email.get('run_id'),
                    'requested_at': core.now().isoformat(),
                },
                message=('Email application authorized too. Recipient research, duplicate checks, '
                         'Zoho sending and Sent verification run independently.'),
                kind='companion_email_requested')
            if saved:
                result = view(saved)
        except Exception as exc:
            logger.warning('Companion email application could not be queued: %s', type(exc).__name__)
            saved = await checkpoint(
                identity, result['revision'],
                companion_email={
                    'requested': True,
                    'status': 'queue_failed',
                    'error': str(exc)[:500] or type(exc).__name__,
                    'requested_at': core.now().isoformat(),
                },
                message=('Website application started, but its companion email could not be queued. '
                         'No email was sent.'),
                kind='companion_email_queue_failed')
            if saved:
                result = view(saved)
    _wake.set()
    return result


async def complete_human_verification(identity, request: ControlRequest):
    """Use a human-supplied code once without persisting it anywhere."""
    code_value = request.answer.strip()
    if len(code_value) != 8 or any(character.isspace() for character in code_value):
        raise ValueError('Enter the complete 8-character security code.')
    await core.ensure_tables()
    async with core.AsyncSessionLocal() as session:
        row = await session.get(BrowserRun, identity)
        if not row:
            raise KeyError(identity)
        if row.revision != request.revision:
            raise ValueError('The browser progressed. Refresh its status before this action.')
        state = row.state
        if (row.status != 'submission_uncertain' or not state.get('submit_started_at')
                or state.get('confirmation')):
            raise ValueError('A pending human-verification challenge was not established for this application.')
        browser = await attach_browser(row)
        if not browser:
            raise ValueError('The preserved application browser is unavailable.')
        run_id = row.run_id
        expected = row.revision
        resume = ROOT / run_id / 'resume.pdf'
        if hashlib.sha256(resume.read_bytes()).hexdigest() != state['resume']['sha256']:
            raise ValueError('The selected resume changed. Application stopped.')
    screenshot_path = ROOT / run_id / 'page.png'
    snapshot = await browser.observe(screenshot_path)
    for index, character in enumerate(code_value):
        code_controls, submit_control = human_verification_controls(snapshot)
        if not code_controls or not submit_control:
            raise ValueError('The preserved page no longer shows the expected human-verification challenge.')
        await browser.execute(BrowserAction(kind='fill', element=code_controls[index]['id'], value=character,
                                            summary='Enter one character of the human-supplied security code'), resume)
        if index < len(code_value) - 1:
            snapshot = await browser.observe(screenshot_path)
    # Re-observe because broker element handles are scoped to one observation.
    snapshot = await browser.observe(screenshot_path)
    code_controls, submit_control = human_verification_controls(snapshot)
    if (not submit_control or submit_control.get('disabled')
            or ''.join(control.get('value', '') for control in code_controls) != code_value):
        raise ValueError('The verification form did not register the complete code. Inspect the preserved page.')
    row = await checkpoint(identity, expected, status='verifying',
        stage='Submitting after human verification', interaction_started=True,
        human_verification_submit_started_at=core.now().isoformat(),
        message='The human-supplied verification code was entered. Performing the required final submission click once.',
        kind='human_verification')
    if not row:
        raise ValueError('The browser progressed. Refresh its status before this action.')
    action = BrowserAction(kind='submit', element=submit_control['id'],
                           summary='Submit after human verification')
    try:
        await browser.execute(action, resume)
    except Exception as exc:
        await checkpoint(identity, row.revision, status='submission_uncertain',
            stage='Human-verification submission needs review',
            error=str(exc)[:1200] or type(exc).__name__,
            message='The final submission click was attempted; inspect the preserved page without resubmitting.',
            kind='error')
        raise
    snapshot = await browser.observe(ROOT / run_id / 'page.png')
    visible = '\n'.join(frame.get('text', '') for frame in snapshot.get('frames', []))
    rejected = any(message in visible for message in (
        'Invalid security code',
        'Incorrect security code',
    ))
    code_ids = {control['id'] for control in code_controls}
    durable_snapshot = {**snapshot, 'frames': [
        {**frame, 'controls': [
            {**control, 'value': ''} if control.get('id') in code_ids else control
            for control in frame.get('controls', [])
        ]}
        for frame in snapshot.get('frames', [])
    ]}
    screenshot_path.unlink(missing_ok=True)
    saved = await checkpoint(identity, row.revision,
        status='submission_uncertain' if rejected else 'verifying',
        stage='Verification code rejected' if rejected else
              'Checking the employer confirmation after human verification',
        interaction_started=False,
        human_verification_click_completed_at=core.now().isoformat(),
        snapshot=durable_snapshot, current_url=snapshot.get('url'), screenshot=False,
        error='Greenhouse rejected the security code. Enter the latest code from the newest email.' if rejected else None,
        message='Greenhouse rejected the security code; the application remains unsubmitted.' if rejected else
                'The verification click completed; checking the employer confirmation without resubmitting.',
        kind='human_verification_rejected' if rejected else 'human_verification_completed')
    _wake.set()
    return view(saved)


async def control(identity, request: ControlRequest):
    if request.action == 'challenge':
        return await complete_human_verification(identity, request)
    await core.ensure_tables()
    async with core.AsyncSessionLocal() as session:
        row = await session.get(BrowserRun, identity, with_for_update=True)
        if not row:
            raise KeyError(identity)
        if row.revision != request.revision:
            raise ValueError('The browser progressed. Refresh its status before this action.')
        state = dict(row.state)
        if row.status == 'human_control':
            raise ValueError('Return or pause human control before using another application command.')
        if row.status == 'cancelled' and request.action not in {'restart', 'release'}:
            raise ValueError('You quit this application. Use Restart from beginning if you decide to apply again.')
        if request.provider is not None and request.action not in {
                'resume', 'answer', 'verify', 'restart', 'resume_unsubmitted'}:
            raise ValueError('Choose a provider when starting, resuming, answering, or checking confirmation.')
        if request.action == 'confirm_receipt':
            if row.status != 'submission_uncertain' or not state.get('submit_started_at'):
                raise ValueError('A receipt can be confirmed only after a recorded submission attempt.')
            quote = request.answer.strip()
            snapshot = state.get('snapshot') or {}
            visible = '\n'.join(frame.get('text', '') for frame in snapshot.get('frames', []))
            if len(quote) < 8 or quote not in visible:
                raise ValueError('The supplied receipt quote is not visible in the preserved employer page.')
            state.update(
                confirmation={'quote': quote, 'url': snapshot.get('url') or state.get('current_url'),
                              'at': core.now().isoformat(),
                              'verification': {'confirmed': True,
                                               'reason': 'Exact visible employer receipt confirmed locally.'},
                              'model': None},
                stage='Website submission confirmed', error=None, question=None,
                interaction_started=False, browser_closed=True, session_available=False,
                browser_session_status='closed')
            row.status = 'submitted'
            add_event(session, row, 'The preserved employer page confirmed this application.', 'submitted')
            try:
                await close_browser(row)
            except Exception as exc:
                state['browser_cleanup_error'] = 'Submission is confirmed, but browser closure could not be verified.'
                logger.warning('Confirmed receipt browser cleanup failed: %s', type(exc).__name__)
        elif request.action == 'resume_unsubmitted':
            if (row.status != 'submission_uncertain'
                    or not state.get('human_may_have_submitted_at')
                    or state.get('confirmation')):
                raise ValueError('This recovery is only available after human control was mistakenly returned as possibly submitted.')
            browser = await attach_browser(row)
            if not browser:
                raise ValueError('The preserved application browser is unavailable.')
            snapshot = await browser.observe(ROOT / row.run_id / 'page.png')
            current_url = snapshot.get('url') or ''
            submit_controls = [control for frame in snapshot.get('frames', [])
                               for control in frame.get('controls', [])
                               if control.get('type') == 'submit' and not control.get('disabled')]
            if (not current_url or current_url != state.get('current_url')
                    or not submit_controls):
                raise ValueError('The preserved page no longer proves that the unsubmitted application form is open.')
            recovered_at = core.now().isoformat()
            state['mistaken_submission_recovery'] = {
                'at': recovered_at,
                'human_may_have_submitted_at': state.get('human_may_have_submitted_at'),
                'evidence_url': current_url,
                'visible_submit_control': True,
            }
            for key in ('submit_started_at', 'human_may_have_submitted_at',
                        'human_verification_submit_started_at'):
                state.pop(key, None)
            state.update(
                snapshot=snapshot, current_url=current_url, screenshot=True,
                verification_only=False, interaction_started=False,
                stage='Resuming the preserved form after you confirmed it was not submitted',
                error=None, question=None, action_signature=None, repeat_count=0,
                segment_steps=0, browser_action_id=None,
                force_verified_submit_retry={'recovery_at': recovered_at},
            )
            row.status = 'queued'
            add_event(session, row,
                'You confirmed that human control did not submit the form. The submission lock was cleared and the preserved form will continue.',
                'mistaken_submission_recovered', evidence_url=current_url)
        elif request.action == 'quit':
            reason = restart_blocker(row)
            if reason:
                raise ValueError(reason)
            # Waiting/paused runs cannot dispatch actions. Close best-effort:
            # a failed browser connection must not prevent the operator quitting.
            try:
                await asyncio.wait_for(close_browser(row), timeout=3)
                state.update(browser_closed=True, session_available=False,
                             browser_session_status='closed', browser_cleanup_error=None)
            except Exception as exc:
                state['browser_cleanup_error'] = 'Application stopped, but browser closure could not be confirmed. Use Close browser to retry.'
                logger.warning('Quit browser cleanup failed: %s', type(exc).__name__)
            row.status = 'cancelled'
            state.update(quit_at=core.now().isoformat(), quit_reason=request.reason.strip(),
                         quit_question=state.get('question'), question=None, error=None,
                         stage='Application quit by you')
        elif request.action == 'restart':
            reason = restart_blocker(row)
            if reason:
                raise ValueError(reason)
            candidate = await session.get(core.JobAgentCandidate, identity)
            if not candidate or candidate.posting.get('status') == 'closed':
                raise ValueError('This job is unavailable or marked closed.')
            from app.services.job_agent_processing import job_key
            if job_key(candidate.posting) != job_key(state['posting']):
                raise ValueError('The saved employer or role changed. Review the job before restarting.')
            history = list(state.get('attempt_history', []))
            history.append({'run_id': row.run_id, 'status': row.status,
                'archived_at': core.now().isoformat(),
                'state': {k:v for k,v in state.items() if k != 'attempt_history'}})
            new_id = uuid4().hex
            directory = ROOT / new_id
            directory.mkdir(parents=True, mode=0o700)
            if state.get('resume'):
                old_pdf = ROOT / row.run_id / 'resume.pdf'
                if hashlib.sha256(old_pdf.read_bytes()).hexdigest() != state['resume']['sha256']:
                    raise ValueError('The saved resume changed; review it before restarting.')
                shutil.copyfile(old_pdf, directory / 'resume.pdf')
                (directory / 'resume.pdf').chmod(0o600)
            await close_browser(row)
            state = {k:state[k] for k in ('posting', 'resume', 'resume_filename', 'category_id',
                'preferences', 'answers', 'authorized_at', 'ai_provider', 'openai_model') if k in state}
            state.update(attempt_history=history, attempt=len(history)+1, steps=0, segment_steps=0,
                stage='Starting again with a fresh browser and saved answers', error=None,
                question=None, session_available=False)
            row.run_id, row.status = new_id, 'queued'
        elif request.action == 'pause':
            if row.status not in ACTIVE:
                raise ValueError('Only an active browser run can be paused.')
            # In-flight browser actions can complete; CAS prevents another action.
            row.status = 'submission_uncertain' if state.get('submit_started_at') or state.get('interaction_started') else 'paused'
            state['stage'] = 'Pause requested; any action already in flight may finish'
        elif request.action == 'release':
            if row.status in ACTIVE:
                raise ValueError('Pause the application before closing its browser.')
            await close_browser(row)
            row.status = row.status if row.status in LOCKED or row.status == 'cancelled' else ('waiting_for_answer' if state.get('question') else 'paused')
            state['session_available'] = False
            state['browser_closed'] = True
            state['browser_session_status'] = 'closed'
            state['browser_cleanup_error'] = None
            state['stage'] = 'Application quit by you' if row.status == 'cancelled' else 'Browser closed; saved application progress retained'
        elif request.action == 'reconnect':
            if row.status in ACTIVE or row.status == 'submitted':
                raise ValueError('Reconnect is available for stopped applications only.')
            if state.get('browser_transport') != 'broker':
                raise ValueError('This older run has no separately managed browser to reconnect.')
            await attach_browser(row)
            state.update(session_available=True, browser_session_status='available',
                         stage='Reconnected to the existing page; no browser action performed')
        elif request.action == 'verify':
            browser = await attach_browser(row)
            if row.status != 'submission_uncertain' or not browser:
                raise ValueError('Read-only verification needs the original browser session. Review the saved evidence or the employer portal manually.')
            row.status, state['stage'] = 'verifying', 'Checking the existing page without resubmitting'
            state['verification_only'] = True
            # A retry must be decided from the freshly observed page and mail,
            # not from the error/audit that caused the previous attempt to stop.
            # The durable action/event history remains available for traceability.
            state['error'] = None
            state['failed_action'] = None
            state['failed_audit'] = None
            state['failed_model'] = None
            state['failed_audit_model'] = None
            state['audit_feedback'] = None
            state['audit_repair_count'] = 0
        else:
            recovering_input = (request.action == 'resume'
                                and row.status == 'submission_uncertain'
                                and recoverable_input_interruption(state))
            recovering_source = (request.action == 'resume'
                                 and row.status == 'submission_uncertain'
                                 and recoverable_source_navigation(state))
            recovering_navigation = (request.action == 'resume'
                                     and row.status == 'submission_uncertain'
                                     and recoverable_navigation_interruption(state))
            recovering_validation = (request.action == 'resume'
                                     and row.status == 'submission_uncertain'
                                     and recoverable_validation_rejection(state))
            recovering = (recovering_input or recovering_source
                          or recovering_navigation or recovering_validation)
            if (row.status in ACTIVE or (row.status in LOCKED and not recovering)
                    or (state.get('submit_started_at') and not recovering_validation)
                    or (state.get('interaction_started') and not recovering)):
                raise ValueError('This application cannot be restarted. Check submission evidence first.')
            if request.action == 'answer':
                question = state.get('question')
                if row.status != 'waiting_for_answer' or not question or question['id'] != request.question_id:
                    raise ValueError('This question is no longer pending.')
                if not request.answer.strip():
                    raise ValueError('Enter an answer before continuing.')
                saved_answer = {
                    'question': question['text'], 'answer': request.answer.strip(),
                    'at': core.now().isoformat(), 'remember': request.remember}
                await profile.remember(session, identity, state['posting'], saved_answer, reusable=request.remember)
                state['answers'] = [*state.get('answers', []), saved_answer]
                state['question'] = None
                add_event(session, row, 'Your answer was saved to the applicant profile for reuse.' if request.remember else 'Your answer was saved for this application only.', 'answer')
            elif state.get('question'):
                raise ValueError('Answer the pending question before resuming.')
            row.status, state['stage'] = 'queued', 'Resuming from the current browser page'
            # Source recovery allocates a new run directory before its browser
            # exists. Older workers retained the previous run's broker flag,
            # causing attach to fail before the official URL could be opened.
            # Absence of the broker marker proves no browser action occurred in
            # this new run, so it is safe to let step() create that browser.
            if unopened_recovered_source_browser(row, state):
                state['browser_transport'] = None
                state['browser_session_status'] = 'opening'
                state['browser_closed'] = False
                state['session_available'] = False
                state['stage'] = 'Opening the verified official application page'
            state['error'] = None
            state['segment_steps'] = 0
            state['profile_reuse_signatures'] = []
            state['audit_repair_count'] = 0
            # A deliberate operator resume starts a fresh inspection segment.
            # Keep the durable action history, but do not let the repeat guard
            # immediately replay the stop that ended the previous segment. The
            # freshly observed page may now expose controls that rendered late
            # (for example options in a custom select).
            state['action_signature'] = None
            state['repeat_count'] = 0
            if request.action == 'resume':
                recovery = state.get('mistaken_submission_recovery') or {}
                recovery_at = recovery.get('at')
                if (recovery_at and not state.get('submit_started_at')
                        and state.get('mistaken_submission_retry_recovery_at') != recovery_at):
                    state['force_verified_submit_retry'] = {'recovery_at': recovery_at}
            if recovering_input:
                state['interrupted_action_recovery'] = {
                    'at': core.now().isoformat(),
                    'action': state.get('last_action'),
                    'audit': state.get('audit')}
                if (state.get('last_action') or {}).get('kind') == 'check':
                    state['audit_feedback'] = (
                        'The previous native check operation could not verify this custom radio or checkbox. '
                        'Inspect its visible state first. If the choice is still required, use a click action '
                        'on the same observed control instead of another check action. Do not submit here.')
                state['interaction_started'] = False
                state['browser_action_id'] = None
                state['action_signature'] = None
                state['repeat_count'] = 0
                add_event(session, row,
                    'Continuing after an interrupted audited input. The preserved page will be inspected before choosing another action.',
                    'input_recovered')
            elif recovering_source:
                state['source_recovery'] = {
                    'status': 'pending', 'requested_at': core.now().isoformat(),
                    'failed_url': state.get('current_url') or state['posting'].get('source_url')}
                state['interaction_started'] = False
                state['browser_action_id'] = None
                state['action_signature'] = None
                state['repeat_count'] = 0
                state['stage'] = 'Finding the exact role on the official employer or ATS site'
                add_event(session, row,
                    'The listing could not open its application form. Searching for the exact official employer or ATS page.',
                    'source_recovery_started')
            elif recovering_navigation:
                state['navigation_interruption_recovery'] = {
                    'at': core.now().isoformat(),
                    'action': state.get('last_action'),
                    'audit': state.get('audit')}
                state['interaction_started'] = False
                state['browser_action_id'] = None
                state['action_signature'] = None
                state['repeat_count'] = 0
                state['stage'] = 'Inspecting the page reached by the last navigation'
                add_event(session, row,
                    'Continuing after an interrupted navigation. The preserved page will be inspected without replaying the click.',
                    'navigation_recovered')
            elif recovering_validation:
                state['validation_rejection_recovery'] = {
                    'at': core.now().isoformat(),
                    'submit_started_at': state.get('submit_started_at'),
                    'message': 'Employer page explicitly rejected required fields before accepting the application.'}
                state['submit_started_at'] = None
                state['interaction_started'] = False
                state['verification_only'] = False
                state['stage'] = 'Correcting employer-identified validation errors'
                add_event(session, row,
                    'The employer kept the application form open and identified required fields. Correcting them before a new submit attempt.',
                    'validation_rejection_recovered')
        if request.action in {'resume', 'answer', 'verify', 'restart', 'resume_unsubmitted'}:
            settings = await session.get(core.JobAgentState, 'default')
            config = core.saved_config(settings.config) if settings else core.JobAgentConfig()
            selected = request.provider or state.get('ai_provider') or config.browser_ai_provider
            chosen = provider_settings(config, selected, request.model)
            if request.model is None and request.provider is None and state.get('openai_model'):
                chosen['openai_model'] = state['openai_model']
            if chosen != {k: state.get(k) for k in chosen}:
                add_event(session, row, 'AI provider selected: ' + ('Direct OpenAI API' if selected == 'openai' else 'OpenClaw gateway'), 'provider', **chosen)
            state.update(chosen)
        row.state, row.revision, row.updated_at = state, row.revision + 1, core.now()
        add_event(session, row, state['stage'], request.action,
                  **({'reason': state['quit_reason'], 'question': state.get('quit_question')} if request.action == 'quit' else {}))
        await session.commit()
        result = view(row)
    _wake.set()
    return result


async def checkpoint(identity, expected, *, status=None, message=None, kind='progress', **changes):
    async with core.AsyncSessionLocal() as session:
        row = await session.get(BrowserRun, identity, with_for_update=True)
        if not row or row.revision != expected:
            return None  # A pause or answer invalidates an in-flight model decision.
        row.state = {**row.state, **changes}
        row.status = status or row.status
        row.revision += 1
        row.updated_at = core.now()
        if message:
            add_event(session, row, message, kind)
        await session.commit()
        return row


async def model_decision(mode, state, **extra):
    # Use the small, fast Jev model for narrow semantic judgments. Generative
    # controller calls remain the fallback for ambiguity and for tasks that need
    # new text, detailed recovery guidance, or browser actions.
    if mode in {'audit_action', 'verify_confirmation'}:
        from app.services import job_browser_jev
        try:
            if mode == 'audit_action':
                judgment, metadata = await job_browser_jev.audit_action(
                    state, extra['proposed_action'],
                    mailbox_result_available=bool(extra.get('mailbox_result_available')))
            else:
                judgment, metadata = await job_browser_jev.verify_confirmation(
                    state, str(extra.get('evidence') or ''))
            if judgment is not None:
                return judgment, metadata
        except Exception as exc:
            logger.warning('Jev %s judgment unavailable; using configured controller: %s',
                           mode, type(exc).__name__)
    current_profile = {item['id']: item for item in state.get('saved_profile', [])}
    answers = [answer for answer in state.get('answers', []) if answer.get('source') != 'profile' or
        all(c['id'] in current_profile and current_profile[c['id']]['revision'] == c.get('revision')
            for c in answer.get('citations', []))]
    payload = {'mode': mode, 'answer_policy': CONTEXT_SKILL.read_text(), 'job': state['posting'],
            'resume': state['resume']['text'], 'preferences': state['preferences'],
            'saved_profile': state.get('saved_profile', []),
            'operator_answers': answers, 'page': state.get('snapshot'),
            'earlier_pages': state.get('page_evidence', []),
            'recent_action_history': state.get('action_history', []),
            'previous_action': state.get('last_action'), 'previous_error': state.get('error'),
            'audit_feedback': state.get('audit_feedback'),
            'submit_started_at': state.get('submit_started_at'), **extra}
    if state.get('ai_provider', 'gateway') == 'openai':
        from app.services.job_browser_ai import direct_decision
        return await direct_decision(mode, payload, model=state.get('openai_model', 'gpt-5-mini'), instructions=SKILL.read_text())
    result = await call_skill_json(
        skill_path=SKILL, payload=payload,
        required_fields={'decide': ['action'], 'audit_action': ['allowed', 'effect', 'reason', 'recovery', 'repair_hint'],
                         'verify_confirmation': ['confirmed', 'reason'],
                         'extract_confirmation': ['confirmed', 'exact_quote', 'reason'],
                         'resolve_question': ['answer', 'missing_question', 'citations', 'reason']}[mode],
        model='openclaw/main', lane='possibleos-interactive', allow_tools=False,
        timeout_s=90, retries=1, max_tokens=2500)
    return result.parsed, {'provider': 'gateway', 'model': result.model, 'usage': result.usage}


def validate_audit(action, audit):
    if audit.get('allowed') is not True:
        raise ValueError(str(audit.get('reason') or 'This action needs clarification.'))
    allowed_effects = {'fill': {'input'}, 'select': {'input'}, 'check': {'input'},
                      'press': {'input'},
                      'upload': {'input'}, 'goto': {'navigation'},
                      'email_search': {'read'}, 'verification_code': {'submit'},
                      # Custom comboboxes commonly expose their flyout and options
                      # as buttons. Those clicks change a form input without
                      # navigating. The independent audit must still reject submit.
                      'click': {'input', 'navigation', 'advance'}, 'submit': {'submit'}}
    if audit.get('effect') not in allowed_effects.get(action.kind, set()):
        raise ValueError('The action audit identified a different effect. Inspect the page again before proceeding.')


def normalize_observed_action(action, snapshot):
    """Use click semantics for observed radio buttons.

    Some ATS forms render radios as controlled custom buttons. Playwright's
    native set_checked can click them visually while the hidden input still
    reports its old state. Selecting an observed radio is exactly one click;
    real checkboxes retain native checked-state handling.
    """
    if action.kind != 'check' or not action.checked or not action.element:
        return action
    control = next((control for frame in snapshot.get('frames', [])
                    for control in frame.get('controls', [])
                    if control.get('id') == action.element), None)
    if not control or control.get('type') != 'radio':
        return action
    return action.model_copy(update={'kind': 'click'})


def redact_mailbox_action(action: BrowserAction) -> BrowserAction:
    """Keep mailbox queries and returned content out of durable browser state."""
    return action.model_copy(update={'value': '[redacted mailbox query]'})


def redact_mailbox_followup(action: BrowserAction) -> BrowserAction:
    """Persist the action shape without mailbox-derived content or secrets."""
    return action.model_copy(update={
        'summary': 'Used a transient read-only mailbox result',
        'value': '[redacted mailbox result]' if action.value else '',
        'question': '',
        'choices': action.choices if action.kind == 'verification_code' else [],
        'evidence': '',
    })


async def search_current_application_mail(request: MailboxSearchRequest, state: dict) -> dict:
    """Search the proposed phrase, then the verified employer name if it was too narrow."""
    result = await search_zoho_inbox(request)
    firm_name = ' '.join(str(state.get('posting', {}).get('firm_name') or '').split())
    same_query = firm_name.casefold() == request.query.casefold()
    if result.get('matched') or len(firm_name) < 4 or same_query:
        return result
    fallback = await search_zoho_inbox(MailboxSearchRequest(
        query=firm_name, since_hours=request.since_hours, limit=request.limit))
    fallback['employer_fallback_used'] = True
    return fallback


def mailbox_verification_value(action: BrowserAction, mailbox_result: dict, snapshot: dict) -> str:
    """Validate a transient one-time code and its visible form controls."""
    code = action.value.strip()
    if not 4 <= len(code) <= 12 or any(not character.isalnum() for character in code):
        raise ValueError('The newest matching email did not provide a complete one-time code.')
    items = mailbox_result.get('items') or []
    if not items or code not in (items[0].get('excerpt') or ''):
        raise ValueError('The proposed code was not quoted by the newest matching email.')
    controls = {control['id']: control for frame in snapshot.get('frames', [])
                for control in frame.get('controls', [])}
    code_ids = action.choices
    if not code_ids or len(set(code_ids)) != len(code_ids):
        raise ValueError('Select the visible one-time-code input control or controls in order.')
    if len(code_ids) not in {1, len(code)}:
        raise ValueError('The selected one-time-code controls do not match the code length.')
    for control_id in code_ids:
        control = controls.get(control_id) or {}
        if (control.get('tag') != 'input' or control.get('type') in {'password', 'hidden'}
                or control.get('disabled')):
            raise ValueError('The selected one-time-code control is unavailable.')
    submit = controls.get(action.element) or {}
    # Code forms commonly keep their final control disabled until every code
    # input is populated. complete_mailbox_verification observes the page again
    # after filling and requires this same structural control to become enabled.
    if submit.get('tag') not in {'button', 'input'}:
        raise ValueError('The visible verification action is unavailable.')
    return code


def complete_verification_action_shape(action: BrowserAction, snapshot: dict) -> BrowserAction:
    """Recover omitted code-field IDs from their structural position.

    The model has already identified this as an email-code step and selected the
    visible verification control. Some model responses omit ``choices`` even
    though the code inputs are present in the page snapshot. Recover only when
    the inputs form an unambiguous, contiguous group immediately before that
    control. This is DOM bookkeeping, not a semantic guess about page wording.
    """
    if action.kind != 'verification_code' or action.choices:
        return action
    code_length = len(action.value.strip())
    if not code_length:
        return action
    for frame in snapshot.get('frames', []):
        controls = frame.get('controls', [])
        submit_index = next((index for index, control in enumerate(controls)
                             if control.get('id') == action.element), None)
        if submit_index is None:
            continue
        adjacent = []
        for control in reversed(controls[:submit_index]):
            if (control.get('tag') != 'input'
                    or control.get('type') not in {'text', 'tel', 'number'}
                    or control.get('disabled')):
                break
            adjacent.append(control['id'])
        adjacent.reverse()
        if len(adjacent) == code_length:
            return action.model_copy(update={'choices': adjacent})
        if len(adjacent) == 1:
            return action.model_copy(update={'choices': adjacent})
    return action


def verified_failed_submit_retry_action(state, snapshot):
    """Dismiss the proven failure, then return its one deterministic submit."""
    requested = state.get('force_verified_submit_retry') or {}
    recovery = state.get('mistaken_submission_recovery') or {}
    recovery_at = recovery.get('at')
    if (not recovery_at or requested.get('recovery_at') != recovery_at
            or state.get('submit_started_at') or state.get('confirmation')
            or state.get('mistaken_submission_retry_recovery_at') == recovery_at):
        return None
    if (not recovery.get('visible_submit_control')
            or snapshot.get('url') != recovery.get('evidence_url')):
        raise ValueError(
            'The preserved page no longer matches the verified failed-submission recovery.')
    visible = '\n'.join(frame.get('text', '') for frame in snapshot.get('frames', []))
    all_controls = [control for frame in snapshot.get('frames', [])
                    for control in frame.get('controls', [])]
    failure_text = 'Something went wrong. We are working on this, please try again later.'
    dismiss = [control for control in all_controls
               if (control.get('label') or '').strip().casefold() == 'dismiss'
               and not control.get('disabled')]
    if failure_text in visible and len(dismiss) == 1:
        return BrowserAction(
            kind='click', element=dismiss[0]['id'],
            summary='Dismiss the employer’s visible failed-submission error before retrying.',
            evidence=(
                'The preserved application page visibly says the earlier attempt failed '
                'and exposes one enabled Dismiss control.'))
    controls = [control for frame in snapshot.get('frames', [])
                for control in frame.get('controls', [])
                if control.get('type') == 'submit' and not control.get('disabled')]
    labelled_submit = [control for control in controls
                       if (control.get('label') or '').strip().casefold() == 'submit application']
    if len(labelled_submit) == 1:
        controls = labelled_submit
    if len(controls) != 1:
        raise ValueError(
            'The preserved page must expose exactly one identifiable final Submit control '
            'before the failed submission can be retried.')
    return BrowserAction(
        kind='submit', element=controls[0]['id'],
        summary='Retry the completed application after the preserved form proved the prior attempt failed.',
        evidence=(
            'The operator returned the same preserved application form as unsubmitted; '
            'the current URL matches that recovery evidence and exactly one enabled final '
            'Submit control remains visible.'))


def verified_failed_submit_retry_audit(action):
    """Fixed audit for the page-proven, timestamp-bound recovery actions."""
    if action.kind not in {'click', 'submit'}:
        raise ValueError('Unexpected failed-submission recovery action.')
    return {
        'allowed': True,
        'effect': 'submit' if action.kind == 'submit' else 'input',
        'reason': (
            'The preserved page and recovery timestamp deterministically establish '
            'this bounded failed-submission recovery action.'),
        'recovery': 'none',
        'repair_hint': '',
    }


def verification_control_descriptor(snapshot: dict, element: str) -> dict:
    """Identify one observed control structurally without relying on page wording."""
    for frame_index, frame in enumerate(snapshot.get('frames', [])):
        for control_index, control in enumerate(frame.get('controls', [])):
            if control.get('id') == element:
                return {
                    'frame_index': frame_index,
                    'control_index': control_index,
                    'tag': control.get('tag'),
                    'type': control.get('type'),
                    'role': control.get('role'),
                    'label': control.get('label'),
                    'required': control.get('required'),
                }
    raise ValueError('The selected email-verification control is no longer visible.')


def resolve_verification_control(snapshot: dict, descriptor: dict) -> dict:
    """Resolve a fresh browser element ID only when its structural identity is unchanged."""
    try:
        control = snapshot['frames'][descriptor['frame_index']]['controls'][descriptor['control_index']]
    except (IndexError, KeyError, TypeError) as exc:
        raise ValueError('The email-verification form changed while the code was being entered.') from exc
    for field in ('tag', 'type', 'role', 'label', 'required'):
        if control.get(field) != descriptor.get(field):
            raise ValueError('The email-verification form changed while the code was being entered.')
    return control


async def complete_mailbox_verification(identity: str, row: BrowserRun,
                                        browser, action: BrowserAction,
                                        mailbox_result: dict, snapshot: dict):
    """Enter a newest-message code transiently and perform its verification once."""
    code = mailbox_verification_value(action, mailbox_result, snapshot)
    resume = ROOT / row.run_id / 'resume.pdf'
    screenshot_path = ROOT / row.run_id / 'page.png'
    field_descriptors = [verification_control_descriptor(snapshot, element)
                         for element in action.choices]
    submit_descriptor = verification_control_descriptor(snapshot, action.element)
    durable_action = redact_mailbox_followup(action)
    changes = {
        'status': 'verifying',
        'stage': 'Completing email verification',
        'interaction_started': True,
        'human_verification_submit_started_at': core.now().isoformat(),
        'last_action': durable_action.model_dump(),
        'action_history': [*row.state.get('action_history', []), durable_action.model_dump()][-40:],
        'steps': row.state.get('steps', 0) + 1,
        'segment_steps': row.state.get('segment_steps', 0) + 1,
    }
    if isinstance(browser, PersistentBrowserSession):
        browser.action_id = uuid4().hex
        changes['browser_action_id'] = browser.action_id
    saved = await checkpoint(identity, row.revision,
        message='Using the newest matching application email to complete the visible verification step once.',
        kind='email_verification', **changes)
    if not saved:
        raise ValueError('The browser progressed. Refresh its status before this action.')
    try:
        values = [code] if len(field_descriptors) == 1 else list(code)
        for descriptor, value in zip(field_descriptors, values, strict=True):
            control = resolve_verification_control(snapshot, descriptor)
            await browser.execute(BrowserAction(kind='fill', element=control['id'], value=value,
                                                summary='Enter the email verification code'), resume)
            snapshot = await browser.observe(screenshot_path)
        current_fields = [resolve_verification_control(snapshot, descriptor)
                          for descriptor in field_descriptors]
        registered = ''.join(control.get('value', '') for control in current_fields)
        if registered != code:
            raise ValueError('The verification form did not register the complete one-time code.')
        submit = resolve_verification_control(snapshot, submit_descriptor)
        if submit.get('disabled'):
            raise ValueError('The email verification action is still disabled after entering the code.')
        if isinstance(browser, PersistentBrowserSession):
            browser.action_id = uuid4().hex
        await browser.execute(BrowserAction(kind='submit', element=submit['id'],
                                            summary='Complete email verification'), resume)
    except Exception as exc:
        screenshot_path.unlink(missing_ok=True)
        await checkpoint(identity, saved.revision, status='submission_uncertain',
            stage='Email-verification submission needs review',
            screenshot=False,
            error=str(exc)[:1200] or type(exc).__name__,
            message='The verification action was attempted; inspect the page without replaying it.',
            kind='error')
        raise
    screenshot_path.unlink(missing_ok=True)
    await checkpoint(identity, saved.revision, status='verifying', interaction_started=False,
        human_verification_click_completed_at=core.now().isoformat(), error=None,
        screenshot=False,
        message='Email verification completed; checking the employer page for confirmation without resubmitting.',
        kind='email_verification_completed')
    _wake.set()


async def resolve_saved_question(state, question):
    from app.services.job_browser_ai import ProfileResolution
    result = usage = None
    try:
        from app.services.job_browser_jev import resolve_profile_question
        result, usage = await resolve_profile_question(state, question)
    except Exception as exc:
        logger.warning('Jev saved-answer selection unavailable; using configured controller: %s',
                       type(exc).__name__)
    if result is None:
        result, usage = await model_decision('resolve_question', state, proposed_question=question)
    resolved = ProfileResolution.model_validate(result)
    sources = {item['id']: item for item in state.get('saved_profile', [])}
    for citation in resolved.citations:
        if citation.id not in sources or not citation.quote.strip() or citation.quote not in sources[citation.id]['answer']:
            raise ValueError('Saved-answer reuse could not be verified against the original answer.')
    if resolved.answer.strip() and not resolved.citations:
        raise ValueError('Saved-answer reuse needs a source from the applicant profile.')
    if not resolved.answer.strip() and not resolved.missing_question.strip():
        raise ValueError('The agent did not resolve the question or identify missing information.')
    return resolved, usage


async def step(row):
    identity, state = row.candidate_id, row.state
    directory = ROOT / row.run_id
    if not state.get('resume'):
        from app.services.job_agent_processing import application_resume
        row = await checkpoint(identity, row.revision, status='running',
            stage='Matching the job to a category and selecting its resume')
        if not row:
            return
        selected = await application_resume(identity, state['posting'])
        resume = selected['resume']
        shutil.copyfile(resolve_resume(resume['path']), directory / 'resume.pdf')
        (directory / 'resume.pdf').chmod(0o600)
        await checkpoint(identity, row.revision, resume=resume, category_id=selected['category_id'],
            resume_filename=resume['filename'], stage='Resume selected; opening the application',
            message='Resume selected: ' + resume['filename'], kind='resume')
        return
    if (state.get('source_recovery') or {}).get('status') == 'pending':
        row = await checkpoint(identity, row.revision, status='running',
            stage='Searching for the exact official employer or ATS application page',
            message='Searching for the exact role on the official employer or ATS site.',
            kind='source_recovery_search')
        if row:
            await recover_official_source(row)
        return
    browser = _sessions.get(identity)
    if not browser and state.get('browser_transport') == 'broker':
        browser = await attach_browser(row)
    if not browser:
        if state.get('submit_started_at') or state.get('interaction_started'):
            await checkpoint(identity, row.revision, status='submission_uncertain',
                stage='Original browser lost; review the saved evidence before any further submission')
            return
        if len(_sessions) >= int(os.getenv('JOB_BROWSER_MAX_SESSIONS', '3')):
            await checkpoint(identity, row.revision, status='paused', stage='Browser capacity reached',
                error='Other browser sessions are waiting for answers. Finish them, then resume this job.')
            return
        # Persist ownership before launch so a crash cannot silently recreate a page.
        row = await checkpoint(identity, row.revision, browser_transport='broker',
                               browser_closed=False, browser_session_status='opening')
        if not row:
            return
        state = row.state
        browser = PersistentBrowserSession(row.run_id)
        start_url = (state.get('application_source_url')
                     or state['posting'].get('application_url')
                     or state['posting']['source_url'])
        await browser.open(start_url)
        _sessions[identity] = browser
    screenshot = directory / 'page.png'
    snapshot = await browser.observe(screenshot)
    page_evidence = list(state.get('page_evidence', []))
    evidence = {'url': snapshot['url'], 'text': '\n'.join(f.get('text', '') for f in snapshot['frames'])[:6000]}
    if not page_evidence or page_evidence[-1] != evidence:
        page_evidence.append(evidence)
        # Retain the original role page as well as recent multi-page form context.
        page_evidence = page_evidence[:1] + page_evidence[-5:] if len(page_evidence) > 6 else page_evidence
    saved_profile = await profile.snapshot(identity)
    profile_history = list(state.get('profile_history', []))
    if saved_profile != state.get('saved_profile', []):
        profile_history.append({'at': core.now().isoformat(), 'items': saved_profile})
    read_only = bool(state.get('submit_started_at') or state.get('interaction_started') or state.get('verification_only'))
    row = await checkpoint(identity, row.revision,
        status='verifying' if read_only else 'running',
        stage='Inspecting the application page', snapshot=snapshot, page_evidence=page_evidence,
        current_url=snapshot['url'], session_available=True, screenshot=True,
        browser_session_status='available',
        saved_profile=saved_profile, profile_count=len(saved_profile), profile_history=profile_history)
    if not row:
        return
    state = row.state
    action = verified_failed_submit_retry_action(state, snapshot)
    forced_failed_submit_retry = action is not None
    if not forced_failed_submit_retry:
        decision, usage = await model_decision(
            'decide', state, action_schema=BrowserAction.model_json_schema())
        action = BrowserAction.model_validate(decision['action'])
        action = normalize_observed_action(action, snapshot)
    else:
        usage = {'provider': 'deterministic_recovery', 'model': None, 'usage': {}}
    mailbox_derived = False
    mailbox_result = None
    if action.kind == 'email_search':
        if state.get('mailbox_search_count', 0) >= 3:
            raise ValueError('This application reached its three-search mailbox limit.')
        search_audit, search_audit_usage = await model_decision(
            'audit_action', state, proposed_action=action.model_dump())
        from app.services.job_browser_ai import ActionAudit
        search_audit = ActionAudit.model_validate(search_audit).model_dump()
        validate_audit(action, search_audit)
        request = MailboxSearchRequest(query=action.value)
        mailbox_result = await search_current_application_mail(request, state)
        redacted_action = redact_mailbox_action(action)
        row = await checkpoint(identity, row.revision,
            stage='Checked the Zoho inbox without changing mailbox state',
            last_action=redacted_action.model_dump(),
            action_history=[*state.get('action_history', []), redacted_action.model_dump()][-40:],
            steps=state.get('steps', 0) + 1,
            segment_steps=state.get('segment_steps', 0) + 1,
            mailbox_search_count=state.get('mailbox_search_count', 0) + 1,
            mailbox_search_last={'at': core.now().isoformat(), 'matched': mailbox_result['matched'],
                                 'since_hours': mailbox_result['since_hours']},
            message=f"Read-only Zoho inbox search found {mailbox_result['matched']} matching message(s).",
            kind='email_search', model=usage, audit=search_audit, audit_model=search_audit_usage)
        if not row:
            return
        state = row.state
        decision, usage = await model_decision('decide', state,
            action_schema=BrowserAction.model_json_schema(), mailbox_search_result=mailbox_result)
        action = BrowserAction.model_validate(decision['action'])
        action = complete_verification_action_shape(action, snapshot)
        if action.kind == 'email_search':
            raise ValueError('Only one mailbox search is allowed per browser step.')
        mailbox_derived = True
    durable_action = redact_mailbox_followup(action) if mailbox_derived else action
    if mailbox_derived and (action.kind == 'confirmed'
                            or (action.kind == 'ask' and mailbox_result.get('matched'))):
        raise ValueError('Mailbox content cannot become a durable question or submission confirmation.')
    if read_only and action.kind not in {'confirmed', 'wait', 'email_search',
                                         'verification_code', 'ask', 'blocked'}:
        raise ValueError('Submission was already attempted. Only read-only verification is allowed.')
    if action.kind == 'ask':
        if mailbox_derived and mailbox_result.get('matched'):
            raise ValueError('Mailbox content cannot be persisted as an applicant question.')
        if read_only:
            await checkpoint(identity, row.revision, status='submission_uncertain',
                             stage='Submission needs manual verification', error=action.question or action.summary)
        else:
            if not action.question.strip():
                raise ValueError('The agent did not provide a question to answer.')
            if state.get('saved_profile'):
                resolution, reuse_usage = await resolve_saved_question(state, action.question)
                if resolution.answer.strip():
                    signature = hashlib.sha256(json.dumps([action.question, resolution.answer,
                        [c.model_dump() for c in resolution.citations]], sort_keys=True).encode()).hexdigest()
                    if signature in state.get('profile_reuse_signatures', []):
                        raise ValueError('The agent repeated a question already answered from your profile. Resume to retry using the saved answer.')
                    row = await checkpoint(identity, row.revision,
                        answers=[*state.get('answers', []), {'question': action.question,
                            'answer': resolution.answer, 'at': core.now().isoformat(), 'source': 'profile',
                            'citations': [dict(c.model_dump(), revision=next(item['revision'] for item in state['saved_profile'] if item['id'] == c.id)) for c in resolution.citations]}],
                        profile_reuse_signatures=[*state.get('profile_reuse_signatures', []), signature],
                        message='Reused a saved applicant answer; no need to ask you again.', kind='profile_reused',
                        stage='Using saved applicant information', profile_reuse_model=reuse_usage)
                    if not row:
                        return
                if not resolution.missing_question.strip():
                    return
                action = action.model_copy(update={'question': resolution.missing_question[:1500], 'choices': []})
            await checkpoint(identity, row.revision, status='waiting_for_answer',
                stage='Waiting for your answer', question={'id': uuid4().hex,
                'text': action.question, 'choices': action.choices},
                message=action.question, kind='question', model=usage)
        return
    if action.kind == 'blocked':
        blocked_message = (durable_action.summary if mailbox_derived else action.summary)
        await checkpoint(identity, row.revision,
            status='submission_uncertain' if read_only else 'blocked',
            stage='Manual help needed', error=blocked_message, message=blocked_message, kind='blocked')
        return
    if action.kind == 'confirmed':
        visible = '\n'.join(f.get('text', '') for f in snapshot['frames'])
        if not state.get('submit_started_at'):
            raise ValueError('No submission attempt was recorded for this application.')
        evidence = action.evidence.strip()
        extraction_usage = None
        if not evidence or evidence not in visible:
            extraction, extraction_usage = await model_decision(
                'extract_confirmation', state, visible_page_text=visible)
            from app.services.job_browser_ai import ConfirmationEvidence
            extraction = ConfirmationEvidence.model_validate(extraction)
            evidence = extraction.exact_quote.strip()
            if not extraction.confirmed or not evidence or evidence not in visible:
                raise ValueError('Exact visible submission confirmation evidence was not established.')
        verification, verify_usage = await model_decision('verify_confirmation', state, evidence=evidence)
        if verification.get('confirmed') is not True:
            raise ValueError('Submission confirmation could not be verified: ' + str(verification.get('reason', '')))
        saved = await checkpoint(identity, row.revision, status='submitted', stage='Website submission confirmed',
            confirmation={'quote': evidence, 'url': snapshot['url'], 'at': core.now().isoformat(),
                          'verification': verification, 'model': verify_usage,
                          'extraction_model': extraction_usage},
            message='The employer page confirmed this application.', kind='submitted', session_available=False,
            browser_closed=True, browser_session_status='closed')
        if saved:
            await browser.close()
            _sessions.pop(identity, None)
        return
    if action.kind != 'wait':
        row = await checkpoint(identity, row.revision,
            stage='Checking the proposed action against your resume, answers and this role')
        if not row:
            return
        state = row.state
        if forced_failed_submit_retry:
            audit = verified_failed_submit_retry_audit(action)
            audit_usage = {
                'provider': 'deterministic_recovery', 'model': None, 'usage': {}}
        else:
            audit, audit_usage = await model_decision(
                'audit_action', state, proposed_action=durable_action.model_dump(),
                mailbox_result_available=mailbox_derived)
            from app.services.job_browser_ai import ActionAudit
            audit = ActionAudit.model_validate(audit).model_dump()
        if not audit['allowed'] and audit['recovery'] == 'correct_form':
            if state.get('submit_started_at') or state.get('interaction_started'):
                raise ValueError('An interaction may already have submitted. Verify before changing the form.')
            repairs = state.get('audit_repair_count', 0) + 1
            exhausted = repairs >= 3
            await checkpoint(identity, row.revision,
                status='blocked' if exhausted else 'running',
                stage='Form correction needs review' if exhausted else 'Correcting the form before submission',
                error=('The agent could not correct the form after three rejected proposals. ' + audit['reason']) if exhausted else None,
                audit_feedback={'reason': audit['reason'], 'repair_hint': audit['repair_hint'],
                                'rejected_action': durable_action.model_dump()},
                audit_repair_count=repairs, segment_steps=state.get('segment_steps', 0) + 1,
                audit=audit, audit_model=audit_usage, model=usage,
                message=('Automatic correction stopped: ' if exhausted else 'Fixing form: ') + (audit['repair_hint'] or audit['reason']),
                kind='audit_repair_stopped' if exhausted else 'audit_repair')
            return  # Rejected actions are never dispatched or counted as submit attempts.
        try:
            validate_audit(action, audit)
        except ValueError as exc:
            # Preserve the proposal that actually failed. Previously the UI showed
            # the last successful action/audit, which made this stop misleading.
            await checkpoint(identity, row.revision, status='blocked',
                stage='Proposed browser action did not pass its safety audit',
                error=str(exc), failed_action=durable_action.model_dump(), failed_audit=audit,
                failed_model=usage, failed_audit_model=audit_usage,
                message=f'Stopped before {durable_action.summary}: {audit.get("reason") or str(exc)}',
                kind='audit_blocked')
            return
    else:
        audit, audit_usage = {}, {}
    if action.kind == 'verification_code':
        if not mailbox_derived or mailbox_result is None:
            raise ValueError('Email verification requires a fresh, scoped Zoho inbox search in this browser step.')
        await complete_mailbox_verification(identity, row, browser, action, mailbox_result, snapshot)
        return
    if action.kind == 'submit':
        if not state.get('authorized_at') or state.get('submit_started_at'):
            raise ValueError('A new website submission is not authorized.')
        recovery = state.get('mistaken_submission_recovery') or {}
        recovery_at = recovery.get('at')
        if (recovery_at
                and state.get('mistaken_submission_retry_recovery_at') == recovery_at):
            raise ValueError(
                'The verified failed-submission retry was already attempted. '
                'New page evidence is required before another submission.')
        async with core.AsyncSessionLocal() as session:
            candidate = await session.get(core.JobAgentCandidate, identity)
            from app.services.job_agent_processing import job_key
            if not candidate or candidate.posting.get('status') == 'closed' or job_key(candidate.posting) != job_key(state['posting']):
                raise ValueError('The saved job changed or closed. Review before submitting.')
    resume = directory / 'resume.pdf'
    if hashlib.sha256(resume.read_bytes()).hexdigest() != state['resume']['sha256']:
        raise ValueError('The selected resume changed. Application stopped.')
    signature = hashlib.sha256(json.dumps({'action': action.model_dump(exclude={'summary', 'evidence'}),
                                          'snapshot': snapshot}, sort_keys=True).encode()).hexdigest()
    repeated = state.get('repeat_count', 0) + 1 if signature == state.get('action_signature') else 1
    if repeated >= 3:
        raise ValueError('The same action is repeating without page progress. Review the page before resuming.')
    # Reject a stale model element BEFORE recording a possible interaction.
    if action.kind not in {'goto', 'wait'} and not any(
            c.get('id') == action.element for f in snapshot.get('frames', [])
            for c in f.get('controls', [])):
        raise ValueError('The agent selected an unavailable form control. Resume to inspect the page again, or restart from beginning.')
    # Write ahead of any potentially consequential click/navigation. A crash in
    # this interval is uncertain, even if the model incorrectly called it Next.
    interaction = action.kind in {'click', 'submit', 'goto', 'check', 'select'}
    changes = {'stage': durable_action.summary, 'last_action': durable_action.model_dump(),
               'action_history': [*state.get('action_history', []), durable_action.model_dump()][-40:],
               'model': usage, 'audit': audit, 'audit_model': audit_usage,
               'interaction_started': interaction,
               'steps': state.get('steps', 0) + 1,
               'segment_steps': state.get('segment_steps', 0) + 1}
    changes.update(action_signature=signature, repeat_count=repeated)
    if isinstance(browser, PersistentBrowserSession):
        browser.action_id = uuid4().hex
        changes['browser_action_id'] = browser.action_id
    if action.kind == 'submit':
        changes['submit_started_at'] = core.now().isoformat()
        recovery_at = (state.get('mistaken_submission_recovery') or {}).get('at')
        if recovery_at:
            changes['mistaken_submission_retry_recovery_at'] = recovery_at
            changes['force_verified_submit_retry'] = None
    row = await checkpoint(identity, row.revision, message=durable_action.summary, kind=action.kind, **changes)
    if not row:
        return
    await browser.execute(action, resume)
    input_completed = core.now().isoformat() if audit.get('effect') == 'input' else state.get('form_input_completed_at')
    await checkpoint(identity, row.revision, interaction_started=False, error=None,
        form_input_completed_at=input_completed,
        failed_action=None, failed_audit=None, failed_model=None, failed_audit_model=None,
        audit_feedback=None, audit_repair_count=0,
        status='verifying' if action.kind == 'submit' else None)


async def recover():
    async with core.AsyncSessionLocal() as session:
        rows = (await session.scalars(select(BrowserRun).where(BrowserRun.status.notin_(['submitted', 'cancelled'])))).all()
        for row in rows:
            state = dict(row.state)
            available = False
            if state.get('browser_transport') == 'broker' and not state.get('browser_closed'):
                try:
                    available = bool(await attach_browser(row))
                    state['browser_session_status'] = 'available'
                except ValueError as exc:
                    state['browser_session_status'] = 'unavailable'
                    state['session_error'] = str(exc)
            uncertain = state.get('submit_started_at') or state.get('interaction_started')
            source_pending = (state.get('source_recovery') or {}).get('status') == 'pending'
            if row.status == 'human_control':
                expires = state.get('human_control_expires_at')
                try:
                    expired = not expires or datetime.fromisoformat(expires) <= datetime.now(timezone.utc)
                except (TypeError, ValueError):
                    expired = True
                if expired:
                    state.pop('human_control_token_sha256', None)
                    state.pop('human_control_expires_at', None)
                    row.status = 'paused'
                    state['stage'] = 'Human-control lease expired; browser preserved and paused'
                elif available:
                    state['stage'] = 'Human control restored after backend restart'
                else:
                    row.status = 'paused'
                    state['stage'] = 'Human-control browser is unavailable; progress remains saved'
            elif source_pending and not state.get('submit_started_at'):
                row.status = 'queued'
                state['stage'] = 'Continuing official application-page recovery after worker restart'
            elif uncertain:
                row.status = 'submission_uncertain'
                state['stage'] = ('Browser preserved; check confirmation without resubmitting' if available else
                                  'Worker restarted after a possible submission; manual verification required')
            elif row.status in ACTIVE:
                row.status = 'paused'
                state['stage'] = ('Browser preserved; resume from the existing form' if available else
                                  'Worker restarted; review browser session status before continuing')
            state['session_available'] = available
            if available:
                state.pop('session_error', None)
                add_event(session, row, 'Worker reconnected to the preserved browser. No action or submission was replayed.', 'reconnected')
            row.state, row.revision = state, row.revision + 1
            row.updated_at = core.now()
        await session.commit()


async def worker():
    await core.ensure_tables()
    async with core.async_engine.connect() as lock:
        if not await lock.scalar(text('SELECT pg_try_advisory_lock(734985227)')):
            return
        await lock.commit()
        await recover()
        await profile.import_browser_answers()
        try:
            while True:
                _wake.clear()
                async with core.AsyncSessionLocal() as session:
                    row = await session.scalar(select(BrowserRun).where(
                        BrowserRun.status.in_(ACTIVE)).order_by(BrowserRun.updated_at).limit(1))
                if not row:
                    try:
                        await asyncio.wait_for(_wake.wait(), timeout=3)
                    except asyncio.TimeoutError:
                        pass
                    continue
                try:
                    if row.state.get('segment_steps', 0) >= int(os.getenv('JOB_BROWSER_STEP_BUDGET', '60')):
                        raise ValueError('This run reached its step budget. Review progress and resume if further work is needed.')
                    await asyncio.wait_for(step(row), timeout=240)
                except Exception as exc:
                    logger.warning('Browser application stopped: %s', type(exc).__name__)
                    async with core.AsyncSessionLocal() as session:
                        current = await session.get(BrowserRun, row.candidate_id)
                    if current and current.status in ACTIVE:
                        if recoverable_source_navigation(current.state):
                            recovery = {
                                'status': 'pending', 'requested_at': core.now().isoformat(),
                                'failed_url': (current.state.get('current_url')
                                               or current.state['posting'].get('source_url'))}
                            await checkpoint(current.candidate_id, current.revision,
                                status='queued', interaction_started=False,
                                browser_action_id=None, source_recovery=recovery,
                                stage='Finding the exact role on the official employer or ATS site',
                                error=None,
                                message='The listing did not open its form. Searching for the exact official application page.',
                                kind='source_recovery_started')
                        else:
                            uncertain = current.state.get('submit_started_at') or current.state.get('interaction_started')
                            await checkpoint(current.candidate_id, current.revision,
                                status='submission_uncertain' if uncertain else 'blocked',
                                stage='Submission needs verification' if uncertain else 'Browser application stopped',
                                error=str(exc)[:1200] or type(exc).__name__,
                                message='Browser processing stopped; review the saved error.', kind='error')
                await asyncio.sleep(0.25)
        finally:
            for browser in list(_sessions.values()):
                if isinstance(browser, PersistentBrowserSession):
                    await browser.detach()
                else:
                    await browser.close()  # Legacy in-process sessions only.
            _sessions.clear()
            await lock.execute(text('SELECT pg_advisory_unlock(734985227)'))
            await lock.commit()


async def screenshot_path(identity):
    async with core.AsyncSessionLocal() as session:
        row = await session.get(BrowserRun, identity)
        if not row or not row.state.get('screenshot'):
            raise KeyError(identity)
        return ROOT / row.run_id / 'page.png'
