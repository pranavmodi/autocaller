from datetime import datetime, timezone

from app.db.models import PifFirmRow
from app.services.firm_alias_integrity import (
    build_domain_alias_plan,
    is_trusted_domain_alias,
    normalize_identity_domain,
)


def _firm(
    firm_id: str,
    domain: str,
    *,
    name: str | None = None,
    manual_domains: list[str] | None = None,
    researched: bool = False,
) -> PifFirmRow:
    now = datetime.now(timezone.utc)
    source_json = {}
    if manual_domains is not None:
        source_json["_possibleos_manual_overrides"] = {
            "aliases": {"domains": manual_domains, "vanity_domains": [], "legacy_pif_ids": []}
        }
    return PifFirmRow(
        id=firm_id,
        firm_name=name or firm_id,
        website=domain,
        canonical_website=domain,
        research_status="completed" if researched else "missing",
        source_json=source_json,
        raw_json={},
        contacts=[],
        leadership=[],
        staff=[],
        created_at=now,
        updated_at=now,
        synced_at=now,
    )


def test_identity_domain_rejects_research_prose_and_shared_services():
    assert normalize_identity_domain("https://www.smithlaw.com/about") == "smithlaw.com"
    assert normalize_identity_domain("smithlaw.com (inferred)") == ""
    assert normalize_identity_domain("owner@smithlaw.com") == ""
    assert normalize_identity_domain("[email protected]") == ""
    assert normalize_identity_domain("[email0protected]") == ""
    assert normalize_identity_domain("+1 (323) 555-1212") == ""
    assert normalize_identity_domain("clio.com") == ""
    assert normalize_identity_domain("freshdesk.com") == ""


def test_plan_uses_canonical_and_verified_manual_domains_only():
    jacoby = _firm(
        "jacoby",
        "jacobyandmeyers.com",
        manual_domains=["jacobyandmeyers.com", "jacobymeyers.com"],
        researched=True,
    )
    pro_scan = _firm("pro-scan", "proscanpartners.com")
    pro_scan.raw_json = {
        "aliases": {"domains": ["proscanpartners.com", "jacobymeyers.com", "movedocs.com"]}
    }

    plan, duplicates = build_domain_alias_plan([pro_scan, jacoby])

    assert plan == {
        "jacobyandmeyers.com": "jacoby",
        "jacobymeyers.com": "jacoby",
        "proscanpartners.com": "pro-scan",
    }
    assert duplicates == []
    assert is_trusted_domain_alias(jacoby, "jacobymeyers.com") is True
    assert is_trusted_domain_alias(pro_scan, "jacobymeyers.com") is False


def test_duplicate_canonical_selects_more_complete_record_and_reports_conflict():
    sparse = _firm("sparse", "samefirm.com", name="Same Firm")
    complete = _firm("complete", "samefirm.com", name="Same Firm, PC", researched=True)
    complete.contacts = [{"name": "Founder"}]

    plan, duplicates = build_domain_alias_plan([sparse, complete])

    assert plan["samefirm.com"] == "complete"
    assert duplicates[0]["domain"] == "samefirm.com"
    assert set(duplicates[0]["firm_ids"]) == {"sparse", "complete"}
