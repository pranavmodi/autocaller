"""Real Chromium + private Unix RPC: worker disconnect is not browser destruction."""
import asyncio
import hashlib
import stat
from uuid import uuid4

import pytest
import pytest_asyncio
import uvicorn

from app.services import job_browser_broker as broker_module
from app.services.job_browser_client import PersistentBrowserSession
from app.services.job_browser_tools import BrowserAction, BrowserProgram


@pytest_asyncio.fixture
async def broker(tmp_path, monkeypatch):
    # Synthetic page only. Production public-URL restrictions are unchanged.
    async def fixture_open(self, url):
        from playwright.async_api import async_playwright
        self.engine = await async_playwright().start()
        self.browser = await self.engine.chromium.launch()
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()
        await self.page.set_content('''<form onsubmit="event.preventDefault();
          window.submits=(window.submits||0)+1; document.querySelector('p').textContent='Application received';">
          <label>Name<input name="name" required></label>
          <button type="submit">Submit</button></form><p></p>''')
    monkeypatch.setattr(broker_module.BrowserSession, 'open', fixture_open)
    socket = tmp_path / 'broker.sock'
    monkeypatch.setenv('JOB_BROWSER_SOCKET', str(socket))
    app = broker_module.create_app(tmp_path)
    socket_manager = broker_module.private_socket(socket)
    listener = socket_manager.__enter__()
    assert stat.S_IMODE(socket.stat().st_mode) == 0o600
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(.05)
        assert server.started
        yield app, tmp_path
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 15)
        socket_manager.__exit__(None, None, None)


async def open_fixture(broker):
    app, root = broker
    run_id = uuid4().hex
    directory = root / run_id
    directory.mkdir()
    (directory / 'resume.pdf').write_bytes(b'%PDF-fixture')
    client = PersistentBrowserSession(run_id)
    await client.open('https://fixture.example/job')
    return client, directory, app.state.sessions[run_id]


@pytest.mark.asyncio
async def test_worker_reconnect_keeps_form_and_open_is_idempotent(broker):
    client, directory, owner = await open_fixture(broker)
    first = await client.attach()
    await client.observe(directory / 'page.png')
    await client.execute(BrowserAction(kind='fill', element='e0', value='Synthetic Applicant', summary='Name'), directory / 'resume.pdf')
    await client.detach()
    # New worker has no old element handles or Playwright connection.
    replacement = PersistentBrowserSession(client.run_id)
    assert (await replacement.attach())['instance'] == first['instance']
    await replacement.open('https://fixture.example/job')
    page = await replacement.observe(directory / 'page.png')
    assert page['frames'][0]['controls'][0]['value'] == 'Synthetic Applicant'
    assert await owner.browser.page.evaluate('window.submits || 0') == 0


@pytest.mark.asyncio
async def test_input_program_fills_multiple_fields_without_submitting(broker):
    client, directory, owner = await open_fixture(broker)
    await owner.browser.page.set_content('''<form onsubmit="event.preventDefault(); window.submits=(window.submits||0)+1">
      <label>First name<input name="first" required></label>
      <label>Last name<input name="last" required></label>
      <button type="submit">Submit</button></form>''')
    snapshot = await client.observe(directory / 'page.png')
    assert 'textbox "First name"' in snapshot['frames'][0]['accessibility']
    program = BrowserProgram(actions=[
        BrowserAction(kind='fill', element='e0', value='Pranav', summary='Fill name'),
        BrowserAction(kind='fill', element='e1', value='Modi', summary='Fill surname'),
    ])
    program_id = uuid4().hex
    observation_id = client.observation_id
    client.action_id = program_id
    result = await client.execute_program(program, directory / 'resume.pdf')
    assert len(result['operations']) == 2
    payload = {'program_id': program_id, 'observation_id': observation_id,
               'resume_sha256': hashlib.sha256(b'%PDF-fixture').hexdigest(),
               'program': program.model_dump()}
    replay = await client.request('POST', '/execute-program', json=payload)
    assert replay['already_completed'] is True
    with pytest.raises(ValueError, match='different contents'):
        await client.request('POST', '/execute-program', json={
            **payload, 'program': BrowserProgram(actions=[
                program.actions[0],
                program.actions[1].model_copy(update={'value': 'Changed'}),
            ]).model_dump()})
    assert await owner.browser.page.locator('input[name=first]').input_value() == 'Pranav'
    assert await owner.browser.page.locator('input[name=last]').input_value() == 'Modi'
    assert await owner.browser.page.evaluate('window.submits || 0') == 0


@pytest.mark.asyncio
async def test_generated_text_response_uploads_without_replacing_resume(broker):
    client, directory, owner = await open_fixture(broker)
    await owner.browser.page.set_content('''<form>
      <label>Describe a stakeholder example<input name="response" type="file" accept=".txt,text/plain"></label>
      </form>''')
    snapshot = await client.observe(directory / 'page.png')
    control = snapshot['frames'][0]['controls'][0]
    assert control['accept'] == '.txt,text/plain'
    response = (
        'I clarified the stakeholder decision, data inputs, constraints, and success metric; '
        'then translated the shared need into an iterative production plan.'
    )
    await client.execute(BrowserAction(kind='upload_text', element=control['id'],
        value=response, summary='Attach stakeholder response'), directory / 'resume.pdf')
    uploaded = await owner.browser.page.locator('input[name=response]').evaluate(
        'async e => ({name: e.files[0].name, text: await e.files[0].text()})')
    assert uploaded == {'name': 'Pranav_Modi_Application_Response.txt', 'text': response + '\n'}
    assert (directory / 'resume.pdf').read_bytes() == b'%PDF-fixture'


@pytest.mark.asyncio
async def test_stale_observation_and_duplicate_submit_never_click_twice(broker):
    client, directory, owner = await open_fixture(broker)
    await client.observe(directory / 'page.png')
    await client.execute(BrowserAction(kind='fill', element='e0', value='Applicant', summary='Name'), directory / 'resume.pdf')
    await client.observe(directory / 'page.png')
    payload = {'action_id': uuid4().hex, 'observation_id': client.observation_id,
               'resume_sha256': hashlib.sha256(b'%PDF-fixture').hexdigest(),
               'action': BrowserAction(kind='submit', element='e1', summary='Submit').model_dump()}
    await client.request('POST', '/execute', json=payload)
    assert (await client.request('POST', '/execute', json=payload))['already_completed']
    assert await owner.browser.page.evaluate('window.submits') == 1
    with pytest.raises(ValueError, match='observation changed'):
        await client.request('POST', '/execute', json={**payload, 'action_id': uuid4().hex})
    with pytest.raises(ValueError, match='different contents'):
        await client.request('POST', '/execute', json={**payload, 'resume_sha256': 'different'})


@pytest.mark.asyncio
async def test_disconnect_during_submit_finishes_in_owner_without_replay(broker):
    client, directory, owner = await open_fixture(broker)
    await client.observe(directory / 'page.png')
    await client.execute(BrowserAction(kind='fill', element='e0', value='Applicant', summary='Name'), directory / 'resume.pdf')
    await client.observe(directory / 'page.png')
    began, finish = asyncio.Event(), asyncio.Event()
    original = owner.browser.execute
    async def delayed(action, resume):
        began.set()
        await finish.wait()
        await original(action, resume)
    owner.browser.execute = delayed
    pending = asyncio.create_task(client.execute(BrowserAction(kind='submit', element='e1', summary='Submit'), directory / 'resume.pdf'))
    await asyncio.wait_for(began.wait(), 5)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    finish.set()
    replacement = PersistentBrowserSession(client.run_id)
    snapshot = await replacement.observe(directory / 'page.png')
    assert 'Application received' in snapshot['frames'][0]['text']
    assert await owner.browser.page.evaluate('window.submits') == 1


@pytest.mark.asyncio
async def test_lost_session_cannot_be_recreated_and_other_session_survives(broker):
    client, directory, owner = await open_fixture(broker)
    other, _, other_owner = await open_fixture(broker)
    await client.close()
    assert not (await client.status())['available']
    with pytest.raises(ValueError, match='gone'):
        await client.attach()
    with pytest.raises(ValueError, match='closed or lost'):
        await client.open('https://fixture.example/job')
    assert (await other.attach())['available']
    # Simulate complete owner loss: the tombstone survives, the browser does not.
    await other_owner.browser.close()
    broker[0].state.sessions.clear()
    with pytest.raises(ValueError, match='closed or lost'):
        await other.open('https://fixture.example/job')


@pytest.mark.asyncio
async def test_invalid_id_changed_resume_and_unknown_session_are_rejected(broker):
    with pytest.raises(ValueError, match='identifier'):
        await PersistentBrowserSession('not-an-id').status()
    client, directory, _ = await open_fixture(broker)
    await client.observe(directory / 'page.png')
    with pytest.raises(ValueError, match='resume changed'):
        await client.request('POST', '/execute', json={
            'action_id': uuid4().hex, 'observation_id': client.observation_id,
            'resume_sha256': 'bad', 'action': BrowserAction(kind='submit', element='e1', summary='Submit').model_dump()})
    with pytest.raises(ValueError, match='gone'):
        await PersistentBrowserSession(uuid4().hex).attach()


@pytest.mark.asyncio
async def test_human_actions_use_exact_observation_and_preserve_same_page(broker):
    client, directory, owner = await open_fixture(broker)
    await client.observe(directory / 'page.png')
    box = await owner.browser.page.locator('input').bounding_box()
    assert box
    await client.human_action(
        observation_id=client.observation_id, action_id=uuid4().hex,
        kind='click', x=box['x'] + 5, y=box['y'] + 5)
    await client.observe(directory / 'page.png')
    stale = client.observation_id
    await client.human_action(
        observation_id=stale, action_id=uuid4().hex,
        kind='type', value='Entered by the operator')
    assert await owner.browser.page.locator('input').input_value() == 'Entered by the operator'
    with pytest.raises(ValueError, match='live browser view changed'):
        await client.human_action(
            observation_id=stale, action_id=uuid4().hex,
            kind='press', key='Tab')
    assert await owner.browser.page.evaluate('window.submits || 0') == 0
