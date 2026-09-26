"""Classification, explicit send intent, recipient evidence and duplicate safety."""
import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.services import job_agent as core, job_agent_processing as processing
from app.services import job_agent_mail as mail, job_agent_research as research, job_agent_resumes as resumes


@pytest.fixture
def verified_job_identity(monkeypatch):
    verifier = AsyncMock(return_value={
        'provider': 'typesafe', 'model': 'jev-test', 'probability': 0.97,
        'threshold': 0.8, 'usage': {},
    })
    monkeypatch.setattr(research, 'verify_job_identity_with_jev', verifier)
    return verifier


def test_category_config_requires_unique_ids():
    category = resumes.default_categories()[0]
    with pytest.raises(ValidationError):
        core.JobAgentConfig(resume_categories=[category, category])


def test_resume_path_rejects_escape_and_non_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(resumes, 'RESUME_ROOT', tmp_path / 'library')
    (tmp_path / 'library').mkdir()
    (tmp_path / 'private.pdf').write_bytes(b'private')
    (tmp_path / 'library' / 'alias.pdf').symlink_to(tmp_path / 'private.pdf')
    for path in ['../private.pdf', 'alias.pdf', '/etc/passwd', 'missing.pdf']:
        with pytest.raises(ValueError):
            resumes.resolve_resume(path)


def test_resume_rejects_multiple_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(resumes, 'RESUME_ROOT', tmp_path)
    (tmp_path / 'resume.pdf').write_bytes(b'pdf')
    monkeypatch.setattr(resumes.subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout='Pages: 2\n'))
    with pytest.raises(ValueError, match='one page'):
        resumes.inspect_resume('resume.pdf')


def test_real_category_resumes_are_one_page():
    for category in resumes.default_categories():
        result = resumes.inspect_resume(category.resume_path)
        assert result['pages'] == 1
        assert 'Possible Minds' in result['text'] and 'PRANAV MODI' in result['text']


def test_resume_catalog_separates_application_category_and_library(tmp_path, monkeypatch):
    monkeypatch.setattr(resumes, 'RESUME_ROOT', tmp_path)
    (tmp_path / 'job-agent' / 'resumes').mkdir(parents=True)
    (tmp_path / 'applications' / 'Example').mkdir(parents=True)
    (tmp_path / 'misc').mkdir()
    category_file = tmp_path / 'job-agent' / 'resumes' / 'AI.pdf'
    application_file = tmp_path / 'applications' / 'Example' / 'Pranav_Example.pdf'
    other_file = tmp_path / 'misc' / 'Older.pdf'
    for path in (category_file, application_file, other_file):
        path.write_bytes(b'%PDF test')
    categories = [SimpleNamespace(id='ai', name='AI automation', resume_path='job-agent/resumes/AI.pdf')]
    applications = [{'path': 'applications/Example/Pranav_Example.pdf', 'filename': 'Pranav_Example.pdf',
                     'firm_name': 'Example', 'role_title': 'AI Engineer', 'application_status': 'sent_verified',
                     'sent_verified': True, 'updated_at': '2026-09-21T10:00:00+00:00'}]

    items = resumes.resume_catalog(categories, applications)

    assert [item['kind'] for item in items] == ['application', 'category', 'library']
    assert items[0]['firm_name'] == 'Example' and items[0]['sent_verified'] is True
    assert items[1]['category_names'] == ['AI automation']


@pytest.mark.asyncio
async def test_job_agent_classification_uses_one_jev_choice_request(monkeypatch):
    categories = resumes.default_categories()[:2]
    options = {category.id: 0.0 for category in categories}
    options[processing.JEV_NO_MATCH] = 0.0
    answers = {
        'job_0': {'type': 'choice', 'choice': categories[0].id, 'confidence': 0.96,
                  'probabilities': {**options, categories[0].id: 0.97, categories[1].id: 0.03}},
        'job_1': {'type': 'choice', 'choice': processing.JEV_NO_MATCH, 'confidence': 0.91,
                  'probabilities': {**options, processing.JEV_NO_MATCH: 0.95,
                                    categories[0].id: 0.03, categories[1].id: 0.02}},
    }
    captured = {}

    class Client:
        def __init__(self, **kwargs):
            captured['client'] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **kwargs):
            captured['url'], captured['request'] = url, kwargs
            return httpx.Response(200, request=httpx.Request('POST', url), json={
                'model': 'jev-1.13.0', 'answers': answers,
                'usage': {'input_tokens': 400, 'output_tokens': 80},
            })

    monkeypatch.setattr(processing.httpx, 'AsyncClient', Client)
    monkeypatch.setenv('TYPESAFE_API_KEY', 'secret-test-key')
    monkeypatch.delenv('JOB_AGENT_TYPESAFE_MODEL', raising=False)
    jobs = [
        {'candidate_id': 'a', 'title': 'AI Engineer', 'responsibilities': ['Build agents']},
        {'candidate_id': 'b', 'title': 'Attorney', 'responsibilities': ['Try cases']},
    ]

    decisions = await processing.classify_with_jev(jobs, categories)

    assert [decision.category_id for decision in decisions] == [categories[0].id, categories[0].id]
    assert 'Closest available resume' in decisions[1].reason
    assert decisions[1].confidence == 0.03
    assert decisions[1].probabilities[processing.JEV_NO_MATCH] == 0.95
    assert decisions[0].model == 'jev-1.13.0'
    assert decisions[0].probabilities[categories[0].id] == 0.97
    assert '97% category probability' in decisions[0].reason
    assert captured['url'] == processing.TYPESAFE_SYSTEM_ONE_URL
    assert captured['request']['headers']['Authorization'] == 'Bearer secret-test-key'
    assert captured['request']['json']['model'] == 'jev-latest'
    assert set(captured['request']['json']['questions']) == {'job_0', 'job_1'}
    assert set(captured['request']['json']['questions']['job_0']['criteria']) == set(options)


def test_jev_response_rejects_missing_category_probabilities():
    category = resumes.default_categories()[0]
    response = {'model': 'jev-1.13.0', 'answers': {
        'job_0': {'type': 'choice', 'choice': category.id, 'confidence': 0.9,
                  'probabilities': {category.id: 1.0}},
    }}

    with pytest.raises(ValueError, match='invalid options'):
        processing._parse_jev_decisions(response, ['job'], [category])


@pytest.mark.asyncio
async def test_jev_requires_api_key_without_using_openclaw(monkeypatch):
    monkeypatch.delenv('TYPESAFE_API_KEY', raising=False)
    gateway = AsyncMock()
    monkeypatch.setattr(processing, 'call_skill_json', gateway)

    with pytest.raises(RuntimeError, match='TYPESAFE_API_KEY'):
        await processing.classify_with_jev(
            [{'candidate_id': 'a', 'title': 'Data analyst'}],
            resumes.default_categories(),
        )

    gateway.assert_not_awaited()


def test_zoho_cli_uses_attachment_tuple_and_no_shell(monkeypatch):
    from app.services import email_notification_service as transport
    monkeypatch.setattr(transport, '_zoho_account_id', lambda: 'account')
    monkeypatch.setattr(transport, '_zoho_upload_attachment', lambda *a: {'attachmentName': 'resume.pdf', 'attachmentPath': '/Mail/file', 'storeName': 'store'})
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout='Working...\n{"status":{"code":200,"description":"success"}}\n')
    monkeypatch.setattr(mail.subprocess, 'run', run)
    result = mail.send_cli({'from': 'pranav@possiblemindshq.com', 'to': 'jobs@example.com', 'subject': 'Application', 'body_text': 'Hello\n\nResume attached.'}, 'resume.pdf')
    args, kwargs = calls[0]
    assert result['transport'] == 'zoho_cli'
    assert '--attachments=resume.pdf::/Mail/file::store' in args
    assert '--content=Hello\n\nResume attached.' in args
    assert not kwargs.get('shell')
    assert len(calls) == 1


def test_sent_verification_requires_body_and_exact_attachment(monkeypatch):
    email = {'from': 'pranav@possiblemindshq.com', 'to': 'jobs@example.com', 'subject': 'Application: Engineer', 'body_text': 'Hello, my resume is attached.'}
    message = EmailMessage()
    message['From'], message['To'], message['Subject'] = email['from'], email['to'], email['subject']
    message['Message-ID'] = '<sent@example.com>'
    message.set_content(email['body_text'])
    message.add_attachment(b'correct-pdf', maintype='application', subtype='pdf', filename='resume.pdf')
    monkeypatch.setattr(mail, '_messages', lambda *a, **k: iter([('Sent', '1', message.as_bytes())]))
    monkeypatch.setattr(mail.time, 'sleep', lambda _: None)
    assert mail.verify_sent(email, hashlib.sha256(b'correct-pdf').hexdigest())['uid'] == '1'
    assert mail.verify_sent(email, hashlib.sha256(b'wrong-pdf').hexdigest()) is None
    assert mail.verify_sent({**email, 'body_text': 'Different draft'}, hashlib.sha256(b'correct-pdf').hexdigest()) is None


def test_sent_recheck_schedule_is_bounded_and_due():
    now = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
    first = processing.next_sent_recheck_at(0, now=now)
    assert first == '2026-09-20T18:00:30+00:00'
    assert not processing.sent_recheck_due({
        'verification_rechecks': 0, 'verification_next_at': first}, now=now)
    assert processing.sent_recheck_due({
        'verification_rechecks': 0, 'verification_next_at': first},
        now=datetime(2026, 9, 20, 18, 0, 30, tzinfo=timezone.utc))
    assert processing.next_sent_recheck_at(3, now=now) is None
    assert not processing.sent_recheck_due({
        'verification_rechecks': 3, 'verification_next_at': first},
        now=datetime(2026, 9, 20, 18, 1, tzinfo=timezone.utc))


@pytest.mark.asyncio
async def test_automatic_sent_recheck_verifies_without_sending(monkeypatch):
    async def directly(function, *args, **kwargs):
        return function(*args, **kwargs)

    save = AsyncMock()
    monkeypatch.setattr(processing.asyncio, 'to_thread', directly)
    monkeypatch.setattr(processing, 'set_application', save)
    monkeypatch.setattr(processing, 'record_application_communication', AsyncMock(return_value='log-1'))
    monkeypatch.setattr(mail, 'verify_sent', lambda *_args: {
        'uid': 'sent-1', 'attachment_sha256': 'hash'})

    await processing.automatic_sent_recheck('candidate', {
        'email': {'to': 'jobs@example.com'}, 'attachment': {'sha256': 'hash'},
        'verification_rechecks': 1,
    })

    assert save.await_args.kwargs['status'] == 'sent_verified'
    assert save.await_args.kwargs['verification_next_at'] is None
    assert save.await_args.kwargs['retryable'] is False


@pytest.mark.asyncio
async def test_job_application_communication_contains_searchable_context(monkeypatch):
    from datetime import datetime
    calls = []
    monkeypatch.setattr('app.services.comms_log.log_email', lambda **kwargs: calls.append(kwargs) or 'log-1')
    application = {
        'posting': {'firm_name': 'Example LLP', 'title': 'Automation Engineer'},
        'email': {'to': 'jobs@example.com', 'subject': 'Application: Automation Engineer',
                  'body_text': 'Hello, my resume is attached.'},
        'recipient': {'name': 'Recruiting'},
        'send_started_at': '2026-09-18T08:00:00+00:00',
    }

    result = await processing.record_application_communication(
        'candidate-1', application, 'sent_verified',
        verification={'provider_message_id': 'zoho-1'},
    )

    assert result == 'log-1'
    assert calls == [{
        'recipient_email': 'jobs@example.com',
        'recipient_name': 'Recruiting',
        'subject': 'Application: Automation Engineer',
        'body': 'Hello, my resume is attached.',
        'message_type': 'job_application',
        'transport': 'zoho_cli',
        'message_id': 'zoho-1',
        'status': 'sent_verified',
        'error': None,
        'firm_name': 'Example LLP',
        'source_type': 'job_application',
        'source_id': 'candidate-1',
        'occurred_at': datetime.fromisoformat('2026-09-18T08:00:00+00:00'),
    }]


@pytest.mark.asyncio
async def test_uncertain_send_is_not_retried(monkeypatch):
    events, calls = [], []
    async def directly(function, *args, **kwargs):
        return function(*args, **kwargs)
    monkeypatch.setattr(processing.asyncio, 'to_thread', directly)
    monkeypatch.setattr(processing, 'validate_current_job', AsyncMock())
    monkeypatch.setattr(processing, 'inspect_resume', lambda _: {'sha256': 'hash', 'path': 'resume.pdf'})
    monkeypatch.setattr(processing, 'resolve_resume', lambda _: Path('/resume.pdf'))
    monkeypatch.setattr(processing, 'duplicate_evidence', AsyncMock(return_value=None))
    monkeypatch.setattr(processing, 'record_application_communication', AsyncMock(return_value='log-1'))
    async def save(identity, **values): events.append(values)
    monkeypatch.setattr(processing, 'set_application', save)
    def uncertain(*args):
        calls.append(args)
        raise TimeoutError('unknown')
    monkeypatch.setattr(mail, 'send_cli', uncertain)
    await processing.send_application('job', {'send_requested': True, 'authorized_at': 'now', 'attachment': {'path': 'resume.pdf', 'sha256': 'hash'}, 'email': {}, 'posting': {}})
    assert len(calls) == 1
    assert events[0]['status'] == 'sending' and events[-1]['status'] == 'delivery_unconfirmed'
    with pytest.raises(ValueError, match='explicit'):
        await processing.send_application('job', {'send_requested': False})


@pytest.mark.asyncio
async def test_duplicate_blocks_send(monkeypatch):
    monkeypatch.setattr(processing, 'validate_current_job', AsyncMock())
    monkeypatch.setattr(processing, 'inspect_resume', lambda _: {'sha256': 'hash', 'path': 'resume.pdf'})
    monkeypatch.setattr(processing, 'duplicate_evidence', AsyncMock(return_value={'kind': 'previous_application'}))
    save = AsyncMock()
    monkeypatch.setattr(processing, 'set_application', save)
    send = AsyncMock()
    monkeypatch.setattr(mail, 'send_cli', send)
    await processing.send_application('job', {'send_requested': True, 'authorized_at': 'now', 'attachment': {'path': 'resume.pdf', 'sha256': 'hash'}, 'email': {}, 'posting': {}})
    assert save.call_args.kwargs['status'] == 'needs_review'
    send.assert_not_called()


@pytest.mark.asyncio
async def test_preparation_records_observable_checkpoints(monkeypatch, tmp_path):
    source = tmp_path / 'source.pdf'
    source.write_bytes(b'one-page-pdf')
    packet = {
        'email': {'from': 'pranav@possiblemindshq.com', 'to': 'jobs@example.com',
                  'subject': 'Application: Workflow Developer', 'body_text': 'Resume attached.'},
        'recipient': {'name': 'Recruiting', 'email': 'jobs@example.com'},
        'fit_reason': 'Workflow experience',
    }
    events = []

    async def save(_identity, **values):
        events.append(values)

    async def directly(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(processing.asyncio, 'to_thread', directly)
    monkeypatch.setattr(research, 'research_application', AsyncMock(return_value=packet))
    monkeypatch.setattr(processing, 'set_application', save)
    monkeypatch.setattr(processing, 'duplicate_evidence', AsyncMock(return_value=None))
    monkeypatch.setattr(processing, 'resolve_resume', lambda _path: source)
    monkeypatch.setattr(processing, 'inspect_resume', lambda path: {
        'path': str(Path(path).relative_to(tmp_path)), 'filename': Path(path).name,
        'pages': 1, 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(), 'text': 'resume'})
    monkeypatch.setattr(processing, 'RESUME_ROOT', tmp_path)

    await processing.prepare_application('candidate', {
        'run_id': 'run', 'send_requested': False,
        'posting': {'firm_name': 'Example LLP', 'title': 'Workflow Developer'},
        'resume': {'path': 'source.pdf', 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()},
    })

    assert [event['phase'] for event in events] == [
        'researching', 'checking_duplicates', 'packaging', 'ready']
    assert events[2]['duplicate_checked_at']
    assert events[-1]['status'] == 'ready'
    assert events[-1]['retryable'] is False


@pytest.mark.asyncio
async def test_sent_verification_retry_records_check_without_resending(monkeypatch):
    async def directly(function, *args, **kwargs):
        return function(*args, **kwargs)

    current = {'application': {'status': 'delivery_unconfirmed', 'email': {'to': 'jobs@example.com'},
                               'attachment': {'sha256': 'hash'}}}
    final = {'application': {'status': 'delivery_unconfirmed', 'verification_checked_at': 'now'}}
    detail = AsyncMock(side_effect=[current, final])
    save = AsyncMock()
    monkeypatch.setattr(processing, 'detail', detail)
    monkeypatch.setattr(processing, 'set_application', save)
    monkeypatch.setattr(processing, 'record_application_communication', AsyncMock(return_value='log-1'))
    monkeypatch.setattr(processing.asyncio, 'to_thread', directly)
    monkeypatch.setattr(mail, 'verify_sent', lambda *_args: None)

    result = await processing.verify_application('candidate')

    assert result is final
    assert save.await_args.kwargs['status'] == 'delivery_unconfirmed'
    assert save.await_args.kwargs['phase'] == 'verification_needed'
    assert save.await_args.kwargs['verification_checked_at']
    assert 'No resend occurred' in save.await_args.kwargs['error']


def test_evidence_requires_real_quote_and_successful_page():
    evidence = research.Evidence(source_url='https://example.com', text='jobs@example.com')
    with pytest.raises(ValueError):
        research.validate_evidence(evidence, [{'requested_url': 'https://example.com', 'http_status': 200, 'content': 'Contact support'}])
    with pytest.raises(ValueError):
        research.validate_evidence(evidence, [{'requested_url': 'https://example.com', 'http_status': 404, 'content': 'jobs@example.com'}])


def test_evidence_accepts_exact_fragments_and_email_in_different_page_order():
    url = 'https://example.com/people/denise'
    page = {'requested_url': url, 'http_status': 200, 'content': (
        'Denise Figueiredo Director of Human Resources dfigueiredo@example.com. '
        'Denise Figueiredo is the Director, Human Resources in the Toronto office. '
        'Denise is responsible for building effective teams, including recruiting top talent.')}
    evidence = research.Evidence(source_url=url, text=(
        'Denise Figueiredo is the Director, Human Resources in the Toronto office... '
        'responsible for building effective teams, including recruiting top talent... '
        'dfigueiredo@example.com'))
    assert research.validate_evidence(evidence, [page], 'Contact evidence') is page
    invented = research.Evidence(source_url=url, text=(
        'Denise Figueiredo is the Chief Technology Officer... dfigueiredo@example.com'))
    with pytest.raises(ValueError, match='Contact evidence excerpt'):
        research.validate_evidence(invented, [page], 'Contact evidence')


def test_evidence_url_identity_ignores_tracking_fragment_and_trailing_slash():
    page = {
        'requested_url': 'https://example.com/careers/?utm_source=linkedin',
        'final_url': 'https://example.com/careers/',
        'http_status': 200,
        'content': 'Example Systems careers and jobs@example.com',
    }
    evidence = research.Evidence(
        source_url='https://example.com/careers#open-roles',
        text='Example Systems careers',
    )

    assert research.validate_evidence(evidence, [page]) is page


def test_recipient_email_is_checked_against_fetched_page_not_short_excerpt():
    content = ('Denise Figueiredo, Director of Human Resources. Responsible for '
               'recruiting top talent. Contact dfigueiredo@example.com.')
    assert research.published_email('dfigueiredo@example.com', content)
    assert not research.published_email('invented@example.com', content)


def test_possibleos_contacts_require_employer_domain_and_suitable_routing_role():
    contacts = [
        SimpleNamespace(id='coo', pif_id='firm-1', full_name='Sarah Bonner',
                        email='sbonner@example.com', title='Chief Operating Officer',
                        research_title=None, source='front', front_last_seen=None, updated_at=None),
        SimpleNamespace(id='intake', pif_id='firm-1', full_name='',
                        email='intakes@example.com', title='Intake',
                        research_title=None, source='front', front_last_seen=None, updated_at=None),
        SimpleNamespace(id='vendor', pif_id='firm-1', full_name='Vendor Person',
                        email='person@vendor.example', title='Founder',
                        research_title=None, source='front', front_last_seen=None, updated_at=None),
        SimpleNamespace(id='other-firm', pif_id='firm-2', full_name='Other Owner',
                        email='owner@example.com', title='Owner',
                        research_title=None, source='front', front_last_seen=None, updated_at=None),
    ]

    ranked = research.rank_possibleos_contacts(contacts, 'example.com', {'firm-1'})

    assert [contact['contact_id'] for contact in ranked] == ['coo']
    assert ranked[0]['kind'] == 'routing'
    assert ranked[0]['evidence']['source_type'] == 'possibleos_contact'


@pytest.mark.asyncio
async def test_research_can_use_verified_possibleos_routing_contact(monkeypatch, verified_job_identity):
    company = 'https://example.com'
    job = 'https://jobs.example.com/personal-injury-assistant'
    contact = {
        'contact_id': 'contact-1', 'firm_id': 'firm-1', 'email': 'sbonner@example.com',
        'name': 'Sarah Bonner', 'title': 'Chief Operating Officer', 'kind': 'routing',
        'source': 'front', 'observed_at': '2026-09-18T00:00:00+00:00', 'score': 87,
        'evidence': {
            'source_type': 'possibleos_contact',
            'source_url': 'possibleos://firm-contacts/contact-1',
            'text': 'Sarah Bonner | Chief Operating Officer | sbonner@example.com',
            'contact_id': 'contact-1', 'source_name': 'front',
            'observed_at': '2026-09-18T00:00:00+00:00',
        },
    }
    application = {
        'posting': {'firm_id': 'firm-1', 'title': 'Personal Injury Assistant',
                    'firm_name': 'Example Legal Inc', 'website': 'example.com',
                    'source_url': job},
        'resume': {'text': 'PRANAV MODI\nFounder, Possible Minds'},
        'preferences': {},
    }

    async def fetch(url, **_kwargs):
        if url == job:
            content = 'Example Legal Inc — Personal Injury Assistant — Apply now'
        else:
            content = 'Example Legal Inc official website and careers'
        return {'requested_url': url, 'final_url': url, 'http_status': 200, 'content': content}

    async def model(mode, payload, _fields):
        if mode == 'discover_contacts':
            return {'company_url': company, 'contact_urls': [], 'job_urls': [], 'summary': 'Example'}
        if mode == 'compose':
            assert payload['possibleos_contacts'] == [contact]
            return {'blocked_reason': None, 'packet': {
                'company_summary': 'Example Legal is a law firm.',
                'company_evidence': {'source_url': company, 'text': 'Example Legal Inc official website'},
                'job_evidence': {'source_url': job,
                                 'text': 'Example Legal Inc — Personal Injury Assistant — Apply now'},
                'recipient': {'email': contact['email'], 'name': contact['name'], 'kind': 'routing',
                              'evidence': contact['evidence'],
                              'reason': 'Possible OS lists the COO as an employer-domain routing contact.'},
                'subject': 'Application: Personal Injury Assistant - Pranav Modi',
                'body_text': ('Hello Sarah, I am applying for the Personal Injury Assistant role. '
                              'My resume is attached. Could you please forward it to the person '
                              f'handling this role?\n\nRole: {job}'),
                'fit_reason': 'Relevant client and operations experience.', 'gaps': []}}
        assert mode == 'audit_email'
        assert payload['possibleos_contacts'] == [contact]
        return {'approved': True, 'reason': 'The routing request and evidence are accurate.'}

    monkeypatch.setattr(research, 'fetch_page', fetch)
    monkeypatch.setattr(research, 'load_possibleos_contacts', AsyncMock(return_value=[contact]))

    result = await research.research_application(application, model)

    assert result['recipient']['email'] == 'sbonner@example.com'
    assert result['recipient']['evidence']['source_type'] == 'possibleos_contact'
    assert result['evidence']['possibleos_contacts_considered'] == 1
    assert result['evidence']['possibleos_contact_error'] is None


@pytest.mark.asyncio
async def test_job_identity_verification_uses_jev_noul(monkeypatch):
    captured = {}

    class Client:
        def __init__(self, **kwargs):
            captured['client'] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **kwargs):
            captured['url'], captured['request'] = url, kwargs
            return httpx.Response(200, request=httpx.Request('POST', url), json={
                'model': 'jev-1.13.0',
                'answers': {
                    'same_job_identity_0': {'type': 'noul', 'noul': 0.81},
                    'same_job_identity_1': {'type': 'noul', 'noul': 0.96},
                },
                'usage': {'input_tokens': 200, 'output_tokens': 12},
            })

    monkeypatch.setattr(research.httpx, 'AsyncClient', Client)
    monkeypatch.setenv('TYPESAFE_API_KEY', 'secret-test-key')
    posting = {'title': 'Forward Deployed Engineer - Remote', 'firm_name': 'Kake'}
    page = {'requested_url': 'https://kake.co/jobs/role', 'final_url': 'https://kake.co/jobs/role',
            'content': 'Forward Deployed Engineer | Kake. Kake is a remote-first company.'}
    corroborating = {
        'requested_url': 'https://www.linkedin.com/jobs/view/123',
        'final_url': 'https://www.linkedin.com/jobs/view/123',
        'content': 'Kake is hiring a Forward Deployed Engineer.',
    }

    decision = await research.verify_job_identity_with_jev(
        page, posting, corroborating_pages=[corroborating]
    )

    assert decision == {'provider': 'typesafe', 'model': 'jev-1.13.0', 'probability': 0.96,
                        'selected_source_url': 'https://www.linkedin.com/jobs/view/123',
                        'source_probabilities': [
                            {'source_url': 'https://kake.co/jobs/role', 'probability': 0.81},
                            {'source_url': 'https://www.linkedin.com/jobs/view/123', 'probability': 0.96},
                        ], 'source_count': 2,
                        'usage': {'input_tokens': 200, 'output_tokens': 12}}
    request = captured['request']['json']
    assert captured['url'] == research.TYPESAFE_SYSTEM_ONE_URL
    assert request['model'] == 'jev-latest'
    assert request['questions']['same_job_identity_0']['type'] == 'noul'
    assert request['questions']['same_job_identity_1']['type'] == 'noul'
    assert request['state']['saved_job']['title'] == 'Forward Deployed Engineer - Remote'
    assert request['state']['candidate_sources'] == [{
        'url': 'https://kake.co/jobs/role',
        'content': 'Forward Deployed Engineer | Kake. Kake is a remote-first company.',
    }, {
        'url': 'https://www.linkedin.com/jobs/view/123',
        'content': 'Kake is hiring a Forward Deployed Engineer.',
    }]


@pytest.mark.asyncio
async def test_job_identity_uses_best_available_source_without_a_fixed_threshold(monkeypatch):
    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **_kwargs):
            return httpx.Response(200, request=httpx.Request('POST', url), json={
                'model': 'jev-1.13.0',
                'answers': {'same_job_identity_0': {'type': 'noul', 'noul': 0.22}},
            })

    monkeypatch.setattr(research.httpx, 'AsyncClient', lambda **_kwargs: Client())
    monkeypatch.setenv('TYPESAFE_API_KEY', 'secret-test-key')
    decision = await research.verify_job_identity_with_jev(
        {'requested_url': 'https://example.com/job', 'content': 'Example Office Manager'},
        {'title': 'AI Engineer', 'firm_name': 'Example'},
    )
    assert decision['probability'] == 0.22
    assert decision['selected_source_url'] == 'https://example.com/job'


@pytest.mark.asyncio
async def test_research_uses_verified_alternate_job_page_when_canonical_fetch_fails(
        monkeypatch, verified_job_identity):
    canonical = 'https://jobs.example.invalid/ai-cloud'
    company = 'https://example.com/careers'
    alternate = 'https://regional-recruiter.example.net/jobs/ai-cloud'
    application = {
        'posting': {'title': 'AI & Cloud Infrastructure Specialist', 'firm_name': 'Example Systems LLP',
                    'website': 'example.com', 'source_url': canonical},
        'resume': {'text': 'PRANAV MODI\nFounder, Possible Minds'},
        'preferences': {},
    }

    async def fetch(url, **_kwargs):
        if url == canonical:
            raise TimeoutError('source timed out')
        if url == alternate:
            return {'requested_url': url, 'final_url': url, 'http_status': 200,
                    'content': 'Example Systems LLP — AI & Cloud Infrastructure Specialist — Apply'}
        return {'requested_url': url, 'final_url': url, 'http_status': 200,
                'content': 'Example Systems LLP careers. Recruiting: jobs@example.com'}

    async def model(mode, payload, _fields):
        if mode == 'discover_contacts':
            return {'company_url': company, 'contact_urls': [company], 'job_urls': [alternate], 'summary': 'Example'}
        if mode == 'compose':
            assert {page['requested_url'] for page in payload['pages']} == {
                company, 'https://example.com/', alternate,
            }
            assert payload['source_fetch_failures'][0]['requested_url'] == canonical
            return {'blocked_reason': None, 'packet': {
                'company_summary': 'Example builds software.',
                'company_evidence': {'source_url': company, 'text': 'Example Systems LLP'},
                'job_evidence': {'source_url': alternate,
                                 'text': 'Example Systems LLP — AI & Cloud Infrastructure Specialist — Apply'},
                'recipient': {'email': 'jobs@example.com', 'name': 'Recruiting', 'kind': 'recruiting',
                              'evidence': {'source_url': company, 'text': 'Recruiting: jobs@example.com'},
                              'reason': 'Published recruiting inbox'},
                'subject': 'Application: AI & Cloud Infrastructure Specialist - Pranav Modi',
                'body_text': f'Hello, I am applying for this role. My resume is attached.\n\nRole: {canonical}',
                'fit_reason': 'Relevant agent infrastructure experience.', 'gaps': []}}
        assert mode == 'audit_email'
        assert alternate in payload['packet']['body_text']
        assert canonical not in payload['packet']['body_text']
        return {'approved': True, 'reason': 'Evidence is complete.'}

    phases = []

    async def update_phase(phase, stage):
        phases.append((phase, stage))

    monkeypatch.setattr(research, 'fetch_page', fetch)
    result = await research.research_application(application, model, update_phase)
    assert [phase for phase, _stage in phases] == [
        'discovering_contacts', 'fetching_sources', 'checking_contacts', 'drafting',
        'verifying_sources', 'auditing']
    assert result['evidence']['job']['source_url'] == alternate
    assert result['evidence']['canonical_job_url'] == canonical
    assert result['evidence']['verified_job_url'] == alternate
    assert result['evidence']['job_identity_verification']['probability'] == 0.97
    assert alternate in result['email']['body_text']
    assert canonical not in result['email']['body_text']
    assert result['evidence']['source_fetch_failures'][0]['requested_url'] == canonical


@pytest.mark.asyncio
async def test_research_reports_job_fetch_failures_before_composition(monkeypatch):
    canonical = 'https://jobs.example.invalid/ai-cloud'
    company = 'https://example.com/careers'
    application = {
        'posting': {'title': 'AI Engineer', 'firm_name': 'Example Systems', 'website': 'example.com',
                    'source_url': canonical},
        'resume': {'text': 'resume'}, 'preferences': {},
    }
    compose_called = False

    async def fetch(url, **_kwargs):
        if url == canonical:
            raise TimeoutError('source timed out')
        return {'requested_url': url, 'final_url': url, 'http_status': 200, 'content': 'Example Systems careers'}

    async def model(mode, _payload, _fields):
        nonlocal compose_called
        if mode == 'discover_contacts':
            return {'company_url': company, 'contact_urls': [], 'job_urls': [], 'summary': 'Example'}
        compose_called = True
        raise AssertionError('composition must not run without a verified role page')

    monkeypatch.setattr(research, 'fetch_page', fetch)
    with pytest.raises(ValueError, match='corroborating role pages.*jobs.example.invalid.*source timed out'):
        await research.research_application(application, model)
    assert compose_called is False


@pytest.mark.asyncio
async def test_research_uses_official_job_subdomain_when_company_page_redirects_elsewhere(
        monkeypatch, verified_job_identity):
    job = 'https://jobs.example.com/architect'
    company = 'https://example.com'
    application = {
        'posting': {'firm_id': 'firm-1', 'title': 'Data Architect', 'firm_name': 'Example Systems',
                    'website': 'example.com', 'source_url': job},
        'resume': {'text': 'PRANAV MODI\nFounder, Possible Minds'},
        'preferences': {},
    }

    async def fetch(url, **_kwargs):
        if url in {company, 'https://example.com/'}:
            return {'requested_url': url, 'final_url': 'https://consumer.example.net',
                    'http_status': 200, 'content': 'Unrelated consumer destination'}
        return {'requested_url': url, 'final_url': url, 'http_status': 200,
                'content': 'Example Systems — Data Architect — Apply now. Recruiting: jobs@example.com'}

    async def model(mode, payload, _fields):
        if mode == 'discover_contacts':
            return {'company_url': company, 'contact_urls': [], 'job_urls': [], 'summary': 'Example'}
        if mode == 'compose':
            assert payload['company_url'] == job
            return {'blocked_reason': None, 'packet': {
                'company_summary': 'Example Systems employs data architects.',
                'company_evidence': {'source_url': job, 'text': 'Example Systems'},
                'job_evidence': {'source_url': job, 'text': 'Data Architect — Apply now'},
                'recipient': {'email': 'jobs@example.com', 'name': 'Recruiting', 'kind': 'recruiting',
                              'evidence': {'source_url': job, 'text': 'Recruiting: jobs@example.com'},
                              'reason': 'Published recruiting inbox'},
                'subject': 'Application: Data Architect - Pranav Modi',
                'body_text': f'Hello, I am applying for this role. My resume is attached.\n\nRole: {job}',
                'fit_reason': 'Relevant data architecture experience.', 'gaps': []}}
        assert mode == 'audit_email'
        return {'approved': True, 'reason': 'Evidence is complete.'}

    monkeypatch.setattr(research, 'fetch_page', fetch)
    monkeypatch.setattr(research, 'load_possibleos_contacts', AsyncMock(return_value=[]))
    result = await research.research_application(application, model)
    assert result['evidence']['company']['source_url'] == job
    assert result['evidence']['job']['source_url'] == job


@pytest.mark.asyncio
async def test_research_prefers_saved_canonical_homepage_over_redirected_discovery(
        monkeypatch, verified_job_identity):
    job = 'https://ats.example.net/data-architect'
    discovered_company = 'https://example.com/old-about'
    canonical_company = 'https://example.com/'
    application = {
        'posting': {'firm_id': 'firm-1', 'title': 'Data Architect', 'firm_name': 'Example Systems',
                    'website': 'example.com', 'source_url': job},
        'resume': {'text': 'PRANAV MODI\nFounder, Possible Minds'},
        'preferences': {},
    }

    async def fetch(url, **_kwargs):
        if url == discovered_company:
            return {'requested_url': url, 'final_url': 'https://unrelated.example.org',
                    'http_status': 200, 'content': 'Unrelated destination'}
        if url == canonical_company:
            return {'requested_url': url, 'final_url': url, 'http_status': 200,
                    'content': 'Example Systems. Recruiting: jobs@example.com'}
        return {'requested_url': url, 'final_url': url, 'http_status': 200,
                'content': 'Example Systems — Data Architect — Apply now'}

    async def model(mode, payload, _fields):
        if mode == 'discover_contacts':
            return {'company_url': discovered_company, 'contact_urls': [], 'job_urls': [], 'summary': 'Example'}
        if mode == 'compose':
            assert payload['company_url'] == canonical_company
            return {'blocked_reason': None, 'packet': {
                'company_summary': 'Example Systems employs data architects.',
                'company_evidence': {'source_url': canonical_company, 'text': 'Example Systems'},
                'job_evidence': {'source_url': job, 'text': 'Example Systems — Data Architect — Apply now'},
                'recipient': {'email': 'jobs@example.com', 'name': 'Recruiting', 'kind': 'recruiting',
                              'evidence': {'source_url': canonical_company,
                                           'text': 'Recruiting: jobs@example.com'},
                              'reason': 'Published recruiting inbox'},
                'subject': 'Application: Data Architect - Pranav Modi',
                'body_text': f'Hello, I am applying for this role. My resume is attached.\n\nRole: {job}',
                'fit_reason': 'Relevant data architecture experience.', 'gaps': []}}
        assert mode == 'audit_email'
        return {'approved': True, 'reason': 'Evidence is complete.'}

    monkeypatch.setattr(research, 'fetch_page', fetch)
    monkeypatch.setattr(research, 'load_possibleos_contacts', AsyncMock(return_value=[]))
    result = await research.research_application(application, model)
    assert result['evidence']['company']['source_url'] == canonical_company


@pytest.mark.asyncio
async def test_research_accepts_a_different_official_company_page_than_discovery(
        monkeypatch, verified_job_identity):
    job = 'https://nodesk.co/remote-jobs/example-business-process-engineer/'
    company = 'https://example.com/'
    about = 'https://example.com/about'
    contact = 'https://example.com/contact'
    application = {
        'posting': {
            'firm_id': 'firm-1', 'title': 'Business Process Engineer',
            'firm_name': 'Example Systems', 'website': 'example.com',
            'source_url': job, 'employer_evidence_url': about,
            'role_evidence': {
                'source_url': job,
                'text': 'Example Systems — Business Process Engineer — Apply now',
            },
        },
        'resume': {'text': 'PRANAV MODI\nFounder, Possible Minds'},
        'preferences': {},
    }

    async def fetch(url, **_kwargs):
        content = {
            job: 'Example Systems — Business Process Engineer — Apply now',
            company: 'Example Systems official website',
            about: 'Example Systems builds healthcare workflow software.',
            contact: 'Contact Example Systems at hello@example.com',
        }[url]
        return {'requested_url': url, 'final_url': url, 'http_status': 200, 'content': content}

    async def model(mode, payload, _fields):
        if mode == 'discover_contacts':
            return {'company_url': company, 'contact_urls': [contact],
                    'job_urls': [], 'summary': 'Example'}
        if mode == 'compose':
            return {'blocked_reason': None, 'packet': {
                'company_summary': 'Example Systems builds healthcare workflow software.',
                'company_evidence': {
                    'source_url': about,
                    'text': 'Example Systems builds healthcare workflow software.',
                },
                'job_evidence': {
                    'source_url': job,
                    'text': 'Example Systems is hiring a business-process specialist.',
                },
                'recipient': {
                    'email': 'hello@example.com', 'name': 'Example Systems',
                    'kind': 'routing',
                    'evidence': {
                        'source_type': 'public_page', 'source_url': contact,
                        'text': 'Contact Example Systems at hello@example.com',
                        'contact_id': None, 'source_name': None, 'observed_at': None,
                    },
                    'reason': 'Published official routing inbox.',
                },
                'subject': 'Application: Business Process Engineer - Pranav Modi',
                'body_text': (
                    'Hello, I am applying for the Business Process Engineer role. '
                    f'My resume is attached.\n\nRole: {job}'
                ),
                'fit_reason': 'Relevant workflow automation experience.', 'gaps': [],
            }}
        assert mode == 'audit_email'
        return {'approved': True, 'reason': 'Evidence is complete.'}

    monkeypatch.setattr(research, 'fetch_page', fetch)
    monkeypatch.setattr(research, 'load_possibleos_contacts', AsyncMock(return_value=[]))

    result = await research.research_application(application, model)

    assert result['evidence']['company']['source_url'] == about
    assert result['evidence']['job']['text'] == (
        'Example Systems — Business Process Engineer — Apply now'
    )
    assert result['evidence']['stored_evidence_recoveries'] == ['job']
    assert result['recipient']['email'] == 'hello@example.com'


@pytest.mark.asyncio
async def test_research_uses_imported_company_evidence_when_homepage_is_blocked(
        monkeypatch, verified_job_identity):
    job = 'https://www.linkedin.com/jobs/view/123'
    discovered_company = 'https://example.com'
    canonical_company = 'https://example.com/'
    imported_evidence = (
        'https://example.com/wp-json/wp/v2/pages?slug=about&_fields=link%2Ctitle%2Ccontent'
    )
    contact = {
        'contact_id': 'contact-1', 'firm_id': 'firm-1', 'email': 'recruiting@example.com',
        'name': 'Example Recruiting', 'title': 'Recruiting', 'kind': 'recruiting',
        'source': 'job_search', 'observed_at': '2026-09-23T00:00:00+00:00', 'score': 100,
        'evidence': {
            'source_type': 'possibleos_contact',
            'source_url': 'possibleos://firm-contacts/contact-1',
            'text': 'Example Recruiting | Recruiting | recruiting@example.com',
            'contact_id': 'contact-1', 'source_name': 'job_search',
            'observed_at': '2026-09-23T00:00:00+00:00',
        },
    }
    application = {
        'posting': {'firm_id': 'firm-1', 'title': 'Senior Product Manager',
                    'firm_name': 'Example Systems', 'website': 'example.com',
                    'source_url': job, 'employer_evidence_url': imported_evidence},
        'resume': {'text': 'PRANAV MODI\nFounder, Possible Minds'},
        'preferences': {},
    }

    async def fetch(url, **_kwargs):
        if url in {discovered_company, canonical_company}:
            raise RuntimeError('unverified HTTP 403')
        if url == imported_evidence:
            return {'requested_url': url, 'final_url': url, 'http_status': 200,
                    'content': 'Example Systems official company page'}
        return {'requested_url': url, 'final_url': url, 'http_status': 200,
                'content': 'Example Systems — Senior Product Manager — Apply now'}

    async def model(mode, payload, _fields):
        if mode == 'discover_contacts':
            return {'company_url': discovered_company, 'contact_urls': [],
                    'job_urls': [], 'summary': 'Example'}
        if mode == 'compose':
            assert payload['company_url'] == imported_evidence
            assert payload['possibleos_contacts'] == [contact]
            return {'blocked_reason': None, 'packet': {
                'company_summary': 'Example Systems builds software.',
                'company_evidence': {'source_url': imported_evidence,
                                     'text': 'Example Systems official company page'},
                'job_evidence': {'source_url': job,
                                 'text': 'Example Systems — Senior Product Manager — Apply now'},
                'recipient': {'email': contact['email'], 'name': contact['name'],
                              'kind': 'recruiting', 'evidence': contact['evidence'],
                              'reason': 'Verified employer-domain recruiting contact.'},
                'subject': 'Application: Senior Product Manager - Pranav Modi',
                'body_text': f'Hello, I am applying for this role. My resume is attached.\n\nRole: {job}',
                'fit_reason': 'Relevant product leadership experience.', 'gaps': []}}
        assert mode == 'audit_email'
        return {'approved': True, 'reason': 'Evidence is complete.'}

    monkeypatch.setattr(research, 'fetch_page', fetch)
    monkeypatch.setattr(research, 'load_possibleos_contacts', AsyncMock(return_value=[contact]))
    result = await research.research_application(application, model)
    assert result['evidence']['company']['source_url'] == imported_evidence
    assert result['recipient']['email'] == 'recruiting@example.com'


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv('JOB_AGENT_DB_TESTS') != '1', reason='Requires isolated schema on local PostgreSQL')
async def test_classification_override_and_prepare_send_intent(monkeypatch, tmp_path):
    import shutil
    from sqlalchemy import text, select
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.db import async_engine as configured_engine
    from sqlalchemy.pool import NullPool
    async_engine = create_async_engine(configured_engine.url, poolclass=NullPool)
    for category in resumes.default_categories():
        source = resumes.resolve_resume(category.resume_path)
        destination = tmp_path / category.resume_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    monkeypatch.setattr(resumes, 'RESUME_ROOT', tmp_path)
    monkeypatch.setattr(processing, 'RESUME_ROOT', tmp_path)
    schema = 'job_processing_test_' + uuid4().hex
    async with async_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(async_engine.url, connect_args={'server_settings': {'search_path': schema}})
    monkeypatch.setattr(core, 'async_engine', engine)
    monkeypatch.setattr(core, 'AsyncSessionLocal', async_sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr(core, '_ready', False)
    try:
        await core.ensure_tables()
        async with core.AsyncSessionLocal() as session:
            for identity, title in [('engineer', 'AI Agent Engineer'), ('admin', 'Receptionist'), ('ambiguous', 'Operations Lead')]:
                session.add(core.JobAgentCandidate(id=identity, posting={'firm_id': 'example', 'firm_name': 'Example', 'title': title,
                    'source_url': 'https://example.com/jobs/' + identity, 'description_summary': title}, status='new', note='Preserved', revision=1))
            await session.commit()
        await processing.enqueue_missing()
        async def model(mode, payload, fields):
            return {'decisions': [{'candidate_id': job['candidate_id'], 'category_id': 'ai_automation' if job['candidate_id'] != 'admin' else None,
                'confidence': 0.95 if job['candidate_id'] == 'engineer' else 0.5, 'reason': 'Description-based match', 'tags': []} for job in payload['jobs']]}
        monkeypatch.setattr(processing, 'ask_model', model)
        # Automatic bulk classification is off by default. An operator request
        # marks only the selected job, and the worker handles that one record.
        assert not await processing.classify_batch()
        requested = await processing.request_classification('engineer')
        assert requested['classification']['status'] == 'pending'
        assert await processing.classify_batch(requested_only=True)
        engineer = await processing.detail('engineer')
        assert engineer['classification']['status'] == 'classified'
        assert engineer['classification']['resume']['path'].endswith('AI_Agents_Automation.pdf')
        assert (await processing.detail('admin'))['classification']['status'] == 'pending'
        assert (await processing.detail('ambiguous'))['classification']['status'] == 'pending'
        assert (await core.candidates(category='ai_automation'))['total'] == 1
        with pytest.raises(ValueError, match='category'):
            admin = await processing.detail('admin')
            await processing.request_application('admin', processing.ApplicationRequest(revision=admin['processing_revision'], mode='send'))
        admin = await processing.choose_category('admin', processing.CategoryChoice(revision=admin['processing_revision'], category_id='technical_product'))
        assert admin['classification']['source'] == 'operator'
        with pytest.raises(ValueError, match='changed'):
            await processing.choose_category('admin', processing.CategoryChoice(revision=1, category_id='data_ml'))
        # A prepared draft never grants permission to send.
        prepared_request = await processing.request_application('engineer', processing.ApplicationRequest(revision=engineer['processing_revision'], mode='prepare'))
        async with core.AsyncSessionLocal() as session:
            row = await session.get(processing.JobProcessing, 'engineer')
            assert row.application['send_requested'] is False and row.application['authorized_at'] is None
        assert prepared_request['application']['status'] == 'queued'
        # Concurrent/repeated apply clicks coalesce without upgrading a draft silently.
        repeated = await processing.request_application('engineer', processing.ApplicationRequest(revision=engineer['processing_revision'], mode='send'))
        assert repeated['application']['status'] == 'queued'
        async with core.AsyncSessionLocal() as session:
            row = await session.get(processing.JobProcessing, 'engineer')
            assert row.application['send_requested'] is False
            row.application_status = 'ready'
            await session.commit()
        current = await processing.detail('engineer')
        queued = await processing.request_application('engineer', processing.ApplicationRequest(revision=current['processing_revision'], mode='send'))
        assert queued['application']['status'] == 'queued_send'
        async with core.AsyncSessionLocal() as session:
            row = await session.get(processing.JobProcessing, 'engineer')
            assert row.application['send_requested'] is True and row.application['authorized_at']
        assert (await processing.detail('engineer'))['note'] == 'Preserved'
        # Exercise preparation -> ready -> explicit send -> verified, with external I/O mocked.
        email = {'from': 'pranav@possiblemindshq.com', 'to': 'jobs@example.com', 'subject': 'Application: AI Agent Engineer', 'body_text': 'Hello, my resume is attached.'}
        monkeypatch.setattr(research, 'research_application', AsyncMock(return_value={'email': email, 'recipient': {'email': email['to']}, 'fit_reason': 'Relevant automation experience'}))
        monkeypatch.setattr(processing, 'duplicate_evidence', AsyncMock(return_value=None))
        sends = []
        monkeypatch.setattr(mail, 'send_cli', lambda *args: sends.append(args) or {'accepted': True})
        monkeypatch.setattr(mail, 'verify_sent', lambda *args: {'uid': 'verified', 'attachment_sha256': args[1]})
        async with core.AsyncSessionLocal() as session:
            row = await session.get(processing.JobProcessing, 'engineer')
            row.application_status = 'queued'
            row.application = {**row.application, 'send_requested': False, 'authorized_at': None}
            await session.commit()
        assert await processing.process_application()
        prepared = await processing.detail('engineer')
        assert prepared['application']['status'] == 'ready' and sends == []
        attachment_path = prepared['application']['attachment']['path']
        assert (tmp_path / attachment_path).is_file()
        assert (await processing.request_application('engineer', processing.ApplicationRequest(revision=prepared['processing_revision'], mode='send')))['application']['status'] == 'queued_send'
        assert await processing.process_application()
        assert (await processing.detail('engineer'))['application']['status'] == 'sent_verified'
        assert len(sends) == 1
        assert (await processing.request_application('engineer', processing.ApplicationRequest(revision=1, mode='send')))['application']['status'] == 'sent_verified'
        assert not await processing.process_application()
        assert len(sends) == 1

        # New jobs are enqueued without touching already-classified rows.
        async with core.AsyncSessionLocal() as session:
            session.add(core.JobAgentCandidate(id='new', posting={'title': 'Engineer'}, status='new', note='', revision=1))
            await session.commit()
        await processing.enqueue_missing()
        assert (await processing.detail('new'))['classification']['status'] == 'pending'
        assert (await processing.detail('admin'))['classification']['source'] == 'operator'
    finally:
        await engine.dispose()
        async with async_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await async_engine.dispose()


def test_resume_selection_ignores_legacy_confidence_threshold():
    from types import SimpleNamespace
    from app.services.job_agent import JobAgentConfig
    config = JobAgentConfig(classification_threshold=1.0)
    row = SimpleNamespace(classification_status='classified', classification={
        'source':'model', 'category_id':config.resume_categories[0].id, 'confidence':0.01})
    assert processing.classification_view(row, config)['status'] == 'classified'


def test_best_resume_skips_unmapped_category_and_preserves_ranking():
    categories = resumes.default_categories()[:2]
    categories[0].resume_path = ''
    response = {'model':'jev-test','answers':{'job_0':{
        'type':'choice', 'choice':categories[0].id, 'confidence':0.7,
        'probabilities':{categories[0].id:0.7,categories[1].id:0.2,processing.JEV_NO_MATCH:0.1}}}}
    result = processing._parse_jev_decisions(response, ['job'], categories)[0]
    assert result.category_id == categories[1].id
    assert 'Closest available resume' in result.reason
    categories[1].resume_path = ''
    with pytest.raises(ValueError, match='Assign a resume PDF'):
        processing._parse_jev_decisions(response, ['job'], categories)
