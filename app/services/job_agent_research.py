"""Evidence-backed recipient discovery and application composition."""
from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Literal
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


class RecipientEvidence(Evidence):
    source_type: Literal['public_page', 'possibleos_contact'] = 'public_page'
    contact_id: str | None = None
    source_name: str | None = None
    observed_at: str | None = None


class Recipient(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(pattern=r'^[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$', max_length=320)
    name: str
    kind: str = Field(pattern=r'^(recruiting|routing)$')
    evidence: RecipientEvidence
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


def website_host(value):
    """Normalize stored bare domains and full website URLs to a hostname."""
    value = str(value or '').strip()
    if not value:
        return ''
    parsed = urlsplit(value if '://' in value else '//' + value)
    return (parsed.hostname or '').lower().removeprefix('www.')


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


EMAIL_PATTERN = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
BLOCKED_MAILBOXES = {
    'abuse', 'accessibility', 'accommodation', 'accommodations', 'billing',
    'compliance', 'intake', 'intakes', 'legal', 'litigation', 'media',
    'medicalrecords', 'noreply', 'no-reply', 'patients', 'patient', 'press',
    'privacy', 'records', 'security',
}
RECRUITING_TERMS = (
    'recruit', 'talent', 'human resources', 'people operations', 'people and culture',
    'hiring',
)
ROUTING_TERMS = (
    'chief operating', 'coo', 'firm administrator', 'office administrator',
    'office manager', 'executive director', 'managing partner', 'founder', 'owner',
    'president', 'operations director', 'operations manager',
)
RECRUITING_MAILBOXES = {'careers', 'career', 'jobs', 'job', 'recruiting', 'recruitment', 'talent', 'hr', 'people'}
ROUTING_MAILBOXES = {'contact', 'hello', 'info', 'office', 'admin', 'administration'}


def organization_domain_matches(email, official_host):
    """Require an address on the verified employer domain or its subdomain."""
    if not EMAIL_PATTERN.fullmatch(str(email or '').strip()) or not official_host:
        return False
    email_host = str(email).rsplit('@', 1)[1].casefold().rstrip('.')
    official_host = website_host(official_host)
    return bool(official_host) and (
        email_host == official_host
        or email_host.endswith('.' + official_host)
        or official_host.endswith('.' + email_host)
    )


def _contact_value(contact, key, default=None):
    return contact.get(key, default) if isinstance(contact, dict) else getattr(contact, key, default)


def _possibleos_contact_kind(contact):
    email = str(_contact_value(contact, 'email') or '').strip().casefold()
    local = email.rsplit('@', 1)[0]
    title = normalized(_contact_value(contact, 'research_title') or _contact_value(contact, 'title') or '')
    local_token = re.sub(r'[^a-z0-9-]+', '', local)
    if local_token in BLOCKED_MAILBOXES or any(term in title for term in (
            'medical record', 'patient coordinator', 'media relation', 'privacy', 'security')):
        return None
    if local_token in RECRUITING_MAILBOXES or any(term in title for term in RECRUITING_TERMS):
        return 'recruiting', 100
    if local_token in ROUTING_MAILBOXES or any(term in title for term in ROUTING_TERMS):
        return 'routing', 75
    return None


def rank_possibleos_contacts(contacts, official_host, allowed_firm_ids):
    """Return bounded, deduplicated employer-domain contacts safe for routing.

    Possible OS has historical and third-party addresses attached to some firms.
    Firm identity, official email domain and role suitability are therefore hard
    filters; model judgment is used only after this deterministic boundary.
    """
    allowed_firm_ids = {str(value) for value in allowed_firm_ids if value}
    ranked = []
    source_scores = {'front': 12, 'pif_research': 10, 'pif_leadership': 8, 'pif_contacts': 6, 'manual': 4}
    for contact in contacts:
        firm_id = str(_contact_value(contact, 'pif_id') or '')
        email = str(_contact_value(contact, 'email') or '').strip()
        if firm_id not in allowed_firm_ids or not organization_domain_matches(email, official_host):
            continue
        kind_and_score = _possibleos_contact_kind(contact)
        if not kind_and_score:
            continue
        kind, role_score = kind_and_score
        contact_id = str(_contact_value(contact, 'id') or '')
        if not contact_id:
            continue
        name = str(_contact_value(contact, 'full_name') or '').strip()
        title = str(_contact_value(contact, 'research_title') or _contact_value(contact, 'title') or '').strip()
        source = str(_contact_value(contact, 'source') or 'unknown').strip()
        observed = _contact_value(contact, 'front_last_seen') or _contact_value(contact, 'updated_at')
        observed_at = observed.isoformat() if hasattr(observed, 'isoformat') else (str(observed) if observed else None)
        display_name = name or ('Recruiting' if kind == 'recruiting' else 'Office')
        evidence_text = ' | '.join(value for value in (display_name, title, email) if value)
        ranked.append({
            'contact_id': contact_id,
            'firm_id': firm_id,
            'email': email,
            'name': display_name,
            'title': title,
            'kind': kind,
            'source': source,
            'observed_at': observed_at,
            'score': role_score + source_scores.get(source, 0),
            'evidence': {
                'source_type': 'possibleos_contact',
                'source_url': f'possibleos://firm-contacts/{contact_id}',
                'text': evidence_text,
                'contact_id': contact_id,
                'source_name': source,
                'observed_at': observed_at,
            },
        })
    ranked.sort(key=lambda item: (item['score'], item['observed_at'] or '', item['name'].casefold()), reverse=True)
    unique = {}
    for item in ranked:
        unique.setdefault(item['email'].casefold(), item)
    return list(unique.values())[:12]


async def load_possibleos_contacts(posting, official_host):
    """Read contacts for the stored employer and any exact-domain canonical twin."""
    firm_id = str(posting.get('firm_id') or '').strip()
    official_host = website_host(official_host)
    if not firm_id or not official_host:
        return []
    from sqlalchemy import or_, select
    from app.db import AsyncSessionLocal
    from app.db.models import FirmContactRow, PifFirmRow

    async with AsyncSessionLocal() as session:
        pattern = f'%{official_host}%'
        firms = (await session.scalars(select(PifFirmRow).where(or_(
            PifFirmRow.id == firm_id,
            PifFirmRow.canonical_website.ilike(pattern),
            PifFirmRow.website.ilike(pattern),
        )))).all()
        allowed_ids = {firm_id}
        for firm in firms:
            source_json = firm.source_json if isinstance(firm.source_json, dict) else {}
            if firm.id == firm_id or any(website_host(value) == official_host for value in (
                    firm.canonical_website, firm.website)):
                allowed_ids.add(firm.id)
            if firm.id == firm_id and source_json.get('merged_into'):
                allowed_ids.add(str(source_json['merged_into']))
        merged = (await session.scalars(select(PifFirmRow).where(
            PifFirmRow.source_json['merged_into'].astext.in_(allowed_ids)
        ))).all()
        allowed_ids.update(firm.id for firm in merged)
        contacts = (await session.scalars(select(FirmContactRow).where(
            FirmContactRow.pif_id.in_(allowed_ids),
            FirmContactRow.email.isnot(None),
        ))).all()
    return rank_possibleos_contacts(contacts, official_host, allowed_ids)


def evidence_present(excerpt, content):
    """Verify quoted fragments and addresses without requiring display order.

    Public profile pages commonly render the address in a header and the related
    role description below it. A model may cite those exact passages together,
    separated by an ellipsis, even though their flattened page order differs.
    Every supplied fragment still has to appear verbatim after conservative text
    normalization, and every cited email has to be present exactly.
    """
    addresses = EMAIL_PATTERN.findall(excerpt)
    if any(address.casefold() not in content.casefold() for address in addresses):
        return False
    without_addresses = EMAIL_PATTERN.sub(' ', excerpt)
    fragments = [normalized(fragment) for fragment in re.split(r'(?:\.{3,}|…)', without_addresses)]
    fragments = [fragment for fragment in fragments if fragment]
    normalized_content = normalized(content)
    return bool(addresses or fragments) and all(fragment in normalized_content for fragment in fragments)


def published_email(address, content):
    return address.casefold() in content.casefold()


def validate_evidence(evidence, pages, label='Evidence'):
    page = next((p for p in pages if p['requested_url'] == evidence.source_url), None)
    if not page or page['http_status'] != 200:
        raise ValueError(f'{label} source page could not be verified.')
    if not evidence_present(evidence.text, page['content']):
        raise ValueError(f'{label} excerpt could not be verified against its source page.')
    return page


async def research_application(application, ask_model, update_phase=None):
    posting = application['posting']
    discoveries = Discovery.model_validate(await ask_model(
        'discover_contacts', {'job': posting}, ['company_url', 'contact_urls', 'job_urls']))
    company_url = discoveries.company_url
    expected_host = website_host(posting.get('website') or '')
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

    fetched_company_page = next((page for page in pages
        if page['requested_url'] == company_url and page['http_status'] == 200), None)
    possibleos_contacts = []
    possibleos_contact_error = None
    if fetched_company_page:
        try:
            possibleos_contacts = await load_possibleos_contacts(
                posting, host(fetched_company_page.get('final_url') or company_url))
        except Exception as exc:
            logger.warning('Possible OS contact lookup failed for %s: %s', posting.get('firm_id'), exc)
            possibleos_contact_error = f'{type(exc).__name__}: {exc}'[:500]

    result = await ask_model('compose', {'job': posting, 'pages': pages, 'company_url': company_url,
        'job_urls': job_urls, 'source_fetch_failures': fetch_failures,
        'possibleos_contacts': possibleos_contacts, 'possibleos_contact_error': possibleos_contact_error,
        'resume': application['resume']['text'], 'preferences': application['preferences']}, ['packet', 'blocked_reason'])
    if result.get('blocked_reason') or not result.get('packet'):
        raise ValueError(str(result.get('blocked_reason') or 'No suitable verified application contact was found.'))
    packet = Packet.model_validate(result['packet'])
    company_page = validate_evidence(packet.company_evidence, pages, 'Company evidence')
    if expected_host and host(company_page['final_url']) != expected_host:
        raise ValueError('The company page redirected to another domain. Verify the employer before applying.')
    if packet.company_evidence.source_url != company_url:
        raise ValueError('Company identity must be established by its official page.')
    role_page = validate_evidence(packet.job_evidence, pages, 'Job evidence')
    if packet.job_evidence.source_url not in job_urls:
        raise ValueError('The current job was not established by a researched role page.')
    if packet.job_evidence.source_url != canonical_job_url and not trusted_job_host(
            packet.job_evidence.source_url, host(company_page['final_url'])):
        raise ValueError('The alternate job source is not an employer page or trusted job platform.')
    validate_job_page(role_page, posting)
    official_host = host(company_page['final_url'])
    if packet.recipient.evidence.source_type == 'possibleos_contact':
        local_contact = next((contact for contact in possibleos_contacts
            if contact['contact_id'] == packet.recipient.evidence.contact_id
            and contact['email'].casefold() == packet.recipient.email.casefold()), None)
        if not local_contact:
            raise ValueError('The selected Possible OS contact is not an eligible contact for this employer.')
        if packet.recipient.evidence.source_url != local_contact['evidence']['source_url']:
            raise ValueError('The Possible OS contact reference does not match its stored record.')
        if not evidence_present(packet.recipient.evidence.text, local_contact['evidence']['text']):
            raise ValueError('The Possible OS contact details do not match the stored record.')
        if packet.recipient.kind != local_contact['kind']:
            raise ValueError('The Possible OS contact was assigned the wrong recruiting or routing purpose.')
        packet.recipient.name = local_contact['name']
        packet.recipient.evidence = RecipientEvidence.model_validate(local_contact['evidence'])
    else:
        contact_page = validate_evidence(packet.recipient.evidence, pages, 'Contact evidence')
        contact_host = host(contact_page['final_url'])
        if not (contact_host == official_host or contact_host.endswith('.' + official_host) or packet.recipient.evidence.source_url == posting['source_url']):
            raise ValueError('The recipient must be published on the verified company website.')
        if not published_email(packet.recipient.email, contact_page['content']):
            raise ValueError('The recipient email is not present on its verified source page.')
    if '\r' in packet.subject or '\n' in packet.subject or 'tailored' in packet.body_text.casefold():
        raise ValueError('The application wording needs correction.')
    # Cite the role page that actually passed evidence validation. Imported job
    # boards sometimes block fetches after discovery; retaining that inaccessible
    # URL in the draft makes the final audit contradict the verified evidence.
    verified_job_url = packet.job_evidence.source_url
    if canonical_job_url != verified_job_url:
        packet.body_text = packet.body_text.replace(canonical_job_url, verified_job_url)
    if verified_job_url not in packet.body_text:
        packet.body_text += '\n\nRole: ' + verified_job_url
    if update_phase:
        await update_phase('auditing', 'Draft created; checking every claim against the resume and sources')
    audit = await ask_model('audit_email', {'packet': packet.model_dump(), 'resume': application['resume']['text'],
        'pages': pages, 'possibleos_contacts': possibleos_contacts,
        'possibleos_contact_error': possibleos_contact_error,
        'preferences': application['preferences']}, ['approved', 'reason'])
    if audit['approved'] is not True:
        raise ValueError('Application needs review: ' + str(audit['reason']))
    return {'email': {'from': 'pranav@possiblemindshq.com', 'to': packet.recipient.email,
                      'subject': packet.subject, 'body_text': packet.body_text},
            'recipient': packet.recipient.model_dump(), 'company_summary': packet.company_summary,
            'fit_reason': packet.fit_reason, 'gaps': packet.gaps,
            'evidence': {'company': packet.company_evidence.model_dump(), 'job': packet.job_evidence.model_dump(),
                         'canonical_job_url': canonical_job_url, 'verified_job_url': verified_job_url,
                         'possibleos_contacts_considered': len(possibleos_contacts),
                         'possibleos_contact_error': possibleos_contact_error,
                         'source_fetch_failures': fetch_failures,
                         'audit': audit, 'checked_at': datetime.now(timezone.utc).isoformat()}}
