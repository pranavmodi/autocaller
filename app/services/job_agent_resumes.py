"""Explicit category-to-local-PDF mapping and safe resume access."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

RESUME_ROOT = Path('/home/pranav/resume')


class ResumeCategory(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,63}$')
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2000)
    resume_path: str = Field('', max_length=1000)


def default_categories():
    return [
        ResumeCategory(id='ai_automation', name='AI agents and automation',
            description='Hands-on AI agents, workflow automation, integrations and applied AI engineering.',
            resume_path='job-agent/resumes/Pranav_Modi_AI_Agents_Automation.pdf'),
        ResumeCategory(id='engineering_leadership', name='Engineering leadership',
            description='Engineering management, technical team leadership, architecture and software delivery.',
            resume_path='job-agent/resumes/Pranav_Modi_Engineering_Leadership.pdf'),
        ResumeCategory(id='technical_product', name='Technical product and solutions',
            description='Technical product management, solution consulting, customer discovery and implementation.',
            resume_path='job-agent/resumes/Pranav_Modi_Technical_Product_Solutions.pdf'),
        ResumeCategory(id='data_ml', name='Data and machine learning',
            description='Data engineering, data platforms, data science, analytics and production machine learning.',
            resume_path='job-agent/resumes/Pranav_Modi_Data_Machine_Learning.pdf'),
        ResumeCategory(id='pi_case_management', name='Personal injury case management',
            description='Entry-level, assistant or trainable plaintiff-side personal-injury case management and pre-litigation operations: client and provider communication, treatment and appointment follow-up, medical records and bills, liens, bodily-injury and property-damage claim support, matter tracking and case-status updates. Include case-manager assistant or VA roles at PI firms that support property-damage claim caseloads when no minimum number of years is required. Include combined office-operations roles when hands-on PI case management is substantial. Exclude clinical or social-services case management and roles requiring independent ownership backed by multiple years of direct PI experience.',
            resume_path='job-agent/resumes/Pranav_Modi_PI_Case_Manager.pdf'),
        ResumeCategory(id='entry_level_paralegal', name='Entry-level paralegal and legal assistant',
            description='Junior, entry-level or explicitly trainable paralegal and legal-assistant work under attorney supervision: factual research, legal-document and case-file organization, correspondence, drafting support, discovery support, calendaring, filing and trial preparation. Exclude roles that require a paralegal certificate, qualification under California Business and Professions Code section 6450, jurisdiction-specific independent filing expertise, or multiple years of direct paralegal experience.',
            resume_path='job-agent/resumes/Pranav_Modi_Entry_Level_Paralegal.pdf'),
        ResumeCategory(id='pi_intake', name='Personal injury intake specialist',
            description='Hands-on personal-injury intake specialist, intake coordinator and new-client roles: first contact by phone, email, text or chat; structured interviews and fact capture; screening under firm-defined case criteria; accurate notes and file creation; prompt follow-up; consultation scheduling; and retainer or staff handoff. Include trainable and entry-level roles, and roles accepting transferable sales, customer-success, onboarding or operations experience. Exclude intake-attorney, director, manager and supervisor roles; roles requiring multiple years of direct PI intake; and roles with a mandatory language or jurisdiction credential that is not established.',
            resume_path='job-agent/resumes/Pranav_Modi_PI_Intake_Specialist.pdf'),
    ]


def resolve_resume(value: str) -> Path:
    path = Path(value)
    path = (path if path.is_absolute() else RESUME_ROOT / path).resolve()
    if not path.is_relative_to(RESUME_ROOT.resolve()) or path.suffix.lower() != '.pdf' or not path.is_file():
        raise ValueError('Choose an existing PDF in the resume library.')
    return path


def inspect_resume(value: str):
    path = resolve_resume(value)
    if path.stat().st_size > 10_000_000:
        raise ValueError('Resume PDF exceeds 10 MB.')
    info = subprocess.run(['pdfinfo', str(path)], check=True, capture_output=True, text=True, timeout=20).stdout
    pages = next((line.split(':', 1)[1].strip() for line in info.splitlines() if line.startswith('Pages:')), '')
    if pages != '1':
        raise ValueError('Application resumes must be exactly one page.')
    content = subprocess.run(['pdftotext', '-layout', str(path), '-'], check=True, capture_output=True, text=True, timeout=20).stdout.strip()
    if len(content) < 200:
        raise ValueError('Resume text could not be read. Choose a readable one-page PDF.')
    return {'path': str(path.relative_to(RESUME_ROOT.resolve())), 'filename': path.name,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'pages': 1, 'text': content}


def resume_library():
    items = []
    for path in RESUME_ROOT.rglob('*.pdf'):
        if any(part in {'node_modules', '.git', 'tmp', 'resume trash', 'older'} for part in path.relative_to(RESUME_ROOT).parts):
            continue
        try:
            resolved = resolve_resume(str(path))
            items.append({'path': str(resolved.relative_to(RESUME_ROOT.resolve())), 'filename': path.name})
        except ValueError:
            continue
    return sorted(items, key=lambda item: (not item['path'].startswith('job-agent/resumes/'), item['path']))
