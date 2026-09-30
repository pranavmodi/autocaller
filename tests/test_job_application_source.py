from unittest.mock import AsyncMock

import pytest

from app.services import job_application_source as source


@pytest.mark.asyncio
async def test_resolver_selects_only_fetched_exact_official_page(monkeypatch):
    model = AsyncMock(side_effect=[
        ({'candidates': [{'url': 'https://jobs.fixture.example/roles/ai-engineer',
                          'reason': 'Exact official ATS result.'}]}, {'provider': 'fixture'}),
        ({'matched': True,
          'selected_url': 'https://jobs.fixture.example/roles/ai-engineer',
          'evidence_url': 'https://jobs.fixture.example/roles/ai-engineer',
          'source_type': 'ats',
          'match_scope': 'direct_role',
          'exact_role_quote': 'Agentic AI Engineer',
          'exact_employer_quote': 'Fixture Employer',
          'exact_application_quote': 'Apply for this job',
          'reason': 'The ATS page identifies the exact employer and role.',
          'confidence': 0.98}, {'provider': 'fixture'}),
    ])
    fetch = AsyncMock(return_value={
        'final_url': 'https://jobs.fixture.example/roles/ai-engineer',
        'http_status': 200,
        'content': 'Fixture Employer\nAgentic AI Engineer\nApply for this job',
    })
    monkeypatch.setattr(source, '_model', model)
    monkeypatch.setattr(source, 'fetch_page', fetch)
    result = await source.resolve_official_application_source({
        'firm_name': 'Fixture Employer', 'title': 'Agentic AI Engineer',
        'location': 'Remote - Colombia', 'source_url': 'https://linkedin.example/jobs/1',
    }, provider='openai', model='fixture-model')
    assert result['source_type'] == 'ats'
    assert result['url'] == 'https://jobs.fixture.example/roles/ai-engineer'
    assert result['evidence']['application'] == 'Apply for this job'


@pytest.mark.asyncio
async def test_resolver_rejects_unquoted_model_evidence(monkeypatch):
    monkeypatch.setattr(source, '_model', AsyncMock(side_effect=[
        ({'candidates': [{'url': 'https://jobs.fixture.example/roles/other',
                          'reason': 'Possible result.'}]}, {}),
        ({'matched': True, 'selected_url': 'https://jobs.fixture.example/roles/other',
          'evidence_url': 'https://jobs.fixture.example/roles/other',
          'source_type': 'ats', 'match_scope': 'direct_role',
          'exact_role_quote': 'Different title',
          'exact_employer_quote': 'Fixture Employer',
          'exact_application_quote': 'Apply', 'reason': 'Possible match.',
          'confidence': 0.51}, {}),
    ]))
    monkeypatch.setattr(source, 'fetch_page', AsyncMock(return_value={
        'final_url': 'https://jobs.fixture.example/roles/other', 'http_status': 200,
        'content': 'Fixture Employer\nAgentic AI Engineer\nApply',
    }))
    with pytest.raises(ValueError, match='role evidence'):
        await source.resolve_official_application_source({
            'firm_name': 'Fixture Employer', 'title': 'Agentic AI Engineer',
            'source_url': 'https://linkedin.example/jobs/1',
        }, provider='gateway', model='fixture-model')


@pytest.mark.asyncio
async def test_resolver_accepts_only_employer_linked_official_jobs_portal(monkeypatch):
    portal = 'https://talent.fixture.example/jobs'
    employer = 'https://fixture.example/careers'
    monkeypatch.setattr(source, '_model', AsyncMock(side_effect=[
        ({'candidates': [{'url': employer, 'reason': 'Official careers page.'},
                         {'url': portal, 'reason': 'Employer-linked jobs portal.'}]}, {}),
        ({'matched': True, 'selected_url': portal, 'evidence_url': employer,
          'source_type': 'ats', 'match_scope': 'official_jobs_portal',
          'exact_role_quote': '', 'exact_employer_quote': 'Fixture Employer',
          'exact_application_quote': 'Browse Open Positions',
          'reason': 'The employer careers page links to its searchable jobs portal.',
          'confidence': 0.94}, {}),
    ]))
    async def fetch(url, attempts=1):
        content = (f'Fixture Employer Browse Open Positions Links: {portal}'
                   if url == employer else 'Open jobs')
        return {'final_url': url, 'http_status': 200, 'content': content}
    monkeypatch.setattr(source, 'fetch_page', fetch)
    result = await source.resolve_official_application_source({
        'firm_name': 'Fixture Employer', 'title': 'Agentic AI Engineer',
        'source_url': 'https://linkedin.example/jobs/1',
    }, provider='openai', model='fixture-model')
    assert result['url'] == portal
    assert result['match_scope'] == 'official_jobs_portal'


@pytest.mark.asyncio
async def test_resolver_accepts_employer_owned_app_subdomain_without_literal_link(monkeypatch):
    portal = 'https://app.fixture.example/jobs'
    employer = 'https://fixture.example/careers'
    monkeypatch.setattr(source, '_model', AsyncMock(side_effect=[
        ({'candidates': [{'url': employer, 'reason': 'Official careers page.'},
                         {'url': portal, 'reason': 'Employer-owned jobs app.'}]}, {}),
        ({'matched': True, 'selected_url': portal, 'evidence_url': employer,
          'source_type': 'ats', 'match_scope': 'official_jobs_portal',
          'exact_role_quote': '', 'exact_employer_quote': 'Fixture Employer',
          'exact_application_quote': 'Browse Open Positions',
          'reason': 'The employer careers page identifies its jobs flow.',
          'confidence': 0.90}, {}),
    ]))

    async def fetch(url, attempts=1):
        content = ('Fixture Employer Browse Open Positions'
                   if url == employer else 'Fixture Employer jobs application')
        return {'final_url': url, 'http_status': 200, 'content': content}

    monkeypatch.setattr(source, 'fetch_page', fetch)
    result = await source.resolve_official_application_source({
        'firm_name': 'Fixture Employer', 'title': 'Agentic AI Engineer',
        'website': 'fixture.example',
        'employer_evidence_url': 'https://fixture.example/',
        'source_url': 'https://linkedin.example/jobs/1',
    }, provider='openai', model='fixture-model')
    assert result['url'] == portal
    assert result['match_scope'] == 'official_jobs_portal'


@pytest.mark.asyncio
async def test_resolver_still_rejects_unlinked_third_party_portal(monkeypatch):
    portal = 'https://unlinked-ats.example/jobs'
    employer = 'https://fixture.example/careers'
    monkeypatch.setattr(source, '_model', AsyncMock(side_effect=[
        ({'candidates': [{'url': employer, 'reason': 'Official careers page.'},
                         {'url': portal, 'reason': 'Unlinked portal.'}]}, {}),
        ({'matched': True, 'selected_url': portal, 'evidence_url': employer,
          'source_type': 'ats', 'match_scope': 'official_jobs_portal',
          'exact_role_quote': '', 'exact_employer_quote': 'Fixture Employer',
          'exact_application_quote': 'Browse Open Positions',
          'reason': 'Possible portal.', 'confidence': 0.70}, {}),
    ]))

    async def fetch(url, attempts=1):
        content = ('Fixture Employer Browse Open Positions'
                   if url == employer else 'Possible jobs portal')
        return {'final_url': url, 'http_status': 200, 'content': content}

    monkeypatch.setattr(source, 'fetch_page', fetch)
    with pytest.raises(ValueError, match='did not link'):
        await source.resolve_official_application_source({
            'firm_name': 'Fixture Employer', 'title': 'Agentic AI Engineer',
            'website': 'fixture.example',
            'employer_evidence_url': 'https://fixture.example/',
            'source_url': 'https://linkedin.example/jobs/1',
        }, provider='openai', model='fixture-model')
