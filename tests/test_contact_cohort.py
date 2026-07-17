from app.services.contact_cohort import email_domain, select_curated_contact_rows


def _row(contact_id: str, pif_id: str, email: str, confidence: float = 1.0) -> dict:
    return {
        "id": contact_id,
        "pif_id": pif_id,
        "email": email,
        "conf": confidence,
    }


def test_email_domain_normalizes_and_rejects_invalid_addresses():
    assert email_domain(" Person@Example.COM. ") == "example.com"
    assert email_domain("not-an-email") == ""
    assert email_domain("@example.com") == ""


def test_curated_selection_caps_duplicate_firm_aliases_by_domain():
    rows = [
        _row("c1", "firm-1", "one@example.com"),
        _row("c2", "firm-2-alias", "two@example.com"),
        _row("c3", "firm-3", "three@other.com"),
    ]

    selected = select_curated_contact_rows(
        rows,
        max_per_firm=1,
        max_per_domain=1,
    )

    assert [row["id"] for row in selected] == ["c1", "c3"]


def test_curated_selection_allows_explicit_second_contact_per_domain():
    rows = [
        _row("c1", "firm-1", "one@example.com"),
        _row("c2", "firm-1", "two@example.com"),
        _row("c3", "firm-2", "three@other.com"),
    ]

    selected = select_curated_contact_rows(
        rows,
        max_per_firm=2,
        max_per_domain=2,
        second_contact_min_team=2,
    )

    assert [row["id"] for row in selected] == ["c1", "c2", "c3"]
