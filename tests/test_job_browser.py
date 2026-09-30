"""Browser application safety and real-browser form workflow regression tests."""
import asyncio
import hashlib
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.services import job_agent as core, job_agent_processing as processing
from app.services import job_browser as service
from app.services import job_browser_jev
from app.services import job_browser_tools
from app.services.job_browser_tools import (
    BrowserAction, BrowserProgram, BrowserSession, validate_fast_program)


@pytest.fixture(autouse=True)
def no_live_browser_jev(monkeypatch):
    """Browser workflow tests exercise their mocked controller, never live Jev."""
    async def uncertain(*_args, **_kwargs):
        return None, {}

    monkeypatch.setattr(job_browser_jev, 'audit_action', uncertain)
    monkeypatch.setattr(job_browser_jev, 'resolve_profile_question', uncertain)
    monkeypatch.setattr(job_browser_jev, 'verify_confirmation', uncertain)


def test_start_requires_explicit_submission_authorization():
    for payload in [{'revision': 1}, {'revision': 1, 'authorize_submit': False}]:
        with pytest.raises(ValidationError):
            service.StartRequest.model_validate(payload)


def test_click_cannot_disguise_submission_or_bypass_action_audit():
    click = BrowserAction(kind='click', element='e1', summary='Next')
    with pytest.raises(ValueError, match='different effect'):
        service.validate_audit(click, {'allowed': True, 'effect': 'submit'})
    with pytest.raises(ValueError, match='unsupported'):
        service.validate_audit(click, {'allowed': False, 'reason': 'unsupported fact'})
    # Greenhouse and similar forms use button clicks to open/select custom
    # combobox values. An audited input effect is valid and is not a submit.
    service.validate_audit(click, {'allowed': True, 'effect': 'input'})
    service.validate_audit(click, {'allowed': True, 'effect': 'advance'})
    # Expanding terms, help text, or an accordion is a safe read-only click.
    service.validate_audit(click, {'allowed': True, 'effect': 'read'})


def test_fast_program_accepts_only_distinct_native_input_controls():
    snapshot = {'frames': [{'controls': [
        {'id': 'e0', 'tag': 'input', 'type': 'text', 'disabled': False},
        {'id': 'e1', 'tag': 'select', 'type': 'select-one', 'disabled': False},
        {'id': 'e2', 'tag': 'input', 'type': 'checkbox', 'disabled': False},
        {'id': 'e3', 'tag': 'input', 'type': 'file', 'disabled': False},
        {'id': 'e4', 'tag': 'button', 'type': 'submit', 'disabled': False},
        {'id': 'e5', 'tag': 'input', 'type': 'radio', 'disabled': False},
    ]}]}
    program = BrowserProgram(actions=[
        BrowserAction(kind='fill', element='e0', value='Pranav', summary='First name'),
        BrowserAction(kind='select', element='e1', value='CO', summary='Country'),
        BrowserAction(kind='check', element='e2', checked=True, summary='Agree'),
        BrowserAction(kind='upload', element='e3', summary='Resume'),
    ])
    assert validate_fast_program(program, snapshot) is program
    for unsafe in [
        BrowserAction(kind='submit', element='e4', summary='Submit'),
        BrowserAction(kind='click', element='e4', summary='Continue'),
        BrowserAction(kind='check', element='e5', summary='Radio'),
    ]:
        with pytest.raises(ValueError):
            validate_fast_program(BrowserProgram(actions=[program.actions[0], unsafe]), snapshot)


def test_fast_program_and_controller_allow_at_most_twelve_actions():
    from app.services.job_browser_ai import Decision

    controls = [
        {'id': f'e{index}', 'tag': 'input', 'type': 'text', 'disabled': False}
        for index in range(13)
    ]
    actions = [
        BrowserAction(kind='fill', element=f'e{index}', value=str(index), summary=f'Field {index}')
        for index in range(13)
    ]
    program = BrowserProgram(actions=actions[:12])
    assert len(validate_fast_program(program, {'frames': [{'controls': controls}]}).actions) == 12
    with pytest.raises(ValidationError):
        BrowserProgram(actions=actions)
    decision = Decision(action=actions[0], additional_actions=actions[1:12])
    assert len(decision.additional_actions) == 11
    with pytest.raises(ValidationError):
        Decision(action=actions[0], additional_actions=actions[1:13])


def test_decision_program_uses_safe_batch_and_falls_back_to_first_action():
    snapshot = {'frames': [{'controls': [
        {'id': 'e0', 'tag': 'input', 'type': 'text', 'disabled': False},
        {'id': 'e1', 'tag': 'input', 'type': 'text', 'disabled': False},
        {'id': 'e2', 'tag': 'button', 'type': 'submit', 'disabled': False},
    ]}]}
    decision = {
        'action': {'kind': 'fill', 'element': 'e0', 'value': 'Pranav', 'summary': 'First'},
        'additional_actions': [
            {'kind': 'fill', 'element': 'e1', 'value': 'Modi', 'summary': 'Last'}],
    }
    first, program = service.decision_program(decision, snapshot)
    assert first.element == 'e0' and [item.element for item in program.actions] == ['e0', 'e1']
    decision['additional_actions'] = [
        {'kind': 'submit', 'element': 'e2', 'summary': 'Submit'}]
    first, program = service.decision_program(decision, snapshot)
    assert first.element == 'e0' and program is None


def test_observed_radio_check_uses_click_but_checkbox_keeps_native_check():
    radio = BrowserAction(kind='check', element='e1', checked=True, summary='Choose Yes')
    snapshot = {'frames': [{'controls': [
        {'id': 'e1', 'type': 'radio'}, {'id': 'e2', 'type': 'checkbox'},
    ]}]}
    assert service.normalize_observed_action(radio, snapshot).kind == 'click'
    checkbox = radio.model_copy(update={'element': 'e2'})
    assert service.normalize_observed_action(checkbox, snapshot).kind == 'check'
    uncheck = checkbox.model_copy(update={'checked': False})
    assert service.normalize_observed_action(uncheck, snapshot).kind == 'check'


@pytest.mark.asyncio
async def test_hidden_native_checkbox_with_visible_label_uses_forced_check():
    browser = BrowserSession()
    handle = AsyncMock()
    browser.snapshot = {'frames': [{'controls': [{
        'id': 'e0', 'tag': 'input', 'type': 'checkbox',
        'disabled': False, 'proxy_visible': True,
    }]}]}
    browser.elements = {'e0': handle}

    await browser.execute(
        BrowserAction(kind='check', element='e0', checked=True,
                      summary='Agree to the terms'),
        None,
    )

    handle.set_checked.assert_awaited_once_with(True, force=True)


@pytest.mark.asyncio
async def test_keyboard_recovery_is_limited_to_safe_combobox_keys():
    browser = BrowserSession()
    handle = AsyncMock()
    browser.snapshot = {'frames': [{'controls': [
        {'id': 'e0', 'type': 'text', 'role': 'combobox'},
        {'id': 'e1', 'type': 'text', 'role': None},
    ]}]}
    browser.elements = {'e0': handle, 'e1': handle}
    action = BrowserAction(kind='press', element='e0', value='Enter', summary='Commit India')
    service.validate_audit(action, {'allowed': True, 'effect': 'input'})
    await browser.execute(action, None)
    handle.press.assert_awaited_once_with('Enter')
    with pytest.raises(ValueError, match='safe keys'):
        await browser.execute(action.model_copy(update={'element': 'e1'}), None)
    with pytest.raises(ValueError, match='safe keys'):
        await browser.execute(action.model_copy(update={'value': 'Control+A'}), None)


@pytest.mark.asyncio
async def test_anchor_click_timeout_follows_observed_public_href(monkeypatch):
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    browser = BrowserSession()
    handle = AsyncMock()
    handle.click.side_effect = PlaywrightTimeoutError('text layer intercepts pointer events')
    browser.page = SimpleNamespace(
        url='https://apply.example/jobs', goto=AsyncMock())
    browser.snapshot = {'frames': [{'controls': [{
        'id': 'e12', 'tag': 'a', 'type': '', 'role': None,
        'href': '/jobs/exact-role', 'disabled': False,
    }]}]}
    browser.elements = {'e12': handle}
    public = AsyncMock()
    monkeypatch.setattr(job_browser_tools, 'public_url', public)
    await browser.execute(BrowserAction(
        kind='click', element='e12', summary='Open exact role'), None)
    public.assert_awaited_once_with('https://apply.example/jobs/exact-role')
    browser.page.goto.assert_awaited_once_with(
        'https://apply.example/jobs/exact-role',
        wait_until='domcontentloaded', timeout=45000)


def test_only_audited_pre_form_navigation_is_source_recoverable():
    state = {
        'interaction_started': True,
        'last_action': {'kind': 'click', 'element': 'e13'},
        'audit': {'allowed': True, 'effect': 'navigation'},
    }
    assert service.recoverable_source_navigation(state) is True
    assert service.recoverable_source_navigation({**state, 'submit_started_at': 'now'}) is False
    assert service.recoverable_source_navigation({**state, 'form_input_completed_at': 'now'}) is False
    assert service.recoverable_source_navigation({**state, 'application_source_url': 'https://jobs.example/1'}) is False
    assert service.recoverable_source_navigation({**state, 'audit': {'allowed': True, 'effect': 'advance'}}) is False


def test_exact_employer_validation_rejection_is_recoverable():
    url = 'https://careers.example/jobs/1/apply'
    state = {
        'submit_started_at': '2026-09-28T14:07:22Z',
        'browser_transport': 'broker',
        'session_available': True,
        'current_url': url,
        'snapshot': {'url': url, 'frames': [{'text':
            'This info is required. You need to add or modify some info before submitting your job application.'}]},
    }
    assert service.recoverable_validation_rejection(state) is True
    assert service.recoverable_validation_rejection({**state, 'confirmation': {'quote': 'Thank you'}}) is False
    assert service.recoverable_validation_rejection({**state, 'snapshot': {'url': url, 'frames': [{'text': 'Application received'}]}}) is False
    visible = service.view(SimpleNamespace(
        state=state, status='submission_uncertain', revision=7, run_id='fixture',
        updated_at=datetime.now(timezone.utc)))
    assert visible['can_resume'] is True
    assert visible['recoverable_validation_rejection'] is True
    assert 'snapshot' not in visible


def test_page_proven_failed_submit_gets_one_deterministic_retry():
    recovered_at = '2026-09-29T03:29:29+00:00'
    url = 'https://apply.example/jobs/1/apply'
    state = {
        'authorized_at': '2026-09-28T18:55:35+00:00',
        'mistaken_submission_recovery': {
            'at': recovered_at, 'evidence_url': url,
            'visible_submit_control': True},
        'force_verified_submit_retry': {'recovery_at': recovered_at},
    }
    snapshot = {'url': url, 'frames': [{'text':
        'Something went wrong. We are working on this, please try again later.',
        'controls': [
            {'id': 'e3', 'type': 'submit', 'label': 'Dismiss', 'disabled': False},
            {'id': 'e9', 'type': 'submit', 'label': 'Submit application', 'disabled': False},
            {'id': 'e10', 'type': 'submit', 'label': 'Cookie settings', 'disabled': False}]}]}
    dismiss = service.verified_failed_submit_retry_action(state, snapshot)
    assert dismiss.kind == 'click' and dismiss.element == 'e3'
    assert service.verified_failed_submit_retry_audit(dismiss)['effect'] == 'input'
    snapshot['frames'][0]['text'] = 'Completed application form'
    action = service.verified_failed_submit_retry_action(state, snapshot)
    assert action.kind == 'submit' and action.element == 'e9'
    assert service.verified_failed_submit_retry_audit(action)['effect'] == 'submit'
    assert service.verified_failed_submit_retry_action({
        **state, 'mistaken_submission_retry_recovery_at': recovered_at}, snapshot) is None


def test_unopened_recovered_source_browser_requires_no_broker_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'ROOT', tmp_path)
    row = type('Row', (), {'run_id': 'fresh'})()
    (tmp_path / row.run_id).mkdir()
    state = {'application_source_url': 'https://jobs.example/1',
             'browser_transport': 'broker'}
    assert service.unopened_recovered_source_browser(row, state) is True
    (tmp_path / row.run_id / 'browser-session.json').write_text('{}')
    assert service.unopened_recovered_source_browser(row, state) is False
    assert service.unopened_recovered_source_browser(row, {**state, 'interaction_started': True}) is False


def test_mailbox_search_requires_read_audit_and_redacts_durable_query():
    action = BrowserAction(kind='email_search', value='Fixture verification', summary='Check inbox')
    service.validate_audit(action, {'allowed': True, 'effect': 'read'})
    with pytest.raises(ValueError, match='different effect'):
        service.validate_audit(action, {'allowed': True, 'effect': 'input'})
    assert service.redact_mailbox_action(action).value == '[redacted mailbox query]'


def test_mailbox_verification_uses_newest_exact_code_and_visible_controls():
    snapshot = {'frames': [{'controls': [
        *[{'id': f'e{i}', 'tag': 'input', 'type': 'text', 'disabled': False}
          for i in range(8)],
        {'id': 'e8', 'tag': 'button', 'type': 'submit', 'disabled': False},
    ]}]}
    result = {'items': [
        {'excerpt': 'Your current application verification code is Ab12Cd34.'},
        {'excerpt': 'An earlier code was Old12345.'},
    ]}
    action = BrowserAction(kind='verification_code', value='Ab12Cd34',
        choices=[f'e{i}' for i in range(8)], element='e8', summary='Verify application')
    assert service.mailbox_verification_value(action, result, snapshot) == 'Ab12Cd34'
    service.validate_audit(action, {'allowed': True, 'effect': 'submit'})
    with pytest.raises(ValueError, match='newest matching email'):
        service.mailbox_verification_value(action.model_copy(update={'value': 'Old12345'}), result, snapshot)
    redacted = service.redact_mailbox_followup(action)
    assert redacted.value == '[redacted mailbox result]'
    assert redacted.choices == [f'e{i}' for i in range(8)]


def test_missing_verification_choices_are_recovered_from_adjacent_controls():
    snapshot = {'frames': [{'controls': [
        {'id': 'e0', 'tag': 'input', 'type': 'text', 'disabled': False},
        {'id': 'e1', 'tag': 'button', 'type': 'button', 'disabled': False},
        *[{'id': f'e{i}', 'tag': 'input', 'type': 'text', 'disabled': False}
          for i in range(2, 10)],
        {'id': 'e10', 'tag': 'button', 'type': 'submit', 'disabled': True},
    ]}]}
    action = BrowserAction(kind='verification_code', value='Ab12Cd34', choices=[],
                           element='e10', summary='Verify application')
    recovered = service.complete_verification_action_shape(action, snapshot)
    assert recovered.choices == [f'e{i}' for i in range(2, 10)]


def test_verification_button_may_start_disabled_until_code_is_filled():
    snapshot = {'frames': [{'controls': [
        {'id': 'e0', 'tag': 'input', 'type': 'text', 'disabled': False},
        {'id': 'e1', 'tag': 'button', 'type': 'submit', 'disabled': True},
    ]}]}
    result = {'items': [{'excerpt': 'Current code: Ab12Cd34'}]}
    action = BrowserAction(kind='verification_code', value='Ab12Cd34',
                           choices=['e0'], element='e1', summary='Verify application')
    assert service.mailbox_verification_value(action, result, snapshot) == 'Ab12Cd34'


def test_missing_verification_choices_are_not_guessed_across_other_controls():
    snapshot = {'frames': [{'controls': [
        {'id': 'e0', 'tag': 'input', 'type': 'text', 'disabled': False},
        {'id': 'e1', 'tag': 'button', 'type': 'button', 'disabled': False},
        {'id': 'e2', 'tag': 'button', 'type': 'submit', 'disabled': False},
    ]}]}
    action = BrowserAction(kind='verification_code', value='Ab12Cd34', choices=[],
                           element='e2', summary='Verify application')
    assert service.complete_verification_action_shape(action, snapshot).choices == []


@pytest.mark.asyncio
async def test_application_mail_search_falls_back_to_verified_employer_name(monkeypatch):
    search = AsyncMock(side_effect=[
        {'matched': 0, 'items': []},
        {'matched': 1, 'items': [{'excerpt': 'Current code'}]},
    ])
    monkeypatch.setattr(service, 'search_zoho_inbox', search)
    result = await service.search_current_application_mail(
        service.MailboxSearchRequest(query='Elite Technology Technical Sales Engineer'),
        {'posting': {'firm_name': 'Elite Technology'}})
    assert result['matched'] == 1 and result['employer_fallback_used'] is True
    assert search.await_args_list[1].args[0].query == 'Elite Technology'


def test_email_verification_controls_survive_new_observation_ids_only_when_structure_matches():
    original = {'frames': [{'controls': [
        {'id': 'e4', 'tag': 'input', 'type': 'text', 'role': None,
         'label': 'Code', 'required': True},
    ]}]}
    descriptor = service.verification_control_descriptor(original, 'e4')
    refreshed = {'frames': [{'controls': [
        {'id': 'e9', 'tag': 'input', 'type': 'text', 'role': None,
         'label': 'Code', 'required': True, 'value': '123456'},
    ]}]}
    assert service.resolve_verification_control(refreshed, descriptor)['id'] == 'e9'
    refreshed['frames'][0]['controls'][0]['type'] = 'password'
    with pytest.raises(ValueError, match='form changed'):
        service.resolve_verification_control(refreshed, descriptor)


@pytest.mark.asyncio
async def test_browser_rejects_unobserved_navigation_and_password_entry():
    browser = BrowserSession()
    browser.snapshot = {'frames': [{'controls': [{'id': 'e0', 'type': 'password'}]}]}
    with pytest.raises(ValueError, match='observed'):
        await browser.execute(BrowserAction(kind='goto', url='https://attacker.invalid', summary='Open'), None)
    with pytest.raises(ValueError, match='Password'):
        await browser.execute(BrowserAction(kind='fill', element='e0', value='secret', summary='Fill'), None)


@pytest_asyncio.fixture
async def isolated_store(monkeypatch, tmp_path):
    if os.getenv('JOB_BROWSER_DB_TESTS') != '1':
        pytest.skip('Requires explicitly enabled isolated PostgreSQL schema and local Chromium')
    from app.db import async_engine as configured
    from sqlalchemy.pool import NullPool
    admin = create_async_engine(configured.url, poolclass=NullPool)
    schema = 'browser_test_' + uuid4().hex
    async with admin.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(configured.url, connect_args={'server_settings': {'search_path': schema}})
    monkeypatch.setattr(core, 'async_engine', engine)
    monkeypatch.setattr(core, 'AsyncSessionLocal', async_sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr(core, '_ready', False)
    monkeypatch.setattr(service, 'ROOT', tmp_path)
    monkeypatch.setattr(service, '_sessions', {})
    await core.ensure_tables()
    try:
        yield tmp_path
    finally:
        for browser in service._sessions.values():
            await browser.close()
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def seed_run(root, identity='fixture'):
    posting = {'firm_id': 'fixture', 'firm_name': 'Fixture Employer', 'title': 'AI Engineer',
               'source_url': 'https://fixture.invalid/job', 'status': 'active'}
    run_id = uuid4().hex
    directory = root / run_id
    directory.mkdir()
    (directory / 'resume.pdf').write_bytes(b'%PDF-fixture')
    async with core.AsyncSessionLocal() as session:
        session.add(core.JobAgentCandidate(id=identity, posting=posting, status='new', note='', revision=1))
        row = service.BrowserRun(candidate_id=identity, run_id=run_id, revision=1, status='queued',
            state={'posting': posting, 'resume': {'text': 'Applicant Name. AI engineer.',
                   'sha256': hashlib.sha256(b'%PDF-fixture').hexdigest()}, 'preferences': {},
                   'authorized_at': core.now().isoformat(), 'answers': [], 'steps': 0})
        session.add(row)
        await session.commit()
        return row


async def load_run(identity='fixture'):
    async with core.AsyncSessionLocal() as session:
        return await session.get(service.BrowserRun, identity)


@pytest.mark.asyncio
async def test_real_browser_asks_resumes_uploads_submits_once(isolated_store, monkeypatch):
    from playwright.async_api import async_playwright
    row = await seed_run(isolated_store)
    browser = BrowserSession()
    browser.engine = await async_playwright().start()
    browser.browser = await browser.engine.chromium.launch()
    browser.context = await browser.browser.new_context()
    browser.page = await browser.context.new_page()
    await browser.page.set_content('''<h1>Fixture Employer — AI Engineer</h1>
      <form onsubmit="event.preventDefault(); window.submits=(window.submits||0)+1;
      document.body.innerHTML='<h1>Fixture Employer — AI Engineer</h1><p>Application received successfully.</p>'">
      <label>Name<input name="name" required></label>
      <label>Availability<input name="availability" required></label>
      <label>Resume<input type="file" required></label><button type="submit">Submit application</button></form>''')
    service._sessions['fixture'] = browser
    async def controller(mode, state, **extra):
        if mode == 'audit_action':
            kind = extra['proposed_action']['kind']
            return {'allowed': True, 'effect': 'submit' if kind == 'submit' else 'input', 'reason': 'Fixture facts'}, {}
        if mode == 'verify_confirmation':
            return {'confirmed': True, 'reason': 'Exact role confirmation'}, {}
        controls = state['snapshot']['frames'][0]['controls']
        def control(label):
            return next(c for c in controls if c['label'] == label)
        if state.get('submit_started_at'):
            return {'action': {'kind': 'confirmed', 'summary': 'Submitted', 'evidence': 'Application received successfully.'}}, {}
        if not state['answers']:
            return {'action': {'kind': 'ask', 'summary': 'Availability needed', 'question': 'When can you start?', 'choices': ['Immediately']}}, {}
        if not control('Name')['value']:
            action = {'kind': 'fill', 'element': control('Name')['id'], 'value': 'Applicant Name'}
        elif not control('Availability')['value']:
            action = {'kind': 'fill', 'element': control('Availability')['id'], 'value': state['answers'][0]['answer']}
        elif not control('Resume')['value']:
            action = {'kind': 'upload', 'element': control('Resume')['id']}
        else:
            action = {'kind': 'submit', 'element': control('Submit application')['id']}
        return {'action': dict(action, summary='Fixture action')}, {}
    monkeypatch.setattr(service, 'model_decision', controller)
    await service.step(row)
    waiting = await service.get('fixture')
    assert waiting['status'] == 'waiting_for_answer'
    # A stale answer cannot accidentally resume a different question.
    with pytest.raises(ValueError, match='progressed'):
        await service.control('fixture', service.ControlRequest(revision=1, action='answer', question_id='stale', answer='Now'))
    await service.control('fixture', service.ControlRequest(revision=waiting['revision'], action='answer',
        question_id=waiting['question']['id'], answer='Immediately'))
    for _ in range(5):
        await service.step(await load_run())
    completed = await service.get('fixture')
    assert completed['status'] == 'submitted'
    assert completed['confirmation']['quote'] == 'Application received successfully.'
    assert len([e for e in completed['events'] if e['kind'] == 'submit']) == 1
    assert 'fixture' not in service._sessions
    with pytest.raises(ValueError, match='cannot be restarted'):
        await service.control('fixture', service.ControlRequest(revision=completed['revision'], action='resume'))


@pytest.mark.asyncio
async def test_restart_never_requeues_possible_submission(isolated_store):
    row = await seed_run(isolated_store)
    await service.checkpoint('fixture', row.revision, status='running', interaction_started=True)
    await service.recover()
    state = await service.get('fixture')
    assert state['status'] == 'submission_uncertain'
    with pytest.raises(ValueError, match='cannot be restarted'):
        await service.control('fixture', service.ControlRequest(revision=state['revision'], action='resume'))


@pytest.mark.asyncio
async def test_interrupted_audited_input_can_resume_preserved_page(isolated_store):
    row = await seed_run(isolated_store)
    row = await service.checkpoint('fixture', row.revision, status='submission_uncertain',
        interaction_started=True, browser_transport='broker', session_available=True,
        error='Browser service request failed; inspect the saved page before retrying.',
        last_action={'kind':'check', 'element':'e17', 'checked':True},
        audit={'allowed':True, 'effect':'input', 'reason':'Custom radio field.',
               'recovery':'none', 'repair_hint':''})
    visible = service.view(row)
    assert visible['can_resume'] is True
    assert visible['recoverable_input_interruption'] is True
    resumed = await service.control('fixture', service.ControlRequest(
        revision=row.revision, action='resume'))
    assert resumed['status'] == 'queued'
    assert resumed['interaction_started'] is False
    assert resumed['interrupted_action_recovery']['action']['kind'] == 'check'
    assert 'use a click action' in resumed['audit_feedback']
    current = await service.get('fixture')
    assert any(event['kind'] == 'input_recovered' for event in current['events'])


@pytest.mark.asyncio
async def test_resume_clears_repeat_guard_for_fresh_page_inspection(isolated_store):
    row = await seed_run(isolated_store)
    async with core.AsyncSessionLocal() as session:
        saved = await session.get(service.BrowserRun, row.candidate_id, with_for_update=True)
        saved.status = 'blocked'
        saved.state = {
            **saved.state,
            'error': 'The same action is repeating without page progress. Review the page before resuming.',
            'action_signature': 'stale-signature',
            'repeat_count': 2,
            'segment_steps': 4,
        }
        saved.revision += 1
        await session.commit()
        revision = saved.revision

    resumed = await service.control('fixture', service.ControlRequest(
        revision=revision, action='resume'))

    assert resumed['status'] == 'queued'
    assert resumed['action_signature'] is None
    assert resumed['repeat_count'] == 0
    assert resumed['segment_steps'] == 0


@pytest.mark.asyncio
async def test_interrupted_pre_form_navigation_resumes_through_source_recovery(isolated_store):
    row = await seed_run(isolated_store)
    row = await service.checkpoint('fixture', row.revision, status='submission_uncertain',
        interaction_started=True, browser_transport='broker', session_available=True,
        current_url='https://board.example/jobs/1',
        last_action={'kind':'click', 'element':'e13', 'summary':'Open application'},
        audit={'allowed':True, 'effect':'navigation', 'reason':'Opens the application.',
               'recovery':'none', 'repair_hint':''})
    visible = service.view(row)
    assert visible['can_resume'] is True
    assert visible['recoverable_source_navigation'] is True
    resumed = await service.control('fixture', service.ControlRequest(
        revision=row.revision, action='resume'))
    assert resumed['status'] == 'queued'
    assert resumed['interaction_started'] is False
    assert resumed['source_recovery']['status'] == 'pending'
    assert 'official employer or ATS' in resumed['stage']


@pytest.mark.asyncio
async def test_third_party_login_wall_requests_official_source_recovery(isolated_store, monkeypatch):
    row = await seed_run(isolated_store)
    browser = AsyncMock()
    browser.observe.return_value = {
        'url': 'https://social.example/jobs/123',
        'title': 'Sign in',
        'frames': [{'text': 'Sign in to continue your application', 'controls': []}],
    }
    service._sessions['fixture'] = browser

    async def controller(mode, *_args, **_kwargs):
        assert mode == 'decide'
        return {
            'action': {
                'kind': 'official_source',
                'summary': 'The third-party listing requires sign-in.',
                'evidence': 'Sign in to continue your application',
            },
            'additional_actions': [],
        }, {}

    monkeypatch.setattr(service, 'model_decision', controller)
    await service.step(row)
    saved = await load_run('fixture')
    assert saved.status == 'queued'
    assert saved.state['source_recovery']['status'] == 'pending'
    assert saved.state['source_recovery']['failed_url'] == 'https://social.example/jobs/123'
    browser.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_interrupted_navigation_inside_verified_portal_reinspects_preserved_page(isolated_store):
    row = await seed_run(isolated_store)
    row = await service.checkpoint('fixture', row.revision, status='submission_uncertain',
        interaction_started=True, browser_transport='broker', session_available=True,
        application_source_url='https://apply.example/jobs',
        form_input_completed_at='2026-09-29T02:27:44+00:00',
        current_url='https://apply.example/jobs',
        last_action={'kind':'click', 'element':'e12', 'summary':'Open exact role'},
        audit={'allowed':True, 'effect':'navigation', 'reason':'Opens the exact role.',
               'recovery':'none', 'repair_hint':''})
    visible = service.view(row)
    assert visible['can_resume'] is True
    assert visible['recoverable_navigation_interruption'] is True
    assert visible['recoverable_source_navigation'] is False
    resumed = await service.control('fixture', service.ControlRequest(
        revision=row.revision, action='resume'))
    assert resumed['status'] == 'queued'
    assert resumed['interaction_started'] is False
    assert resumed['stage'] == 'Inspecting the page reached by the last navigation'
    assert resumed['navigation_interruption_recovery']['action']['element'] == 'e12'


@pytest.mark.asyncio
async def test_verified_source_with_unopened_new_browser_resumes_by_creating_it(isolated_store):
    row = await seed_run(isolated_store)
    row = await service.checkpoint('fixture', row.revision, status='blocked',
        application_source_url='https://jobs.fixture.example/roles/ai-engineer',
        application_source={'url':'https://jobs.fixture.example/roles/ai-engineer'},
        browser_transport='broker', browser_session_status='lost',
        error='The original browser session is gone.')
    assert not (isolated_store / row.run_id / 'browser-session.json').exists()
    resumed = await service.control('fixture', service.ControlRequest(
        revision=row.revision, action='resume'))
    assert resumed['status'] == 'queued'
    assert resumed['browser_transport'] is None
    assert resumed['stage'] == 'Opening the verified official application page'


@pytest.mark.asyncio
@pytest.mark.parametrize('action,audit', [
    ({'kind':'submit', 'element':'e9'}, {'allowed':True, 'effect':'submit'}),
    ({'kind':'click', 'element':'e9'}, {'allowed':True, 'effect':'advance'}),
    ({'kind':'select', 'element':'e7'}, {'allowed':False, 'effect':'input'}),
])
async def test_interrupted_non_input_or_rejected_action_stays_locked(isolated_store, action, audit):
    row = await seed_run(isolated_store)
    row = await service.checkpoint('fixture', row.revision, status='submission_uncertain',
        interaction_started=True, browser_transport='broker', session_available=True,
        last_action=action, audit={**audit, 'reason':'Fixture', 'recovery':'stop', 'repair_hint':''})
    visible = service.view(row)
    assert visible['can_resume'] is False
    assert visible['recoverable_input_interruption'] is False
    with pytest.raises(ValueError, match='cannot be restarted'):
        await service.control('fixture', service.ControlRequest(
            revision=row.revision, action='resume'))


@pytest.mark.asyncio
async def test_human_supplied_challenge_code_is_used_once_and_never_persisted(isolated_store):
    row = await seed_run(isolated_store)
    row = await service.checkpoint('fixture', row.revision, status='submission_uncertain',
        browser_transport='broker', session_available=True,
        submit_started_at='2026-09-26T14:22:34Z')
    browser = AsyncMock()
    values = [''] * 8
    def challenge():
        return {'url':'https://fixture.invalid/job', 'frames':[{'text':
            "A verification code was sent to applicant@example.com. To submit your application, enter the 8-character code to confirm you're a human.",
            'controls':[{'id':f'e{index + 1}','tag':'input','type':'text',
                         'label':'Security code' if index == 0 else '', 'disabled':False,
                         'value':value} for index, value in enumerate(values)] +
                       [{'id':'e9','tag':'button','type':'submit','label':'Submit application',
                         'disabled':any(not value for value in values)}]}]}
    async def observe(*_):
        return challenge()
    async def execute(action, _resume):
        if action.kind == 'fill':
            values[int(action.element[1:]) - 1] = action.value
    browser.observe.side_effect = observe
    browser.execute.side_effect = execute
    service._sessions['fixture'] = browser
    completed = await service.control('fixture', service.ControlRequest(
        revision=row.revision, action='challenge', answer='Ab12Cd34', remember=False))
    assert completed['status'] == 'verifying'
    assert completed['human_verification_click_completed_at']
    assert browser.execute.await_count == 9
    actions = [call.args[0] for call in browser.execute.await_args_list]
    fills, submit = actions[:-1], actions[-1]
    assert ''.join(action.value for action in fills) == 'Ab12Cd34'
    assert all(action.kind == 'fill' and len(action.value) == 1 for action in fills)
    assert submit.kind == 'submit' and submit.value == ''
    saved = await load_run()
    assert 'Ab12Cd34' not in str(saved.state)
    assert 'Ab12Cd34' not in str((await service.get('fixture'))['events'])


@pytest.mark.asyncio
@pytest.mark.parametrize('rejection_message', ['Invalid security code', 'Incorrect security code'])
async def test_rejected_challenge_code_can_be_retried_without_claiming_submission(
        isolated_store, rejection_message):
    row = await seed_run(isolated_store)
    row = await service.checkpoint('fixture', row.revision, status='submission_uncertain',
        browser_transport='broker', session_available=True,
        submit_started_at='2026-09-26T14:22:34Z',
        human_verification_click_completed_at='2026-09-26T14:41:56Z')
    values = [''] * 8
    clicked = False
    browser = AsyncMock()
    def challenge():
        text = ("A verification code was sent to applicant@example.com. To submit your application, "
                "enter the 8-character code to confirm you're a human.")
        if clicked:
            text += f"\n{rejection_message}"
        return {'url':'https://fixture.invalid/job', 'frames':[{'text':text,
            'controls':[{'id':f'e{index + 1}','tag':'input','type':'text',
                         'label':'Security code' if index == 0 else '', 'disabled':False,
                         'value':value} for index, value in enumerate(values)] +
                       [{'id':'e9','tag':'button','type':'submit','label':'Submit application',
                         'disabled':any(not value for value in values)}]}]}
    async def observe(*_):
        return challenge()
    async def execute(action, _resume):
        nonlocal clicked
        if action.kind == 'fill':
            values[int(action.element[1:]) - 1] = action.value
        elif action.kind == 'submit':
            clicked = True
    browser.observe.side_effect = observe
    browser.execute.side_effect = execute
    service._sessions['fixture'] = browser
    result = await service.control('fixture', service.ControlRequest(
        revision=row.revision, action='challenge', answer='Ab12Cd34', remember=False))
    assert result['status'] == 'submission_uncertain'
    assert result['stage'] == 'Verification code rejected'
    assert 'latest code' in result['error']
    saved = await load_run()
    assert 'Ab12Cd34' not in str(saved.state)
    assert service.view(saved)['can_restart'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('rejection_message', ['Invalid security code', 'Incorrect security code'])
async def test_explicitly_rejected_code_allows_clean_restart(isolated_store, rejection_message):
    row = await seed_run(isolated_store)
    controls = [{'id':f'e{index + 1}','tag':'input','type':'text',
                 'label':'Security code' if index == 0 else '', 'disabled':False,
                 'value':value} for index, value in enumerate('Ab12Cd34')]
    controls.append({'id':'e9','tag':'button','type':'submit','label':'Submit application',
                     'disabled':rejection_message == 'Invalid security code'})
    snapshot = {'url':'https://fixture.invalid/job', 'frames':[{
        'text':("A verification code was sent to applicant@example.com. To submit your application, "
                f"enter the 8-character code to confirm you're a human.\n{rejection_message}"),
        'controls':controls}]}
    row = await service.checkpoint('fixture', row.revision, status='submission_uncertain',
        browser_transport='broker', session_available=True,
        submit_started_at='2026-09-26T14:22:34Z', snapshot=snapshot)
    assert service.view(row)['can_restart'] is True
    browser = AsyncMock()
    service._sessions['fixture'] = browser
    restarted = await service.control('fixture', service.ControlRequest(
        revision=row.revision, action='restart'))
    assert restarted['status'] == 'queued'
    assert restarted['run_id'] != row.run_id
    assert not restarted.get('submit_started_at')
    browser.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_challenge_action_requires_exact_visible_human_verification(isolated_store):
    row = await seed_run(isolated_store)
    row = await service.checkpoint('fixture', row.revision, status='submission_uncertain',
        browser_transport='broker', session_available=True,
        submit_started_at='2026-09-26T14:22:34Z')
    browser = AsyncMock()
    browser.observe.return_value = {'url':'https://fixture.invalid/job', 'frames':[{
        'text':'ordinary application form',
        'controls':[{'id':'e1','tag':'input','type':'text','label':'Security code','disabled':False},
                    {'id':'e2','tag':'button','type':'submit','label':'Submit application','disabled':False}]}]}
    service._sessions['fixture'] = browser
    with pytest.raises(ValueError, match='no longer shows'):
        await service.control('fixture', service.ControlRequest(
            revision=row.revision, action='challenge', answer='Ab12Cd34', remember=False))
    browser.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_pause_invalidates_inflight_model_decision(isolated_store):
    row = await seed_run(isolated_store)
    await service.control('fixture', service.ControlRequest(revision=row.revision, action='pause'))
    assert await service.checkpoint('fixture', row.revision, status='running', stage='Stale action') is None
    assert (await service.get('fixture'))['status'] == 'paused'


@pytest.mark.asyncio
async def test_false_confirmation_is_not_accepted(isolated_store, monkeypatch):
    row = await seed_run(isolated_store)
    fake = AsyncMock()
    fake.observe.return_value = {'url': 'https://fixture.invalid/job', 'frames': [{'text': 'Apply now'}]}
    service._sessions['fixture'] = fake
    monkeypatch.setattr(service, 'model_decision', AsyncMock(return_value=(
        {'action': {'kind': 'confirmed', 'summary': 'Done', 'evidence': 'Application received'}}, {})))
    with pytest.raises(ValueError, match='submission attempt'):
        await service.step(row)
    assert (await service.get('fixture'))['status'] != 'submitted'


@pytest.mark.asyncio
async def test_missing_confirmation_quote_is_recovered_from_visible_receipt(isolated_store, monkeypatch):
    row = await seed_run(isolated_store)
    row = await service.checkpoint(
        'fixture', row.revision, submit_started_at='2026-09-27T11:00:00+00:00')
    browser = AsyncMock()
    browser.observe.return_value = {
        'url': 'https://fixture.invalid/confirmation',
        'frames': [{'text': 'Thank you for applying.\nYour application has been received.',
                    'controls': []}],
    }
    service._sessions['fixture'] = browser

    async def controller(mode, state, **extra):
        if mode == 'decide':
            return {'action': {'kind': 'confirmed', 'summary': 'Application received',
                               'evidence': ''}}, {}
        if mode == 'extract_confirmation':
            return {'confirmed': True, 'exact_quote': 'Your application has been received.',
                    'reason': 'Visible employer receipt.'}, {'model': 'extractor'}
        if mode == 'verify_confirmation':
            return {'confirmed': True, 'reason': 'Exact visible receipt.'}, {'model': 'verifier'}
        raise AssertionError(mode)

    monkeypatch.setattr(service, 'model_decision', controller)
    await service.step(row)
    result = await service.get('fixture')
    assert result['status'] == 'submitted'
    assert result['confirmation']['quote'] == 'Your application has been received.'
    browser.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_operator_can_confirm_exact_preserved_receipt_locally(isolated_store):
    row = await seed_run(isolated_store)
    browser = AsyncMock()
    service._sessions['fixture'] = browser
    quote = 'Your application has been received.'
    row = await service.checkpoint(
        'fixture', row.revision, status='submission_uncertain',
        submit_started_at='2026-09-27T11:00:00+00:00',
        current_url='https://fixture.invalid/confirmation',
        snapshot={'url': 'https://fixture.invalid/confirmation',
                  'frames': [{'text': f'Thank you for applying.\n{quote}', 'controls': []}]})
    result = await service.control(
        'fixture', service.ControlRequest(action='confirm_receipt', revision=row.revision,
                                          answer=quote, remember=False))
    assert result['status'] == 'submitted'
    assert result['confirmation']['quote'] == quote
    assert result['confirmation']['model'] is None
    browser.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_is_idempotent_and_email_status_is_unchanged(isolated_store, monkeypatch):
    await seed_run(isolated_store)
    monkeypatch.setattr(processing, 'enqueue_missing', AsyncMock())
    first = await service.start('fixture', service.StartRequest(revision=1, authorize_submit=True))
    second = await service.start('fixture', service.StartRequest(revision=1, authorize_submit=True))
    assert first['run_id'] == second['run_id']


@pytest.mark.asyncio
async def test_release_keeps_pending_question_answerable(isolated_store):
    row = await seed_run(isolated_store)
    row = await service.checkpoint('fixture', row.revision, status='waiting_for_answer',
        question={'id': 'question1', 'text': 'Available date?', 'choices': []})
    released = await service.control('fixture', service.ControlRequest(revision=row.revision, action='release'))
    assert released['status'] == 'waiting_for_answer'
    resumed = await service.control('fixture', service.ControlRequest(revision=released['revision'],
        action='answer', question_id='question1', answer='Monday'))
    assert resumed['status'] == 'queued'


@pytest.mark.asyncio
async def test_submit_timeout_preserves_write_ahead_marker(isolated_store, monkeypatch):
    row = await seed_run(isolated_store)
    browser = AsyncMock()
    browser.observe.return_value = {'url': 'https://fixture.invalid/job', 'frames': [{'text': 'Fixture Employer AI Engineer', 'controls': [{'id': 'e0'}]}]}
    browser.execute.side_effect = TimeoutError('Submit response lost')
    service._sessions['fixture'] = browser
    async def controller(mode, state, **extra):
        if mode == 'audit_action':
            return {'allowed': True, 'effect': 'submit', 'reason': 'Ready'}, {}
        return {'action': {'kind': 'submit', 'element': 'e0', 'summary': 'Submit application'}}, {}
    monkeypatch.setattr(service, 'model_decision', controller)
    with pytest.raises(TimeoutError):
        await service.step(row)
    saved = await load_run()
    assert saved.state['submit_started_at']
    assert saved.state['interaction_started']
    await service.recover()
    assert (await service.get('fixture'))['status'] == 'submission_uncertain'
    assert browser.execute.await_count == 1


@pytest.mark.asyncio
async def test_fresh_start_snapshots_resume_and_preserves_email_channel(isolated_store, monkeypatch):
    source_pdf = isolated_store / 'category.pdf'
    source_pdf.write_bytes(b'%PDF-category-fixture')
    config = core.JobAgentConfig().model_dump()
    config['resume_categories'][0]['resume_path'] = str(source_pdf)
    posting = {'firm_id': 'fixture', 'firm_name': 'Fixture Employer', 'title': 'Engineer',
               'source_url': 'https://fixture.invalid/job', 'status': 'active'}
    async with core.AsyncSessionLocal() as session:
        session.add(core.JobAgentState(id='default', config=config, revision=1))
        session.add(core.JobAgentCandidate(id='fresh', posting=posting))
        session.add(processing.JobProcessing(candidate_id='fresh', revision=5,
            classification_status='classified', classification={
                'category_id': config['resume_categories'][0]['id'], 'source':'operator',
                'job_key': processing.job_key(posting)},
            application_status='sent_verified', application={'recipient': {'email':'fixture@example.com'}}))
        await session.commit()
    monkeypatch.setattr(processing, 'enqueue_missing', AsyncMock())
    monkeypatch.setattr(processing, 'inspect_resume', lambda _: {'path':str(source_pdf),
        'filename':source_pdf.name, 'text':'Fixture Applicant', 'sha256':hashlib.sha256(source_pdf.read_bytes()).hexdigest()})
    monkeypatch.setattr(service, 'resolve_resume', lambda _: source_pdf)
    with pytest.raises(ValueError, match='changed'):
        await service.start('fresh', service.StartRequest(revision=4, authorize_submit=True))
    started = await service.start('fresh', service.StartRequest(revision=5, authorize_submit=True))
    assert started['status'] == 'queued'
    assert not (isolated_store / started['run_id'] / 'resume.pdf').exists()
    async with core.AsyncSessionLocal() as session:
        run = await session.get(service.BrowserRun, 'fresh')
    await service.step(run)
    assert (isolated_store / started['run_id'] / 'resume.pdf').read_bytes() == source_pdf.read_bytes()
    again = await service.start('fresh', service.StartRequest(revision=5, authorize_submit=True))
    assert again['run_id'] == started['run_id']
    async with core.AsyncSessionLocal() as session:
        email = await session.get(processing.JobProcessing, 'fresh')
        assert email.application_status == 'sent_verified'
        assert email.application['recipient']['email'] == 'fixture@example.com'


@pytest.mark.asyncio
async def test_fixed_resume_does_not_require_a_category(isolated_store, monkeypatch):
    source_pdf = isolated_store / 'fixed.pdf'
    source_pdf.write_bytes(b'%PDF-fixed-fixture')
    posting = {'firm_id': 'fixture', 'firm_name': 'Fixture Employer', 'title': 'Principal Engineer',
               'source_url': 'https://fixture.invalid/principal', 'status': 'active'}
    async with core.AsyncSessionLocal() as session:
        session.add(core.JobAgentCandidate(id='fixed', posting=posting))
        session.add(processing.JobProcessing(candidate_id='fixed', revision=2,
            classification_status='classified', classification={
                'source': 'operator', 'resume_override_path': str(source_pdf),
                'job_key': processing.job_key(posting)},
            application_status='not_started', application={}))
        await session.commit()
    monkeypatch.setattr(processing, 'inspect_resume', lambda _: {
        'path': str(source_pdf), 'filename': source_pdf.name, 'text': 'Applicant experience',
        'sha256': hashlib.sha256(source_pdf.read_bytes()).hexdigest(),
    })
    selected = await processing.application_resume('fixed', posting)
    assert selected['resume']['filename'] == 'fixed.pdf'
    assert selected['category_id'] is None


@pytest.mark.asyncio
async def test_resume_can_switch_provider_but_cannot_reset_submission(isolated_store, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-placeholder')
    row=await seed_run(isolated_store)
    row=await service.checkpoint('fixture',row.revision,status='blocked',ai_provider='gateway')
    changed=await service.control('fixture',service.ControlRequest(revision=row.revision,action='resume',provider='openai',model='gpt-6-astra'))
    assert changed['ai_provider']=='openai' and changed['status']=='queued'
    assert changed['openai_model']=='gpt-6-astra'
    row=await load_run()
    row=await service.checkpoint('fixture',row.revision,status='submission_uncertain',submit_started_at=core.now().isoformat())
    with pytest.raises(ValueError,match='cannot be restarted'):
        await service.control('fixture',service.ControlRequest(revision=row.revision,action='resume',provider='gateway'))
    assert (await service.get('fixture'))['ai_provider']=='openai'


@pytest.mark.asyncio
@pytest.mark.parametrize('channel', ['browser', 'prepare', 'send'])
async def test_apply_automatically_classifies_only_selected_job(isolated_store, monkeypatch, channel):
    source = isolated_store / 'selected.pdf'
    source.write_bytes(b'%PDF-test')
    config = core.JobAgentConfig()
    category = config.resume_categories[0]
    category.resume_path = str(source)
    posting = {'title': 'AI Engineer', 'firm_name': 'Example', 'source_url': 'https://example.com/job', 'status': 'active'}
    async with core.AsyncSessionLocal() as session:
        session.add(core.JobAgentState(id='default', config=config.model_dump(), revision=1))
        for identity in ['selected', 'unrelated']:
            session.add(core.JobAgentCandidate(id=identity, posting=posting))
            session.add(processing.JobProcessing(candidate_id=identity, revision=1, classification={}, application={}))
        await session.commit()
    classifier = AsyncMock(return_value=[processing.ClassificationDecision(candidate_id='selected', category_id=category.id,
        confidence=0.99, reason='Responsibilities match', model='jev-test')])
    monkeypatch.setattr(processing, 'classify_with_jev', classifier)
    monkeypatch.setattr(processing, 'inspect_resume', lambda _: {'path':str(source), 'filename':source.name,
        'sha256':hashlib.sha256(source.read_bytes()).hexdigest(), 'text':'Example applicant'})
    monkeypatch.setattr(service, 'resolve_resume', lambda _: source)
    if channel == 'browser':
        first = await service.start('selected', service.StartRequest(revision=1, authorize_submit=True))
        again = await service.start('selected', service.StartRequest(revision=1, authorize_submit=True))
        assert first['run_id'] == again['run_id'] and first['status'] == 'queued'
        assert first['companion_email']['requested'] is True
        email_application = (await processing.detail('selected'))['application']
        assert email_application['status'] == 'queued'
        assert email_application['send_requested'] is True
        assert email_application['authorized_at']
        classifier.assert_not_called()
        async with core.AsyncSessionLocal() as session:
            row = await session.get(service.BrowserRun, 'selected')
        await service.step(row)
        selected = await service.get('selected')
        assert selected['resume_filename'] == source.name and selected['steps'] == 0
        assert selected['session_available'] is False
    else:
        first = await processing.request_application('selected', processing.ApplicationRequest(revision=1, mode=channel))
        again = await processing.request_application('selected', processing.ApplicationRequest(revision=1, mode='send'))
        assert first['application']['run_id'] == again['application']['run_id']
        assert again['application']['send_requested'] == (channel == 'send')
        classifier.assert_not_called()
        selected = await processing.application_resume('selected', posting)
        assert selected['resume']['filename'] == source.name
    assert [j['candidate_id'] for j in classifier.call_args.args[0]] == ['selected']
    assert (await processing.detail('unrelated'))['classification']['status'] == 'pending'
    # A subsequent lookup reuses the result without another model call.
    await processing.application_resume('selected', posting)
    assert classifier.await_count == 1


@pytest.mark.asyncio
async def test_concurrent_email_and_browser_resume_selection_share_one_classification(isolated_store, monkeypatch):
    source = isolated_store / 'shared.pdf'
    source.write_bytes(b'%PDF-test')
    config = core.JobAgentConfig()
    category = config.resume_categories[3]
    category.resume_path = str(source)
    posting = {'title': 'Staff Machine Learning Engineer', 'firm_name': 'Example',
               'source_url': 'https://example.com/ml-job', 'status': 'active'}
    async with core.AsyncSessionLocal() as session:
        session.add(core.JobAgentState(id='default', config=config.model_dump(), revision=1))
        session.add(core.JobAgentCandidate(id='concurrent', posting=posting))
        session.add(processing.JobProcessing(candidate_id='concurrent', revision=1,
            classification={}, application={}))
        await session.commit()
    classifier_started = asyncio.Event()
    release_classifier = asyncio.Event()

    async def classify(jobs, _categories):
        classifier_started.set()
        await release_classifier.wait()
        return [processing.ClassificationDecision(candidate_id=jobs[0]['candidate_id'],
            category_id=category.id, confidence=0.98, reason='Machine learning responsibilities match',
            model='jev-test')]

    classifier = AsyncMock(side_effect=classify)
    monkeypatch.setattr(processing, 'classify_with_jev', classifier)
    monkeypatch.setattr(processing, 'inspect_resume', lambda _: {'path':str(source),
        'filename':source.name, 'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'text':'Example applicant'})
    first = asyncio.create_task(processing.application_resume('concurrent', posting))
    await classifier_started.wait()
    second = asyncio.create_task(processing.application_resume('concurrent', posting))
    await asyncio.sleep(0.05)
    release_classifier.set()
    one, two = await asyncio.gather(first, second)

    assert one['category_id'] == two['category_id'] == category.id
    assert one['resume']['filename'] == two['resume']['filename'] == source.name
    assert classifier.await_count == 1
    assert (await processing.detail('concurrent'))['classification']['status'] == 'classified'


@pytest.mark.asyncio
async def test_explicit_resume_category_without_pdf_needs_help(isolated_store, monkeypatch):
    posting = {'title':'Engineer', 'source_url':'https://example.com/job'}
    config = core.JobAgentConfig()
    config.resume_categories[0].resume_path = ''
    async with core.AsyncSessionLocal() as session:
        session.add(core.JobAgentState(id='default', config=config.model_dump(), revision=1))
        session.add(core.JobAgentCandidate(id='manual', posting=posting))
        session.add(processing.JobProcessing(candidate_id='manual', revision=1, classification_status='classified',
            classification={'source':'operator', 'category_id':config.resume_categories[0].id, 'job_key':processing.job_key(posting)}))
        await session.commit()
    classifier = AsyncMock()
    monkeypatch.setattr(processing, 'classify_with_jev', classifier)
    with pytest.raises(ValueError, match='selected category'):
        await processing.application_resume('manual', posting)
    classifier.assert_not_called()


@pytest.mark.asyncio
async def test_resume_matching_failure_stops_before_opening_browser(isolated_store, monkeypatch):
    posting = {'title':'Engineer', 'source_url':'https://example.com/job', 'status':'active'}
    async with core.AsyncSessionLocal() as session:
        session.add(core.JobAgentCandidate(id='failure', posting=posting))
        session.add(processing.JobProcessing(candidate_id='failure', revision=1, classification={}, application={}))
        await session.commit()
    monkeypatch.setattr(processing, 'classify_with_jev', AsyncMock(side_effect=RuntimeError('offline')))
    browser_open = AsyncMock()
    monkeypatch.setattr(BrowserSession, 'open', browser_open)
    await service.start('failure', service.StartRequest(revision=1, authorize_submit=True))
    async with core.AsyncSessionLocal() as session:
        row = await session.get(service.BrowserRun, 'failure')
    with pytest.raises(ValueError, match='Automatic resume selection needs your help'):
        await service.step(row)
    browser_open.assert_not_called()
    assert (await processing.detail('failure'))['classification']['status'] == 'needs_review'


@pytest.mark.asyncio
async def test_pause_during_resume_matching_prevents_browser_continuation(isolated_store, monkeypatch):
    source = isolated_store / 'pause.pdf'
    source.write_bytes(b'%PDF-test')
    posting = {'title':'Engineer', 'source_url':'https://example.com/job'}
    async with core.AsyncSessionLocal() as session:
        session.add(core.JobAgentCandidate(id='pause', posting=posting))
        session.add(processing.JobProcessing(candidate_id='pause', revision=1, classification={}, application={}))
        await session.commit()
    async def select_resume(identity, posting):
        current = await service.get(identity)
        await service.control(identity, service.ControlRequest(revision=current['revision'], action='pause'))
        return {'category_id':'ai_automation', 'resume':{'path':str(source),'filename':source.name}}
    monkeypatch.setattr(processing, 'application_resume', select_resume)
    monkeypatch.setattr(service, 'resolve_resume', lambda _:source)
    await service.start('pause', service.StartRequest(revision=1, authorize_submit=True))
    async with core.AsyncSessionLocal() as session:
        row = await session.get(service.BrowserRun, 'pause')
    await service.step(row)
    paused = await service.get('pause')
    assert paused['status'] == 'paused' and not paused['session_available']
    assert not paused.get('resume_filename')


@pytest.mark.asyncio
async def test_answers_persist_across_applications_and_removal_survives_backfill(isolated_store):
    from app.services import job_applicant_profile as profile
    row=await seed_run(isolated_store)
    row=await service.checkpoint('fixture',row.revision,status='waiting_for_answer',
        question={'id':'q1','text':'Current home address?','choices':[]})
    await service.control('fixture',service.ControlRequest(revision=row.revision,action='answer',
        question_id='q1',answer='Example Street, Bengaluru, India'))
    items=await profile.snapshot('another-application')
    assert len(items)==1 and items[0]['answer']=='Example Street, Bengaluru, India'
    assert items[0]['context']['candidate_id']=='fixture'
    assert (await profile.import_browser_answers())['imported']==0
    await profile.archive(items[0]['id'],profile.ProfileArchive(revision=items[0]['revision']))
    assert (await profile.import_browser_answers())['imported']==0
    assert await profile.snapshot('another-application')==[]
    assert (await load_run()).state['answers'][0]['answer']=='Example Street, Bengaluru, India'


@pytest.mark.asyncio
async def test_profile_private_scope_and_revision_conflicts(isolated_store):
    from app.services import job_applicant_profile as profile
    row=await seed_run(isolated_store)
    row=await service.checkpoint('fixture',row.revision,status='waiting_for_answer',
        question={'id':'q1','text':'Salary for this role?','choices':[]})
    await service.control('fixture',service.ControlRequest(revision=row.revision,action='answer',
        question_id='q1',answer='USD 150,000 annually',remember=False))
    assert await profile.snapshot('other')==[]
    item=(await profile.snapshot('fixture'))[0]
    edited=await profile.save(profile.ProfileSave(id=item['id'],revision=item['revision'],
        question='Salary for US senior AI roles',answer='USD 160,000 annually',scope='role',scope_value='US senior AI roles'))
    assert len(await profile.snapshot('other'))==1
    assert edited['revision']==item['revision']+1
    with pytest.raises(ValueError,match='another window'):
        await profile.save(profile.ProfileSave(id=item['id'],revision=item['revision'],question='Salary',answer='old'))
    with pytest.raises(ValidationError):
        profile.ProfileSave(question='Authorization',answer='Yes',scope='country')


@pytest.mark.asyncio
async def test_known_question_reuses_profile_instead_of_asking(isolated_store, monkeypatch):
    from app.services import job_applicant_profile as profile
    item=await profile.save(profile.ProfileSave(question='Current address',answer='Example Street, Bengaluru, India',scope='global'))
    row=await seed_run(isolated_store)
    browser=AsyncMock()
    browser.observe.return_value={'url':'https://example.com/application','frames':[{'text':'Enter home address','controls':[]}]}
    service._sessions['fixture']=browser
    async def model(mode,state,**extra):
        if mode=='decide':
            return {'action':{'kind':'ask','question':'What is your address?','summary':'Address needed'}},{}
        assert mode=='resolve_question'
        return {'answer':item['answer'],'missing_question':'','citations':[{'id':item['id'],'quote':item['answer']}],'reason':'Same current address'},{}
    monkeypatch.setattr(service,'model_decision',model)
    await service.step(row)
    saved=await load_run()
    assert saved.status=='running' and not saved.state.get('question')
    assert saved.state['answers'][-1]['source']=='profile'
    assert saved.state['answers'][-1]['citations'][0]['revision']==item['revision']
    assert saved.state['profile_history'][0]['items'][0]['id']==item['id']
    assert 'saved_profile' not in service.view(saved)
    browser.execute.assert_not_called()
    assert (await profile.import_browser_answers())['imported']==0


@pytest.mark.asyncio
async def test_profile_resolution_rejects_fabricated_citations(monkeypatch):
    monkeypatch.setattr(service,'model_decision',AsyncMock(return_value=({'answer':'Yes','missing_question':'',
        'citations':[{'id':'known','quote':'Yes'}],'reason':'Authorization'},{})))
    with pytest.raises(ValueError,match='original answer'):
        await service.resolve_saved_question({'saved_profile':[{'id':'known','answer':'No'}]},'Authorized?')

@pytest.mark.asyncio
async def test_clean_restart_archives_attempt_and_keeps_answers(isolated_store):
    row = await seed_run(isolated_store)
    answers = [{'question':'Sponsorship?', 'answer':'No', 'at':'2026-09-25T10:00:00Z'}]
    row = await service.checkpoint('fixture', row.revision, status='blocked', answers=answers,
        snapshot={'frames':[]}, question={'id':'old','text':'Old question','choices':[]}, error='Old error')
    old_id=row.run_id
    browser=AsyncMock()
    service._sessions['fixture']=browser
    restarted=await service.control('fixture',service.ControlRequest(revision=row.revision,action='restart'))
    assert restarted['status']=='queued'
    assert restarted['run_id']!=old_id and restarted['attempt']==2
    assert restarted['answers']==answers and restarted['question'] is None
    assert 'snapshot' not in restarted and 'attempt_history' not in restarted
    saved=await load_run()
    assert saved.state['attempt_history'][0]['state']['error']=='Old error'
    assert (isolated_store/old_id/'resume.pdf').read_bytes()==(isolated_store/saved.run_id/'resume.pdf').read_bytes()
    browser.close.assert_awaited_once()
    assert 'fixture' not in service._sessions
    with pytest.raises(ValueError,match='progressed'):
        await service.control('fixture',service.ControlRequest(revision=row.revision,action='restart'))

@pytest.mark.asyncio
@pytest.mark.parametrize('changes,status',[
    ({'submit_started_at':'2026-09-25'},'submission_uncertain'),
    ({'interaction_started':True},'submission_uncertain'),
    ({'confirmation':{'quote':'Received'}},'submitted'),
    ({},'running'),
])
async def test_clean_restart_rejects_possible_submission_or_active_run(isolated_store,changes,status):
    row=await seed_run(isolated_store)
    row=await service.checkpoint('fixture',row.revision,status=status,**changes)
    assert service.view(row)['can_restart'] is False
    with pytest.raises(ValueError):
        await service.control('fixture',service.ControlRequest(revision=row.revision,action='restart'))

@pytest.mark.asyncio
async def test_legacy_missing_control_is_restartable_only_when_not_dispatched(isolated_store):
    row=await seed_run(isolated_store)
    row=await service.checkpoint('fixture',row.revision,status='submission_uncertain',interaction_started=True,
        error='The selected control is no longer in the current page snapshot.',
        last_action={'kind':'check','element':'e12'},snapshot={'frames':[{'controls':[{'id':'e1'}]}]})
    assert service.view(row)['can_restart'] is True
    await service.control('fixture',service.ControlRequest(revision=row.revision,action='restart'))

@pytest.mark.asyncio
async def test_stale_control_is_rejected_before_write_ahead(isolated_store,monkeypatch):
    row=await seed_run(isolated_store)
    browser=AsyncMock()
    browser.observe.return_value={'url':'https://fixture.invalid/job','frames':[{'text':'Fixture','controls':[]}]}
    service._sessions['fixture']=browser
    async def controller(mode,state,**extra):
        if mode=='audit_action': return {'allowed':True,'effect':'input','reason':'Known answer'},{}
        return {'action':{'kind':'check','element':'missing','summary':'Select No'}},{}
    monkeypatch.setattr(service,'model_decision',controller)
    with pytest.raises(ValueError,match='unavailable form control'):
        await service.step(row)
    saved=await load_run()
    assert not saved.state.get('interaction_started') and not saved.state.get('submit_started_at')
    browser.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_mailbox_search_result_is_transient_before_form_action(isolated_store, monkeypatch):
    row = await seed_run(isolated_store)
    browser = AsyncMock()
    browser.observe.return_value = {'url': 'https://fixture.invalid/job', 'frames': [{
        'text': 'Fixture Employer verification code',
        'controls': [{'id': 'e0', 'type': 'text', 'label': 'Verification code'}],
    }]}
    service._sessions['fixture'] = browser
    secret = 'Ab12Cd34'
    search = AsyncMock(return_value={
        'query': 'Fixture verification', 'mailbox': 'INBOX', 'read_only': True,
        'since_hours': 48, 'matched': 1,
        'items': [{'from_email': 'verify@fixture.invalid', 'subject': 'Verification',
                   'received_at': '2026-09-27T08:00:00+00:00', 'excerpt': f'Code: {secret}'}],
    })
    monkeypatch.setattr(service, 'search_zoho_inbox', search)

    async def controller(mode, state, **extra):
        if mode == 'audit_action':
            kind = extra['proposed_action']['kind']
            return {'allowed': True, 'effect': 'read' if kind == 'email_search' else 'input',
                    'reason': 'Exact application verification.', 'recovery': 'none', 'repair_hint': ''}, {}
        if 'mailbox_search_result' in extra:
            assert secret in extra['mailbox_search_result']['items'][0]['excerpt']
            return {'action': {'kind': 'fill', 'element': 'e0', 'value': secret,
                               'summary': 'Enter the verification code'}}, {}
        return {'action': {'kind': 'email_search', 'value': 'Fixture verification',
                           'summary': 'Check for the application email'}}, {}

    monkeypatch.setattr(service, 'model_decision', controller)
    await service.step(row)

    browser.execute.assert_awaited_once()
    saved = await load_run()
    durable = str(saved.state)
    assert secret not in durable
    assert 'Fixture verification' not in durable
    assert saved.state['mailbox_search_last']['matched'] == 1
    assert saved.state['last_action']['kind'] == 'fill'
    assert saved.state['last_action']['value'] == '[redacted mailbox result]'


@pytest.mark.asyncio
async def test_post_submit_email_code_is_used_once_without_persisting_it(isolated_store, monkeypatch):
    row = await seed_run(isolated_store)
    secret = 'A1B2C3'
    row = await service.checkpoint('fixture', row.revision, status='submission_uncertain',
                                   submit_started_at=core.now().isoformat())
    empty = {'url': 'https://fixture.invalid/verify', 'frames': [{
        'text': 'Fixture Employer email verification',
        'controls': [
            {'id': 'e0', 'tag': 'input', 'type': 'text', 'role': None, 'label': 'Code',
             'required': True, 'disabled': False, 'value': ''},
            {'id': 'e1', 'tag': 'button', 'type': 'submit', 'role': None, 'label': 'Verify',
             'required': False, 'disabled': False, 'value': ''},
        ],
    }]}
    filled = {'url': empty['url'], 'frames': [{
        'text': empty['frames'][0]['text'],
        'controls': [
            {**empty['frames'][0]['controls'][0], 'id': 'e7', 'value': secret},
            {**empty['frames'][0]['controls'][1], 'id': 'e8'},
        ],
    }]}
    browser = AsyncMock()
    browser.observe.side_effect = [empty, filled]
    service._sessions['fixture'] = browser
    monkeypatch.setattr(service, 'search_zoho_inbox', AsyncMock(return_value={
        'query': 'Fixture verification', 'mailbox': 'INBOX', 'read_only': True,
        'since_hours': 48, 'matched': 1,
        'items': [{'from_email': 'verify@fixture.invalid', 'subject': 'Application verification',
                   'received_at': '2026-09-27T08:00:00+00:00', 'excerpt': f'Code: {secret}'}],
    }))

    async def controller(mode, state, **extra):
        if mode == 'audit_action':
            effect = 'read' if extra['proposed_action']['kind'] == 'email_search' else 'submit'
            return {'allowed': True, 'effect': effect, 'reason': 'Current application verification.',
                    'recovery': 'none', 'repair_hint': ''}, {}
        if 'mailbox_search_result' in extra:
            return {'action': {'kind': 'verification_code', 'value': secret,
                'choices': ['e0'], 'element': 'e1', 'summary': 'Verify application'}}, {}
        return {'action': {'kind': 'email_search', 'value': 'Fixture verification',
                           'summary': 'Check the current application email'}}, {}

    monkeypatch.setattr(service, 'model_decision', controller)
    await service.step(row)
    assert [call.args[0].kind for call in browser.execute.await_args_list] == ['fill', 'submit']
    saved = await load_run()
    assert saved.status == 'verifying' and saved.state['interaction_started'] is False
    assert secret not in str(saved.state)
    assert saved.state['last_action']['kind'] == 'verification_code'
    assert saved.state['last_action']['value'] == '[redacted mailbox result]'

@pytest.mark.asyncio
async def test_hidden_iframe_controls_are_not_presented_as_visible(tmp_path):
    from playwright.async_api import async_playwright
    browser=BrowserSession()
    async with async_playwright() as p:
        browser.browser=await p.chromium.launch()
        browser.context=await browser.browser.new_context()
        browser.page=await browser.context.new_page()
        await browser.page.set_content('''<label>Email<input name="email"></label>
            <iframe style="display:none" srcdoc="<button>Verify hidden challenge</button>"></iframe>
            <iframe srcdoc="<button>Visible embedded action</button>"></iframe>''')
        await browser.page.frames[-1].get_by_text('Visible embedded action').wait_for()
        snapshot=await browser.observe(tmp_path/'page.png')
        labels=[c['label'] for f in snapshot['frames'] for c in f.get('controls',[])]
        assert 'Verify hidden challenge' not in labels
        assert 'Visible embedded action' in labels
        assert 'Email' in labels
        await browser.close()

@pytest.mark.asyncio
async def test_rejected_submit_repairs_field_then_submits_once(isolated_store,monkeypatch):
    from playwright.async_api import async_playwright
    row=await seed_run(isolated_store)
    browser=BrowserSession()
    browser.engine=await async_playwright().start()
    browser.browser=await browser.engine.chromium.launch()
    browser.context=await browser.browser.new_context()
    browser.page=await browser.context.new_page()
    await browser.page.set_content('''<h1>Fixture Employer AI Engineer</h1><form onsubmit="event.preventDefault();window.submits=(window.submits||0)+1;document.body.innerHTML='<p>Application received successfully.</p>'"><label>About you<textarea required></textarea></label><button>Submit application</button></form>''')
    service._sessions['fixture']=browser
    async def controller(mode,state,**extra):
        controls=state['snapshot']['frames'][0]['controls']
        if mode=='verify_confirmation':return {'confirmed':True,'reason':'Visible receipt'},{}
        field=next((c for c in controls if c['label']=='About you'),None)
        if mode=='audit_action':
            if extra['proposed_action']['kind']=='submit' and not field['value']:
                return {'allowed':False,'effect':'submit','reason':'Required About you is empty',
                        'recovery':'correct_form','repair_hint':'Fill About you from confirmed resume facts.'},{}
            return {'allowed':True,'effect':'submit' if extra['proposed_action']['kind']=='submit' else 'input','reason':'Valid'},{}
        if state.get('submit_started_at'):
            return {'action':{'kind':'confirmed','summary':'Done','evidence':'Application received successfully.'}},{}
        if state.get('audit_feedback'):
            assert 'About you' in state['audit_feedback']['repair_hint']
            return {'action':{'kind':'fill','element':field['id'],'value':'Applicant Name. AI engineer.','summary':'Correct missing field'}},{}
        button=next(c for c in controls if c['label']=='Submit application')
        return {'action':{'kind':'submit','element':button['id'],'summary':'Submit'}},{}
    monkeypatch.setattr(service,'model_decision',controller)
    await service.step(row)
    repair=await service.get('fixture')
    assert repair['status']=='running' and not repair.get('submit_started_at')
    assert repair['steps']==0 and repair['audit_repair_count']==1
    assert await browser.page.evaluate('window.submits||0')==0
    for _ in range(3): await service.step(await load_run())
    done=await service.get('fixture')
    assert done['status']=='submitted'
    assert len([e for e in done['events'] if e['kind']=='submit'])==1
    assert len([e for e in done['events'] if e['kind']=='audit_repair'])==1

@pytest.mark.asyncio
async def test_repeated_repair_rejections_stop_without_dispatch(isolated_store,monkeypatch):
    row=await seed_run(isolated_store)
    browser=AsyncMock()
    browser.observe.return_value={'url':'https://fixture.invalid','frames':[{'text':'Fixture','controls':[]}]}
    service._sessions['fixture']=browser
    async def controller(mode,state,**extra):
        if mode=='audit_action':return {'allowed':False,'effect':'submit','reason':'Missing field','recovery':'correct_form','repair_hint':'Fill field'},{}
        return {'action':{'kind':'submit','element':'e0','summary':'Submit prematurely'}},{}
    monkeypatch.setattr(service,'model_decision',controller)
    for _ in range(3):await service.step(await load_run())
    saved=await service.get('fixture')
    assert saved['status']=='blocked' and saved['audit_repair_count']==3
    assert not saved.get('submit_started_at') and saved['steps']==0
    browser.execute.assert_not_awaited()

@pytest.mark.asyncio
async def test_nonrepairable_audit_rejection_stays_blocked(isolated_store,monkeypatch):
    row=await seed_run(isolated_store)
    browser=AsyncMock()
    browser.observe.return_value={'url':'https://fixture.invalid','frames':[{'text':'Fixture','controls':[]}]}
    service._sessions['fixture']=browser
    async def controller(mode,state,**extra):
        if mode=='audit_action':return {'allowed':False,'effect':'blocked','reason':'Unsupported authorization claim','recovery':'stop','repair_hint':''},{}
        return {'action':{'kind':'check','element':'e0','summary':'False authorization'}},{}
    monkeypatch.setattr(service,'model_decision',controller)
    await service.step(row)
    saved = await service.get('fixture')
    assert saved['status'] == 'blocked'
    assert 'Unsupported authorization' in saved['error']
    browser.execute.assert_not_awaited()
    assert not (await load_run()).state.get('audit_feedback')

# Shared fixture runs a real, separate browser owner over a private Unix socket.
from tests.test_job_browser_broker import broker


@pytest.mark.asyncio
async def test_worker_recovery_retains_filled_form_and_submission_lock(isolated_store, broker, monkeypatch):
    row = await seed_run(isolated_store)
    async def controller(mode, state, **extra):
        if mode == 'audit_action':
            return {'allowed': True, 'effect': 'submit' if extra['proposed_action']['kind']=='submit' else 'input', 'reason': 'Synthetic fixture'}, {}
        if mode == 'verify_confirmation':
            return {'confirmed': True, 'reason': 'Visible synthetic confirmation'}, {}
        if state.get('submit_started_at'):
            return {'action': {'kind': 'confirmed', 'summary': 'Confirmed', 'evidence': 'Application received'}}, {}
        controls = state['snapshot']['frames'][0]['controls']
        return {'action': {'kind': 'submit', 'element': 'e1', 'summary': 'Submit'} if controls[0]['value'] else
                {'kind': 'fill', 'element': 'e0', 'value': 'Synthetic Applicant', 'summary': 'Name'}}, {}
    monkeypatch.setattr(service, 'model_decision', controller)
    await service.step(row)
    row = await load_run()
    owner = broker[0].state.sessions[row.run_id]
    assert await owner.browser.page.locator('input').input_value() == 'Synthetic Applicant'
    await service._sessions['fixture'].detach()
    service._sessions.clear()  # Model a newly started backend with no in-memory handles.
    await service.recover()
    paused = await service.get('fixture')
    assert paused['status'] == 'paused' and paused['session_available']
    assert paused['browser_session_status'] == 'available'
    assert await owner.browser.page.locator('input').input_value() == 'Synthetic Applicant'
    await service.control('fixture', service.ControlRequest(action='resume', revision=paused['revision']))
    await service.step(await load_run())
    assert await owner.browser.page.evaluate('window.submits') == 1
    service._sessions.clear()
    await service.recover()
    uncertain = await service.get('fixture')
    assert uncertain['status'] == 'submission_uncertain' and uncertain['session_available']
    assert uncertain['can_restart'] is False
    connected = await service.control('fixture', service.ControlRequest(action='reconnect', revision=uncertain['revision']))
    assert connected['status'] == 'submission_uncertain'
    assert await owner.browser.page.evaluate('window.submits') == 1
    await service.control('fixture', service.ControlRequest(action='verify', revision=connected['revision']))
    await service.step(await load_run())
    completed = await service.get('fixture')
    assert completed['status'] == 'submitted'
    assert len([e for e in completed['events'] if e['kind']=='submit']) == 1


@pytest.mark.asyncio
async def test_reconnect_preserves_pending_question_and_lost_browser_never_reopens(isolated_store, broker):
    from app.services.job_browser_client import PersistentBrowserSession
    row = await seed_run(isolated_store)
    browser = PersistentBrowserSession(row.run_id)
    await browser.open('https://fixture.example/job')
    question = {'id':'pending', 'text':'Availability?', 'choices':[]}
    await service.checkpoint('fixture', row.revision, status='waiting_for_answer',
                             browser_transport='broker', question=question)
    await service.recover()
    waiting = await service.get('fixture')
    assert waiting['question'] == question and waiting['status'] == 'waiting_for_answer'
    await browser.close()
    service._sessions.clear()
    await service.recover()
    lost = await service.get('fixture')
    assert lost['browser_session_status']=='lost' and not lost['session_available']
    with pytest.raises(ValueError, match='gone'):
        await service.control('fixture', service.ControlRequest(action='reconnect', revision=lost['revision']))
    assert not broker[0].state.sessions
    assert (await service.get('fixture'))['question'] == question


@pytest.mark.asyncio
async def test_recover_preserves_spam_protection_pause_after_submit(isolated_store):
    row = await seed_run(isolated_store)
    row = await service.checkpoint(
        'fixture', row.revision, status='paused',
        submit_started_at=core.now().isoformat(),
        spam_protection={'detected_at': core.now().isoformat(), 'evidence': 'Spam protection rejected this request'},
        stage='Paused — spam protection',
    )

    await service.recover()
    recovered = await service.get('fixture')

    assert recovered['status'] == 'paused'
    assert recovered['stage'] == 'Paused — spam protection; browser unavailable'
    assert recovered['spam_protection']['evidence'] == 'Spam protection rejected this request'
    assert recovered['can_resume'] is False


@pytest.mark.asyncio
async def test_human_handoff_keeps_browser_and_returns_without_persisting_text(
        isolated_store, broker):
    from app.services.job_browser_client import PersistentBrowserSession
    row = await seed_run(isolated_store)
    browser = PersistentBrowserSession(row.run_id)
    await browser.open('https://fixture.example/job')
    row = await service.checkpoint(
        'fixture', row.revision, status='paused', browser_transport='broker',
        browser_closed=False, session_available=True, stage='Paused')
    lease = await service.start_handoff(
        'fixture', service.HandoffStartRequest(revision=row.revision))
    token = lease.pop('handoff_token')
    assert lease['status'] == 'human_control'
    assert 'human_control_token_sha256' not in lease
    frame = await service.handoff_frame('fixture', token)
    owner = broker[0].state.sessions[row.run_id]
    box = await owner.browser.page.locator('input').bounding_box()
    await service.handoff_action('fixture', token, service.HumanBrowserActionRequest(
        observation_id=frame['observation_id'], action_id=uuid4().hex,
        kind='click', x=box['x'] + 4, y=box['y'] + 4))
    frame = await service.handoff_frame('fixture', token)
    secret_text = 'Transient operator text'
    await service.handoff_action('fixture', token, service.HumanBrowserActionRequest(
        observation_id=frame['observation_id'], action_id=uuid4().hex,
        kind='type', value=secret_text))
    assert await owner.browser.page.locator('input').input_value() == secret_text
    persisted = await load_run()
    assert secret_text not in persisted.state.__repr__()
    finished = await service.finish_handoff(
        'fixture', token, service.HandoffFinishRequest(
            revision=lease['revision'], outcome='resume_agent'))
    assert finished['status'] == 'queued'
    assert (await browser.status())['available'] is True
    with pytest.raises(ValueError, match='expired or was replaced'):
        await service.handoff_frame('fixture', token)
    service._sessions.pop('fixture', None)
    await browser.close()


@pytest.mark.asyncio
async def test_human_possible_submit_returns_to_verification_only(isolated_store, broker):
    from app.services.job_browser_client import PersistentBrowserSession
    row = await seed_run(isolated_store)
    browser = PersistentBrowserSession(row.run_id)
    await browser.open('https://fixture.example/job')
    row = await service.checkpoint(
        'fixture', row.revision, status='paused', browser_transport='broker',
        browser_closed=False, session_available=True,
        current_url='about:blank')
    lease = await service.start_handoff(
        'fixture', service.HandoffStartRequest(revision=row.revision))
    token = lease['handoff_token']
    finished = await service.finish_handoff(
        'fixture', token, service.HandoffFinishRequest(
            revision=lease['revision'], outcome='may_have_submitted'))
    assert finished['status'] == 'verifying'
    assert finished['verification_only'] is True
    assert finished['submit_started_at']
    uncertain = await service.checkpoint(
        'fixture', finished['revision'], status='submission_uncertain',
        error='Confirmation did not appear.')
    recovered = await service.control(
        'fixture', service.ControlRequest(
            revision=uncertain.revision, action='resume_unsubmitted', provider='gateway'))
    assert recovered['status'] == 'queued'
    assert recovered['verification_only'] is False
    assert not recovered.get('submit_started_at')
    assert not recovered.get('human_may_have_submitted_at')
    assert recovered['mistaken_submission_recovery']['visible_submit_control'] is True
    owner = broker[0].state.sessions[row.run_id]
    assert await owner.browser.page.evaluate('window.submits || 0') == 0
    service._sessions.pop('fixture', None)
    await browser.close()


@pytest.mark.asyncio
async def test_human_return_recovers_recorded_submit_when_form_is_still_open(
        isolated_store, broker):
    from app.services.job_browser_client import PersistentBrowserSession
    row = await seed_run(isolated_store)
    browser = PersistentBrowserSession(row.run_id)
    await browser.open('https://fixture.example/job')
    row = await service.checkpoint(
        'fixture', row.revision, status='submission_uncertain',
        browser_transport='broker', browser_closed=False, session_available=True,
        current_url='about:blank', submit_started_at=service.core.now().isoformat())
    lease = await service.start_handoff(
        'fixture', service.HandoffStartRequest(revision=row.revision))
    token = lease['handoff_token']
    finished = await service.finish_handoff(
        'fixture', token, service.HandoffFinishRequest(
            revision=lease['revision'], outcome='resume_agent'))
    assert finished['status'] == 'queued'
    assert finished['verification_only'] is False
    assert not finished.get('submit_started_at')
    assert finished['mistaken_submission_recovery']['visible_submit_control'] is True
    assert finished['mistaken_submission_recovery']['source'] == 'human_control_return'
    service._sessions.pop('fixture', None)
    await browser.close()


@pytest.mark.asyncio
async def test_verification_after_interrupted_click_cannot_fill_or_resubmit(isolated_store, monkeypatch):
    row = await seed_run(isolated_store)
    browser = AsyncMock()
    browser.observe.return_value = {'url':'https://fixture.example/job', 'frames':[{'text':'Form', 'controls':[{'id':'e0'}]}]}
    service._sessions['fixture'] = browser
    row = await service.checkpoint('fixture', row.revision, status='submission_uncertain', interaction_started=True)
    await service.control('fixture', service.ControlRequest(action='verify', revision=row.revision))
    monkeypatch.setattr(service, 'model_decision', AsyncMock(return_value=({'action':{'kind':'fill','element':'e0','value':'Again','summary':'Fill'}},{})))
    with pytest.raises(ValueError, match='read-only'):
        await service.step(await load_run())
    browser.execute.assert_not_called()


@pytest.mark.asyncio
async def test_verification_retry_clears_stale_failure_context(isolated_store):
    row = await seed_run(isolated_store)
    browser = AsyncMock()
    service._sessions['fixture'] = browser
    row = await service.checkpoint(
        'fixture', row.revision, status='submission_uncertain',
        submit_started_at='2026-09-27T10:00:00+00:00',
        error='Please provide the code manually.',
        failed_action={'kind': 'verification_code'},
        failed_audit={'allowed': False}, failed_model={'id': 'decision'},
        failed_audit_model={'id': 'audit'}, audit_feedback={'reason': 'old'},
        audit_repair_count=2)
    result = await service.control(
        'fixture', service.ControlRequest(action='verify', revision=row.revision))
    assert result['status'] == 'verifying'
    assert result['error'] is None
    assert result['failed_action'] is None
    assert result['failed_audit'] is None
    assert result['failed_model'] is None
    assert result['failed_audit_model'] is None
    assert result['audit_feedback'] is None
    assert result['audit_repair_count'] == 0


@pytest.mark.asyncio
async def test_quit_from_question_preserves_history_without_saving_answer(isolated_store, monkeypatch):
    row = await seed_run(isolated_store)
    question={'id':'relocation','text':'Would you relocate to Czechia or Slovakia?', 'choices':[]}
    row = await service.checkpoint('fixture',row.revision,status='waiting_for_answer',question=question)
    browser=AsyncMock();service._sessions['fixture']=browser
    remember=AsyncMock();monkeypatch.setattr(service.profile,'remember',remember)
    done=await service.control('fixture',service.ControlRequest(action='quit',revision=row.revision,
        reason='Not willing to relocate',answer='This must not become a profile answer'))
    assert done['status']=='cancelled' and done['question'] is None
    assert done['quit_reason']=='Not willing to relocate' and done['quit_question']==question
    assert done['browser_closed'] and done['can_restart'] and not done['can_quit']
    browser.close.assert_awaited_once();remember.assert_not_called()
    assert await service.checkpoint('fixture',row.revision,status='running') is None
    await service.recover()
    assert (await service.get('fixture'))['status']=='cancelled'
    with pytest.raises(ValueError,match='quit this application'):
        await service.control('fixture',service.ControlRequest(action='resume',revision=done['revision']))
    events=(await service.get('fixture'))['events']
    assert events[-1]['kind']=='quit' and events[-1]['reason']=='Not willing to relocate'


@pytest.mark.asyncio
async def test_quit_succeeds_when_browser_cleanup_fails_and_release_keeps_cancelled(isolated_store):
    row=await seed_run(isolated_store)
    row=await service.checkpoint('fixture',row.revision,status='paused')
    browser=AsyncMock();browser.close.side_effect=ValueError('unreachable');service._sessions['fixture']=browser
    result=await service.control('fixture',service.ControlRequest(action='quit',revision=row.revision))
    assert result['status']=='cancelled' and result['browser_cleanup_error']
    browser.close.side_effect=None
    result=await service.control('fixture',service.ControlRequest(action='release',revision=result['revision']))
    assert result['status']=='cancelled' and not result['browser_cleanup_error']


@pytest.mark.asyncio
@pytest.mark.parametrize('status,markers',[('running',{}),('submitted',{}),('submission_uncertain',{'submit_started_at':'recorded'}),('paused',{'interaction_started':True})])
async def test_quit_cannot_disguise_active_or_possible_submission(isolated_store,status,markers):
    row=await seed_run(isolated_store)
    row=await service.checkpoint('fixture',row.revision,status=status,**markers)
    with pytest.raises(ValueError):
        await service.control('fixture',service.ControlRequest(action='quit',revision=row.revision))
    assert (await load_run()).status==status


@pytest.mark.asyncio
async def test_quit_suggestions_have_no_side_effects_and_reject_stale_context(isolated_store,monkeypatch):
    row=await seed_run(isolated_store)
    row=await service.checkpoint('fixture',row.revision,status='waiting_for_answer',question={'id':'q','text':'Relocate to Czechia?', 'choices':[]})
    infer=AsyncMock(return_value=["I'm not willing to relocate to Czechia."])
    monkeypatch.setattr(service,'infer_quit_reasons',infer)
    result=await service.quit_reasons('fixture')
    assert result['reasons']==["I'm not willing to relocate to Czechia."]
    assert (await load_run()).revision==row.revision and (await load_run()).status=='waiting_for_answer'
    async def stale(state):
        await service.checkpoint('fixture',row.revision,status='paused')
        return ['Old suggestion']
    monkeypatch.setattr(service,'infer_quit_reasons',stale)
    with pytest.raises(ValueError,match='changed'):
        await service.quit_reasons('fixture')
