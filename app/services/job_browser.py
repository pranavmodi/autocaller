"""Durable, operator-authorized browser applications, separate from Zoho sends."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
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


class ControlRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=1)
    action: Literal['pause', 'resume', 'answer', 'verify', 'release', 'restart', 'reconnect', 'quit', 'challenge']
    reason: str = Field('', max_length=1000)
    question_id: str | None = None
    answer: str = Field('', max_length=8000)
    provider: Literal['gateway', 'openai'] | None = None
    remember: bool = True


def provider_settings(config, provider=None):
    selected = provider or config.browser_ai_provider
    if selected == 'openai' and not os.getenv('OPENAI_API_KEY', '').strip():
        raise ValueError('Direct OpenAI API requires OPENAI_API_KEY on the server. Choose the gateway or configure the key.')
    return {'ai_provider': selected, 'openai_model': config.browser_openai_model}


def undispatched_missing_control(state):
    # Compatibility with the exact local pre-dispatch error from older workers.
    # This is an exception identity check, not a semantic interpretation of a page.
    action = state.get('last_action') or {}
    return (state.get('error') == 'The selected control is no longer in the current page snapshot.'
            and action.get('kind') in {'fill', 'check', 'select', 'upload', 'click'}
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
            and action.get('kind') in {'fill', 'check', 'select', 'upload', 'click'}
            and audit.get('allowed') is True
            and audit.get('effect') == 'input')


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


def restart_blocker(row):
    state = row.state
    if row.status in ACTIVE:
        return 'Pause the application before restarting.'
    if row.status == 'submitted' or state.get('confirmation') or state.get('submit_started_at'):
        return 'A submission was attempted or confirmed. Verify it before starting another application.'
    if recoverable_input_interruption(state):
        return None
    if state.get('interaction_started') and not undispatched_missing_control(state):
        return 'An earlier browser interaction may have submitted the form. Verify its outcome first.'
    if row.status == 'submission_uncertain' and not undispatched_missing_control(state):
        return 'The previous submission outcome must be verified before restarting.'
    return None


def view(row):
    if not row:
        return {'status': 'not_started', 'revision': 0}
    # Keep resume text / internal page context out of polling responses.
    state = {k: v for k, v in row.state.items() if k not in {'resume', 'posting', 'preferences', 'snapshot', 'page_evidence', 'action_history', 'saved_profile', 'profile_history', 'attempt_history'}}
    can_resume = ((row.status in {'paused', 'blocked'}
                   and not state.get('submit_started_at') and not state.get('interaction_started'))
                  or (row.status == 'submission_uncertain' and recoverable_input_interruption(state)))
    return {**state, 'status': row.status, 'revision': row.revision,
            'run_id': row.run_id, 'updated_at': row.updated_at.isoformat(),
            'can_restart': restart_blocker(row) is None, 'restart_blocked_reason': restart_blocker(row),
            'can_resume': can_resume,
            'recoverable_input_interruption': recoverable_input_interruption(state),
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


async def list_runs():
    await core.ensure_tables()
    async with core.AsyncSessionLocal() as session:
        rows = (await session.scalars(select(BrowserRun).order_by(BrowserRun.updated_at.desc()))).all()
        return {'items': [dict(view(r), candidate_id=r.candidate_id,
                               title=r.state['posting'].get('title'),
                               firm_name=r.state['posting'].get('firm_name')) for r in rows]}


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
        ai_settings = provider_settings(config, request.provider)
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
                or state.get('confirmation') or state.get('human_verification_completed_at')):
            raise ValueError('A pending human-verification challenge was not established for this application.')
        browser = await attach_browser(row)
        if not browser:
            raise ValueError('The preserved application browser is unavailable.')
        run_id = row.run_id
        expected = row.revision
        resume = ROOT / run_id / 'resume.pdf'
        if hashlib.sha256(resume.read_bytes()).hexdigest() != state['resume']['sha256']:
            raise ValueError('The selected resume changed. Application stopped.')
    snapshot = await browser.observe(ROOT / run_id / 'page.png')
    for index, character in enumerate(code_value):
        code_controls, submit_control = human_verification_controls(snapshot)
        if not code_controls or not submit_control:
            raise ValueError('The preserved page no longer shows the expected human-verification challenge.')
        await browser.execute(BrowserAction(kind='fill', element=code_controls[index]['id'], value=character,
                                            summary='Enter one character of the human-supplied security code'), resume)
        if index < len(code_value) - 1:
            snapshot = await browser.observe(ROOT / run_id / 'page.png')
    # Re-observe because broker element handles are scoped to one observation.
    snapshot = await browser.observe(ROOT / run_id / 'page.png')
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
    saved = await checkpoint(identity, row.revision, status='verifying',
        stage='Checking the employer confirmation after human verification',
        interaction_started=False, human_verification_completed_at=core.now().isoformat(), error=None,
        message='Human verification completed; checking the employer confirmation without resubmitting.',
        kind='human_verification_completed')
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
        if row.status == 'cancelled' and request.action not in {'restart', 'release'}:
            raise ValueError('You quit this application. Use Restart from beginning if you decide to apply again.')
        if request.provider is not None and request.action not in {'resume', 'answer', 'verify', 'restart'}:
            raise ValueError('Choose a provider when starting, resuming, answering, or checking confirmation.')
        if request.action == 'quit':
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
        else:
            recovering_input = (request.action == 'resume'
                                and row.status == 'submission_uncertain'
                                and recoverable_input_interruption(state))
            if (row.status in ACTIVE or (row.status in LOCKED and not recovering_input)
                    or state.get('submit_started_at')
                    or (state.get('interaction_started') and not recovering_input)):
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
            state['error'] = None
            state['segment_steps'] = 0
            state['profile_reuse_signatures'] = []
            state['audit_repair_count'] = 0
            if recovering_input:
                state['interrupted_action_recovery'] = {
                    'at': core.now().isoformat(),
                    'action': state.get('last_action'),
                    'audit': state.get('audit')}
                state['interaction_started'] = False
                state['browser_action_id'] = None
                state['action_signature'] = None
                state['repeat_count'] = 0
                add_event(session, row,
                    'Continuing after an interrupted audited input. The preserved page will be inspected before choosing another action.',
                    'input_recovered')
        if request.action in {'resume', 'answer', 'verify', 'restart'}:
            settings = await session.get(core.JobAgentState, 'default')
            config = core.saved_config(settings.config) if settings else core.JobAgentConfig()
            selected = request.provider or state.get('ai_provider') or config.browser_ai_provider
            chosen = provider_settings(config, selected)
            if request.provider is None and state.get('openai_model'):
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
                         'resolve_question': ['answer', 'missing_question', 'citations', 'reason']}[mode],
        model='openclaw/main', lane='possibleos-interactive', allow_tools=False,
        timeout_s=90, retries=1, max_tokens=2500)
    return result.parsed, {'provider': 'gateway', 'model': result.model, 'usage': result.usage}


def validate_audit(action, audit):
    if audit.get('allowed') is not True:
        raise ValueError(str(audit.get('reason') or 'This action needs clarification.'))
    allowed_effects = {'fill': {'input'}, 'select': {'input'}, 'check': {'input'},
                      'upload': {'input'}, 'goto': {'navigation'},
                      # Custom comboboxes commonly expose their flyout and options
                      # as buttons. Those clicks change a form input without
                      # navigating. The independent audit must still reject submit.
                      'click': {'input', 'navigation', 'advance'}, 'submit': {'submit'}}
    if audit.get('effect') not in allowed_effects.get(action.kind, set()):
        raise ValueError('The action audit identified a different effect. Inspect the page again before proceeding.')


async def resolve_saved_question(state, question):
    from app.services.job_browser_ai import ProfileResolution
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
        await browser.open(state['posting']['source_url'])
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
    decision, usage = await model_decision('decide', state, action_schema=BrowserAction.model_json_schema())
    action = BrowserAction.model_validate(decision['action'])
    if read_only and action.kind not in {'confirmed', 'wait', 'ask', 'blocked'}:
        raise ValueError('Submission was already attempted. Only read-only verification is allowed.')
    if action.kind == 'ask':
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
        await checkpoint(identity, row.revision,
            status='submission_uncertain' if read_only else 'blocked',
            stage='Manual help needed', error=action.summary, message=action.summary, kind='blocked')
        return
    if action.kind == 'confirmed':
        visible = '\n'.join(f.get('text', '') for f in snapshot['frames'])
        if not state.get('submit_started_at') or not action.evidence.strip() or action.evidence not in visible:
            raise ValueError('No submission attempt and exact visible confirmation evidence were established.')
        verification, verify_usage = await model_decision('verify_confirmation', state, evidence=action.evidence)
        if verification.get('confirmed') is not True:
            raise ValueError('Submission confirmation could not be verified: ' + str(verification.get('reason', '')))
        saved = await checkpoint(identity, row.revision, status='submitted', stage='Website submission confirmed',
            confirmation={'quote': action.evidence, 'url': snapshot['url'], 'at': core.now().isoformat(),
                          'verification': verification, 'model': verify_usage},
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
        audit, audit_usage = await model_decision('audit_action', state, proposed_action=action.model_dump())
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
                                'rejected_action': action.model_dump()},
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
                error=str(exc), failed_action=action.model_dump(), failed_audit=audit,
                failed_model=usage, failed_audit_model=audit_usage,
                message=f'Stopped before {action.summary}: {audit.get("reason") or str(exc)}',
                kind='audit_blocked')
            return
    else:
        audit, audit_usage = {}, {}
    if action.kind == 'submit':
        if not state.get('authorized_at') or state.get('submit_started_at'):
            raise ValueError('A new website submission is not authorized.')
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
    changes = {'stage': action.summary, 'last_action': action.model_dump(),
               'action_history': [*state.get('action_history', []), action.model_dump()][-40:],
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
    row = await checkpoint(identity, row.revision, message=action.summary, kind=action.kind, **changes)
    if not row:
        return
    await browser.execute(action, resume)
    await checkpoint(identity, row.revision, interaction_started=False, error=None,
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
            if uncertain:
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
