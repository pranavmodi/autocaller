"""Browser application safety and real-browser form workflow regression tests."""
import hashlib
import os
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.services import job_agent as core, job_agent_processing as processing
from app.services import job_browser as service
from app.services.job_browser_tools import BrowserAction, BrowserSession


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
        last_action={'kind':'select', 'element':'e7', 'value':'India'},
        audit={'allowed':True, 'effect':'input', 'reason':'Current country field.',
               'recovery':'none', 'repair_hint':''})
    visible = service.view(row)
    assert visible['can_resume'] is True
    assert visible['recoverable_input_interruption'] is True
    resumed = await service.control('fixture', service.ControlRequest(
        revision=row.revision, action='resume'))
    assert resumed['status'] == 'queued'
    assert resumed['interaction_started'] is False
    assert resumed['interrupted_action_recovery']['action']['kind'] == 'select'
    current = await service.get('fixture')
    assert any(event['kind'] == 'input_recovered' for event in current['events'])


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
async def test_rejected_challenge_code_can_be_retried_without_claiming_submission(isolated_store):
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
            text += "\nInvalid security code"
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
    assert 'Ab12Cd34' not in str((await load_run()).state)


@pytest.mark.asyncio
async def test_explicitly_rejected_code_allows_clean_restart(isolated_store):
    row = await seed_run(isolated_store)
    controls = [{'id':f'e{index + 1}','tag':'input','type':'text',
                 'label':'Security code' if index == 0 else '', 'disabled':False,
                 'value':value} for index, value in enumerate('Ab12Cd34')]
    controls.append({'id':'e9','tag':'button','type':'submit','label':'Submit application',
                     'disabled':True})
    snapshot = {'url':'https://fixture.invalid/job', 'frames':[{
        'text':("A verification code was sent to applicant@example.com. To submit your application, "
                "enter the 8-character code to confirm you're a human.\nInvalid security code"),
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
    with pytest.raises(ValueError, match='confirmation evidence'):
        await service.step(row)
    assert (await service.get('fixture'))['status'] != 'submitted'


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
async def test_resume_can_switch_provider_but_cannot_reset_submission(isolated_store, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-placeholder')
    row=await seed_run(isolated_store)
    row=await service.checkpoint('fixture',row.revision,status='blocked',ai_provider='gateway')
    changed=await service.control('fixture',service.ControlRequest(revision=row.revision,action='resume',provider='openai'))
    assert changed['ai_provider']=='openai' and changed['status']=='queued'
    assert changed['openai_model']=='gpt-5-mini'
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
    with pytest.raises(ValueError,match='Unsupported authorization'):await service.step(row)
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
