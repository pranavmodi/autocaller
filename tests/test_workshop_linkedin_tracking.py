import asyncio

import pytest

from app.services import workshop_linkedin_tracking as tracking


def test_canonical_linkedin_url_normalizes_profile_host_and_query():
    assert tracking.canonical_linkedin_url(
        "https://br.linkedin.com/in/Gabriela-Gaio-Ziegler/?trk=profile"
    ) == "https://www.linkedin.com/in/gabriela-gaio-ziegler"


def test_create_tracking_link_reuses_stable_person_link(monkeypatch):
    async def fake_upsert(*, full_name, firm_name, title, linkedin_url):
        assert full_name == "Gabriela Gaio Ziegler"
        assert firm_name == "McCready Law"
        return ({
            "id": "contact-1",
            "pif_id": "firm-1",
            "full_name": full_name,
            "first_name": "Gabriela",
            "title": title,
            "linkedin_url": linkedin_url,
            "firm_name": firm_name,
        }, False, False)

    async def fake_link(contact_id):
        assert contact_id == "contact-1"
        return "https://getpossibleminds.com/w/stable123", True

    monkeypatch.setattr(tracking, "_upsert_contact", fake_upsert)
    monkeypatch.setattr(tracking, "_tracked_link", fake_link)

    result = asyncio.run(tracking.create_workshop_linkedin_tracking_link(
        full_name="Gabriela Gaio Ziegler",
        firm_name="McCready Law",
        title="Team Lead | Case Manager",
        linkedin_url="https://www.linkedin.com/in/gabriela",
    ))

    assert result == {
        "tracking_url": "https://getpossibleminds.com/w/stable123",
        "contact": {
            "id": "contact-1",
            "pif_id": "firm-1",
            "full_name": "Gabriela Gaio Ziegler",
            "first_name": "Gabriela",
            "title": "Team Lead | Case Manager",
            "linkedin_url": "https://www.linkedin.com/in/gabriela",
            "firm_name": "McCready Law",
        },
        "contact_created": False,
        "firm_created": False,
        "tracking_link_reused": True,
    }


def test_create_tracking_link_requires_name_and_firm():
    with pytest.raises(tracking.WorkshopLinkedInTrackingError, match="contact_name_required"):
        asyncio.run(tracking.create_workshop_linkedin_tracking_link(
            full_name="",
            firm_name="McCready Law",
        ))
