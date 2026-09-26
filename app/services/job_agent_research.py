"""Evidence-backed recipient discovery and application composition."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.services.career_job_store import source_identity
from app.services.career_search_web import fetch_page


logger = logging.getLogger(__name__)
TYPESAFE_SYSTEM_ONE_URL = 'https://api.typesafe.ai/v1/systemone'
JOB_IDENTITY_QUESTION_ID = 'same_job_identity'

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


def official_host_matches(value, official_host):
    candidate = host(value)
    return bool(official_host and (candidate == official_host or candidate.endswith('.' + official_host)))


def canonical_company_url(posting):
    value = str(posting.get('website') or '').strip()
    if not value:
        return None
    parsed = urlsplit(value if '://' in value else 'https://' + value)
    if parsed.scheme != 'https' or not parsed.hostname:
        return None
    return f'https://{parsed.hostname.lower()}/'


def normalized(value):
    value = unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore').decode()
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', value.casefold()).split())


def same_source_url(left, right):
    """Compare mechanical URL identity without requiring presentation equality."""
    if not left or not right:
        return False
    return source_identity(str(left)) == source_identity(str(right))


def _parse_job_identity_response(response, source_pages):
    if not isinstance(response, dict) or not isinstance(response.get('answers'), dict):
        raise ValueError('TypeSafe response is missing answers.')
    model = response.get('model')
    if not isinstance(model, str) or not model:
        raise ValueError('TypeSafe response is missing its model version.')
    scores = []
    for index, page in enumerate(source_pages):
        question_id = f'{JOB_IDENTITY_QUESTION_ID}_{index}'
        answer = response['answers'].get(question_id)
        if not isinstance(answer, dict) or answer.get('type') != 'noul':
            raise ValueError(f'TypeSafe response is missing job-identity answer {index + 1}.')
        probability = answer.get('noul')
        if (isinstance(probability, bool) or not isinstance(probability, (int, float))
                or not 0 <= probability <= 1):
            raise ValueError(f'TypeSafe job-identity probability {index + 1} is invalid.')
        scores.append({
            'source_url': page.get('requested_url'),
            'probability': float(probability),
        })
    best = max(scores, key=lambda item: item['probability'])
    return {
        'provider': 'typesafe',
        'model': model,
        'probability': best['probability'],
        'selected_source_url': best['source_url'],
        'source_probabilities': scores,
        'source_count': len(scores),
        'usage': response.get('usage') if isinstance(response.get('usage'), dict) else {},
    }


async def verify_job_identity_with_jev(page, posting, corroborating_pages=None):
    """Semantically verify the selected role page with bounded corroborating sources."""
    api_key = os.getenv('TYPESAFE_API_KEY', '').strip()
    if not api_key:
        raise RuntimeError('TYPESAFE_API_KEY is not configured for job identity verification.')
    corroborating_pages = [candidate for candidate in (corroborating_pages or [])
                           if not same_source_url(candidate.get('requested_url'), page.get('requested_url'))][:4]
    source_pages = [page, *corroborating_pages]
    candidate_sources = [{
        'url': candidate.get('final_url') or candidate.get('requested_url'),
        'content': str(candidate.get('content') or '')[:20_000 if index == 0 else 12_000],
    } for index, candidate in enumerate(source_pages)]
    questions = {}
    for index in range(len(source_pages)):
        questions[f'{JOB_IDENTITY_QUESTION_ID}_{index}'] = {
            'type': 'noul',
            'instructions': {
                'question': (
                    f'Does `candidate_sources[{index}]` describe the same employer and job role '
                    'as `saved_job`?'
                ),
                'rules': [
                    'Judge semantic role identity from the employer, function, specialty, seniority, and described work.',
                    'Allow harmless presentation differences such as punctuation, capitalization, abbreviations, and appended work-mode, employment-type, or location labels.',
                    'Answer no when the employer, function, specialty, or seniority conflicts, or when the page lacks enough role evidence.',
                ],
            },
            'criteria': {
                'true': 'The source page identifies the saved employer and materially the same job role.',
                'false': 'It identifies a different employer or materially different role, or provides insufficient role evidence.',
            },
        }
    request = {
        'state': {
            'saved_job': {
                'title': posting.get('title'),
                'employer': posting.get('firm_name'),
                'location': posting.get('location'),
                'description_summary': posting.get('description_summary'),
                'responsibilities': posting.get('responsibilities'),
                'qualifications': posting.get('qualifications'),
            },
            'candidate_sources': candidate_sources,
        },
        'model': os.getenv('JOB_AGENT_TYPESAFE_MODEL', 'jev-latest'),
        'questions': questions,
    }
    timeout_s = float(os.getenv('JOB_AGENT_IDENTITY_TIMEOUT_S', '30'))
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
            return _parse_job_identity_response(response.json(), source_pages)
        except json.JSONDecodeError as exc:
            last_error = exc
            if attempt == 0:
                await asyncio.sleep(0.5)
                continue
            break
        except ValueError:
            raise
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_error = exc
            if attempt == 0:
                await asyncio.sleep(0.5)
                continue
            break
    raise RuntimeError('TypeSafe Jev job identity verification is temporarily unavailable.') from last_error


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
    page = next((p for p in pages if same_source_url(p['requested_url'], evidence.source_url)), None)
    if not page or page['http_status'] != 200:
        raise ValueError(f'{label} source page could not be verified.')
    if not evidence_present(evidence.text, page['content']):
        raise ValueError(f'{label} excerpt could not be verified against its source page.')
    return page


def validate_evidence_with_stored_fallback(evidence, stored_evidence, pages, label='Evidence'):
    """Recover a model paraphrase with a previously verified, freshly rechecked excerpt."""
    try:
        return validate_evidence(evidence, pages, label), evidence, False
    except ValueError as original_error:
        if 'excerpt could not be verified' not in str(original_error) or not stored_evidence:
            raise
        try:
            fallback = Evidence.model_validate(stored_evidence)
            page = validate_evidence(fallback, pages, label)
        except (ValueError, TypeError):
            raise original_error
        return page, fallback, True


async def research_application(application, ask_model, update_phase=None):
    posting = application['posting']
    if update_phase:
        await update_phase('discovering_contacts', 'Searching public web sources for the employer, role and recruiting contacts')
    discoveries = Discovery.model_validate(await ask_model(
        'discover_contacts', {'job': posting}, ['company_url', 'contact_urls', 'job_urls']))
    company_url = discoveries.company_url
    expected_host = website_host(posting.get('website') or '')
    if expected_host and not official_host_matches(company_url, expected_host):
        raise ValueError('The research returned a different company website. Verify employer identity before applying.')

    canonical_job_url = posting['source_url']
    canonical_company = canonical_company_url(posting)
    imported_company_evidence = posting.get('employer_evidence_url')
    job_urls = list(dict.fromkeys([canonical_job_url, *discoveries.job_urls]))
    urls = list(dict.fromkeys([*job_urls, company_url, *([canonical_company] if canonical_company else []),
                              *([imported_company_evidence] if imported_company_evidence else []),
                              *discoveries.contact_urls]))

    if update_phase:
        await update_phase('fetching_sources', f'Checking {len(urls)} discovered source page{'' if len(urls) == 1 else 's'}')

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

    identity_urls = [company_url,
                     *([imported_company_evidence] if imported_company_evidence else []),
                     *([canonical_company] if canonical_company else [])]
    fetched_company_page = next((page for requested in identity_urls for page in pages
        if page['requested_url'] == requested and page['http_status'] == 200
        and (not expected_host or official_host_matches(page['final_url'], expected_host))), None)
    if fetched_company_page:
        company_url = fetched_company_page['requested_url']
    # Some official corporate homepages challenge automated reads or redirect to
    # a separate consumer domain. An employer-owned jobs subdomain is still
    # strong company identity evidence when it also carries the current role.
    if not fetched_company_page and expected_host:
        fetched_company_page = next((page for page in successful_job_pages
            if official_host_matches(page['final_url'], expected_host)), None)
        if fetched_company_page:
            company_url = fetched_company_page['requested_url']
    possibleos_contacts = []
    possibleos_contact_error = None
    if fetched_company_page:
        if update_phase:
            await update_phase('checking_contacts', 'Checking published contacts and reusable Possible OS firm contacts')
        try:
            possibleos_contacts = await load_possibleos_contacts(
                posting, host(fetched_company_page.get('final_url') or company_url))
        except Exception as exc:
            logger.warning('Possible OS contact lookup failed for %s: %s', posting.get('firm_id'), exc)
            possibleos_contact_error = f'{type(exc).__name__}: {exc}'[:500]

    if update_phase:
        await update_phase('drafting', 'Selecting a verified recipient and drafting the application email')
    result = await ask_model('compose', {'job': posting, 'pages': pages, 'company_url': company_url,
        'job_urls': job_urls, 'source_fetch_failures': fetch_failures,
        'possibleos_contacts': possibleos_contacts, 'possibleos_contact_error': possibleos_contact_error,
        'resume': application['resume']['text'], 'preferences': application['preferences']}, ['packet', 'blocked_reason'])
    if result.get('blocked_reason') or not result.get('packet'):
        raise ValueError(str(result.get('blocked_reason') or 'No suitable verified application contact was found.'))
    packet = Packet.model_validate(result['packet'])
    evidence_recoveries = []
    company_page, packet.company_evidence, company_evidence_recovered = (
        validate_evidence_with_stored_fallback(
            packet.company_evidence, posting.get('employer_evidence'), pages, 'Company evidence'
        )
    )
    if company_evidence_recovered:
        evidence_recoveries.append('company')
    verified_company_host = expected_host or host(
        (fetched_company_page or {}).get('final_url') or company_url
    )
    if not official_host_matches(company_page['final_url'], verified_company_host):
        raise ValueError('The company page redirected to another domain. Verify the employer before applying.')
    # The evidence may come from any freshly fetched page on the verified
    # employer domain. Requiring the exact discovery URL made an official About
    # or Careers page fail merely because discovery selected the homepage.
    packet.company_evidence.source_url = company_page['requested_url']
    role_page, packet.job_evidence, job_evidence_recovered = validate_evidence_with_stored_fallback(
        packet.job_evidence, posting.get('role_evidence'), pages, 'Job evidence'
    )
    if job_evidence_recovered:
        evidence_recoveries.append('job')
    if not any(same_source_url(role_page['requested_url'], url) for url in job_urls):
        raise ValueError('The current job was not established by a researched role page.')
    packet.job_evidence.source_url = role_page['requested_url']
    # Alternate role sources do not need to belong to a fixed host allowlist.
    # They still must be freshly fetched, cited by the packet, and accepted by
    # the semantic identity and evidence checks below.
    if update_phase:
        await update_phase('verifying_sources', 'Jev is confirming that the selected page matches this employer and role')
    corroborating_role_pages = [page for page in successful_job_pages
                                if not same_source_url(page['requested_url'], role_page['requested_url'])]
    job_identity_verification = await verify_job_identity_with_jev(
        role_page, posting, corroborating_pages=corroborating_role_pages
    )
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
        packet.recipient.evidence.source_url = contact_page['requested_url']
        contact_host = host(contact_page['final_url'])
        if not (contact_host == official_host or contact_host.endswith('.' + official_host)
                or same_source_url(contact_page['requested_url'], posting['source_url'])):
            raise ValueError('The recipient must be published on the verified company website.')
        if not published_email(packet.recipient.email, contact_page['content']):
            raise ValueError('The recipient email is not present on its verified source page.')
    if '\r' in packet.subject or '\n' in packet.subject or 'tailored' in packet.body_text.casefold():
        raise ValueError('The application wording needs correction.')
    # Cite the role page that actually passed evidence validation. Imported job
    # boards sometimes block fetches after discovery; retaining that inaccessible
    # URL in the draft makes the final audit contradict the verified evidence.
    verified_job_url = packet.job_evidence.source_url
    if not same_source_url(canonical_job_url, verified_job_url):
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
                         'job_identity_verification': job_identity_verification,
                         'stored_evidence_recoveries': evidence_recoveries,
                         'possibleos_contacts_considered': len(possibleos_contacts),
                         'possibleos_contact_error': possibleos_contact_error,
                         'source_fetch_failures': fetch_failures,
                         'audit': audit, 'checked_at': datetime.now(timezone.utc).isoformat()}}
