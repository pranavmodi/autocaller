"""Evidence-backed recipient discovery and application composition."""
from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from app.services.career_search_web import fetch_page


logger = logging.getLogger(__name__)

# Alternate pages may corroborate a role when the imported source blocks a
# direct fetch. Keep this list to established job platforms; the employer's
# own domain is accepted separately after company identity is verified.
TRUSTED_JOB_HOSTS = {
    'applytojob.com',
    'ashbyhq.com',
    'bamboohr.com',
    'greenhouse.io',
    'icims.com',
    'indeed.com',
    'jobvite.com',
    'jobs.ca',
    'lever.co',
    'linkedin.com',
    'myworkdayjobs.com',
    'smartrecruiters.com',
    'startup.jobs',
    'ultipro.ca',
    'workable.com',
    'workdayjobs.com',
}


class Evidence(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_url: str
    text: str = Field(min_length=3, max_length=2500)


class Recipient(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(pattern=r'^[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$', max_length=320)
    name: str
    kind: str = Field(pattern=r'^(recruiting|routing)$')
    evidence: Evidence
    reason: str


class Packet(BaseModel):
    model_config = ConfigDict(extra='forbid')
    company_summary: str
    company_evidence: Evidence
    job_evidence: Evidence
    recipient: Recipient
    subject: str = Field(min_length=1, max_length=240)
    body_text: str = Field(min_length=30, max_length=6000)
    fit_reason: str
    gaps: list[str]


class Discovery(BaseModel):
    model_config = ConfigDict(extra='ignore')
    company_url: str
    contact_urls: list[str] = Field(default_factory=list, max_length=10)
    job_urls: list[str] = Field(default_factory=list, max_length=5)
    summary: str = ''


def host(url):
    return (urlsplit(url).hostname or '').lower().removeprefix('www.')


def normalized(value):
    value = unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore').decode()
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', value.casefold()).split())


def trusted_job_host(url, official_host):
    value = host(url)
    if value == official_host or value.endswith('.' + official_host):
        return True
    return any(value == allowed or value.endswith('.' + allowed) for allowed in TRUSTED_JOB_HOSTS)


def validate_job_page(page, posting):
    content = normalized(page['content'])
    title = normalized(posting['title'])
    if title not in content:
        raise ValueError('The corroborating page does not identify the same job title.')
    firm = str(posting.get('firm_name') or '').split(' - ', 1)[0]
    ignored = {'llp', 'llc', 'inc', 'limited', 'ltd', 'corp', 'corporation', 'company', 'private', 'plc'}
    firm_tokens = [token for token in normalized(firm).split() if token not in ignored]
    required = min(2, len(firm_tokens))
    if required and sum(token in content.split() for token in firm_tokens) < required:
        raise ValueError('The corroborating page does not identify the same employer.')
    return page


def validate_evidence(evidence, pages):
    page = next((p for p in pages if p['requested_url'] == evidence.source_url), None)
    if not page or page['http_status'] != 200 or ' '.join(evidence.text.split()) not in ' '.join(page['content'].split()):
        raise ValueError('A contact or job claim could not be verified against its source page.')
    return page


async def research_application(application, ask_model):
    posting = application['posting']
    discoveries = Discovery.model_validate(await ask_model(
        'discover_contacts', {'job': posting}, ['company_url', 'contact_urls', 'job_urls']))
    company_url = discoveries.company_url
    expected_host = host(posting.get('website') or '')
    if expected_host and host(company_url) != expected_host:
        raise ValueError('The research returned a different company website. Verify employer identity before applying.')

    canonical_job_url = posting['source_url']
    job_urls = list(dict.fromkeys([canonical_job_url, *discoveries.job_urls]))
    urls = list(dict.fromkeys([*job_urls, company_url, *discoveries.contact_urls]))

    async def read(url):
        try:
            return await asyncio.wait_for(fetch_page(url, attempts=2), timeout=60)
        except Exception as exc:
            logger.warning('Job application source fetch failed for %s: %s', url, exc)
            return {'requested_url': url, 'error': f'{type(exc).__name__}: {exc}'[:500]}

    results = await asyncio.gather(*(read(url) for url in urls))
    pages = [result for result in results if 'http_status' in result]
    fetch_failures = [result for result in results if 'error' in result]
    successful_job_pages = [page for page in pages if page['requested_url'] in job_urls and page['http_status'] == 200]
    if not successful_job_pages:
        statuses = [f"{host(page['requested_url'])}: HTTP {page['http_status']}" for page in pages
                    if page['requested_url'] in job_urls]
        failures = [f"{host(item['requested_url'])}: {item['error']}" for item in fetch_failures
                    if item['requested_url'] in job_urls]
        detail = '; '.join(statuses + failures)
        raise ValueError('The job source and corroborating role pages could not be verified.' +
                         (f' Fetch results: {detail}' if detail else ''))

    result = await ask_model('compose', {'job': posting, 'pages': pages, 'company_url': company_url,
        'job_urls': job_urls, 'source_fetch_failures': fetch_failures,
        'resume': application['resume']['text'], 'preferences': application['preferences']}, ['packet', 'blocked_reason'])
    if result.get('blocked_reason') or not result.get('packet'):
        raise ValueError(str(result.get('blocked_reason') or 'No suitable verified application contact was found.'))
    packet = Packet.model_validate(result['packet'])
    company_page = validate_evidence(packet.company_evidence, pages)
    if expected_host and host(company_page['final_url']) != expected_host:
        raise ValueError('The company page redirected to another domain. Verify the employer before applying.')
    if packet.company_evidence.source_url != company_url:
        raise ValueError('Company identity must be established by its official page.')
    role_page = validate_evidence(packet.job_evidence, pages)
    if packet.job_evidence.source_url not in job_urls:
        raise ValueError('The current job was not established by a researched role page.')
    if packet.job_evidence.source_url != canonical_job_url and not trusted_job_host(
            packet.job_evidence.source_url, host(company_page['final_url'])):
        raise ValueError('The alternate job source is not an employer page or trusted job platform.')
    validate_job_page(role_page, posting)
    contact_page = validate_evidence(packet.recipient.evidence, pages)
    official_host = host(company_page['final_url'])
    contact_host = host(contact_page['final_url'])
    if not (contact_host == official_host or contact_host.endswith('.' + official_host) or packet.recipient.evidence.source_url == posting['source_url']):
        raise ValueError('The recipient must be published on the verified company website.')
    if packet.recipient.email.casefold() not in packet.recipient.evidence.text.casefold():
        raise ValueError('The recipient email is not present in its published evidence.')
    if '\r' in packet.subject or '\n' in packet.subject or 'tailored' in packet.body_text.casefold():
        raise ValueError('The application wording needs correction.')
    if posting['source_url'] not in packet.body_text:
        packet.body_text += '\n\nRole: ' + posting['source_url']
    audit = await ask_model('audit_email', {'packet': packet.model_dump(), 'resume': application['resume']['text'],
        'pages': pages, 'preferences': application['preferences']}, ['approved', 'reason'])
    if audit['approved'] is not True:
        raise ValueError('Application needs review: ' + str(audit['reason']))
    return {'email': {'from': 'pranav@possiblemindshq.com', 'to': packet.recipient.email,
                      'subject': packet.subject, 'body_text': packet.body_text},
            'recipient': packet.recipient.model_dump(), 'company_summary': packet.company_summary,
            'fit_reason': packet.fit_reason, 'gaps': packet.gaps,
            'evidence': {'company': packet.company_evidence.model_dump(), 'job': packet.job_evidence.model_dump(),
                         'canonical_job_url': canonical_job_url, 'source_fetch_failures': fetch_failures,
                         'audit': audit, 'checked_at': datetime.now(timezone.utc).isoformat()}}
