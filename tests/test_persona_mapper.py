import pytest

from app.db.models import FirmContactRow
from app.services import persona_mapper
from app.services.persona_mapper import classify_contact, classify_contact_fields


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _Session:
    def __init__(self, rows):
        self.rows = rows
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, _stmt):
        return _Result(self.rows)

    async def commit(self):
        self.committed = True


def test_persona_title_precedence_and_specialized_mapping():
    assert classify_contact("Managing Partner", "jane@example.com", "Jane") == (
        "managing_partner",
        "title_keyword",
        0.9,
    )
    assert classify_contact("Treatment Coordinator", "tc@example.com", "Terry")[0] == "case_manager"
    assert classify_contact("Demand Writer", "dw@example.com", "Devon")[0] == "records"
    assert classify_contact("Office Manager", "office@example.com", "Olivia")[0] == "coo_ops"
    assert classify_contact("Operating Partner", "ops@example.com", "Omar")[0] == "coo_ops"
    assert classify_contact("Intake Vendor Owner", "ivo@example.com", "Ivy")[0] == "intake"
    assert classify_contact("Co-Founder; Partner; Managing Attorney", "founder@example.com", "Fran")[0] == "founder_owner"


def test_functional_email_prefix_is_lower_confidence_fallback():
    assert classify_contact("", "records@example.com", "") == ("records", "email_prefix", 0.7)
    assert classify_contact("", "intake.team@example.com", "") == ("intake", "email_prefix", 0.7)
    assert classify_contact("", "billing@example.com", "") == ("lien_settlement", "email_prefix", 0.7)
    assert classify_contact("Marketing Director", "records@example.com", "Morgan") == (
        "marketing",
        "title_keyword",
        0.9,
    )


def test_keyword_coverage_across_persona_groups():
    cases = {
        "Founder": "founder_owner",
        "Pre-litigation Attorney": "attorney",
        "Call Center Manager": "intake",
        "Senior Case Manager": "case_manager",
        "Litigation Paralegal": "paralegal",
        "Lien Negotiator": "lien_settlement",
        "Marketing Director": "marketing",
        "Firm Administrator": "coo_ops",
        "CFO": "coo_ops",
        "Case Management System Admin": "coo_ops",
        "Mass Tort Coordinator": "case_manager",
        "PI Practice Consultant": "coo_ops",
    }
    for title, persona in cases.items():
        assert classify_contact(title, "", "")[0] == persona


def test_research_title_source_wins_over_email_prefix():
    match = classify_contact_fields(
        research_title="Records Manager",
        title="",
        email="intake@example.com",
        name="Riley",
    )
    assert match.persona == "records"
    assert match.source == "research_title"
    assert match.confidence == 0.9


@pytest.mark.asyncio
async def test_map_personas_never_downgrades(monkeypatch):
    strong = FirmContactRow(
        id="fc1",
        pif_id="pif1",
        full_name="Mary Marketing",
        email="records@example.com",
        title="Marketing Director",
        persona="marketing",
        persona_source="research_title",
        persona_confidence=0.9,
    )
    weak = FirmContactRow(
        id="fc2",
        pif_id="pif1",
        full_name="Ira Intake",
        email="intake@example.com",
        title="",
        persona=None,
        persona_source=None,
        persona_confidence=None,
    )
    session = _Session([strong, weak])
    monkeypatch.setattr(persona_mapper, "AsyncSessionLocal", lambda: session)

    result = await persona_mapper.map_personas()

    assert result == {"scanned": 2, "updated": 1, "skipped": 1}
    assert strong.persona == "marketing"
    assert strong.persona_confidence == 0.9
    assert weak.persona == "intake"
    assert weak.persona_confidence == 0.7
