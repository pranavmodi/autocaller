from datetime import datetime, timezone

from app.db.models import PifFirmRow
from app.services import pif_directory


def test_parse_dt_handles_iso_and_z_and_naive():
    assert pif_directory._parse_dt(None) is None
    assert pif_directory._parse_dt("") is None
    aware = pif_directory._parse_dt("2026-06-16T04:08:07.187925")
    assert aware is not None and aware.tzinfo is not None  # naive -> assumed UTC
    z = pif_directory._parse_dt("2026-06-16T04:08:07Z")
    assert z == datetime(2026, 6, 16, 4, 8, 7, tzinfo=timezone.utc)


def test_apply_record_captures_all_rich_fields():
    item = {
        "id": "abc-123",
        "firm_name": "Beverly Law",
        "website": "www.beverlylaw.org",
        "entity_type": "law_firm",
        "fax": "310-000-0000",
        "icp_score": 61,
        "icp_tier": "B",
        "research_status": "done",
        "staff_research_status": "pending",
        "emails": ["a@beverlylaw.org", "b@beverlylaw.org"],
        "phones": ["(310) 598-6326"],
        "addresses": ["123 Main St"],
        "contacts": [{"name": "Emma", "title": "Case Manager", "email": "a@beverlylaw.org"}],
        "leadership": [{"name": "Michael", "title": "CEO", "bio": "founder", "linkedin": None}],
        "staff": None,
        "contact_profiles": {"a@beverlylaw.org": {"role": "case_manager", "after_hours_ratio": 1.0}},
        "research_data": {"sources": ["https://beverlylaw.org/about"]},
        "behavioral_data": {"sender_roles": {"lien_settlement": 336, "case_manager": 209}},
        "score_breakdown": {"total": 61, "email_volume_score": 30},
        "conversation_ids": ["cnv_1", "cnv_2"],
        "extraction_notes": "mentions a patient name",
        "created_at": "2026-03-01T00:00:00",
        "updated_at": "2026-06-16T04:08:07.187925",
        "last_researched_at": "2026-06-12T00:00:00",
        "icp_scored_at": "2026-06-12T00:00:00",
    }
    now = datetime(2026, 6, 16, 5, 0, 0, tzinfo=timezone.utc)
    row = PifFirmRow(id="abc-123")
    pif_directory._apply_record(row, item, now=now)

    # scalars
    assert row.firm_name == "Beverly Law"
    assert row.icp_score == 61 and row.icp_tier == "B"
    # rich JSONB captured
    assert row.contacts[0]["title"] == "Case Manager"
    assert row.leadership[0]["bio"] == "founder"
    assert row.behavioral_data["sender_roles"]["lien_settlement"] == 336
    assert row.contact_profiles["a@beverlylaw.org"]["after_hours_ratio"] == 1.0
    assert row.score_breakdown["email_volume_score"] == 30
    assert row.conversation_ids == ["cnv_1", "cnv_2"]
    # staff None coerced to list
    assert row.staff == []
    # raw_json keeps the untouched record (nothing lost)
    assert row.raw_json is item
    # source timestamps parsed
    assert row.source_updated_at == pif_directory._parse_dt("2026-06-16T04:08:07.187925")
    assert row.synced_at == now
