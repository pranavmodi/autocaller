from app.services.contact_selection import (
    ContactSelectionInput,
    classify_email_quality,
    contact_selection_weights,
    has_usable_email,
    is_target_lead_persona,
    score_contact_selection,
)


def test_filevine_application_addresses_are_not_usable_for_outreach():
    assert not has_usable_email("matter@smithlaw.filevineapp.com")
    assert not has_usable_email("iara@ruiz@sedlawgroup.com")
    assert has_usable_email("jane@smithlaw.com")


def test_email_quality_requires_a_name_match_for_direct_mailboxes():
    assert classify_email_quality("jane.smith@firm.com", "Jane Smith") == "direct_named_email"
    assert classify_email_quality("js@firm.com", "Jane Smith") == "direct_named_email"
    assert classify_email_quality("alex@firm.com", "Alejandra Nuno") == "direct_named_email"
    assert classify_email_quality("pa2@firm.com", "Darling Rivera") == "role_inbox"
    assert classify_email_quality("cmassistant@firm.com", "Rafael Mejia") == "role_inbox"


def test_contact_selection_scores_direct_founder_with_trace():
    scored = score_contact_selection(
        ContactSelectionInput(
            contact_id="c1",
            pif_id="p1",
            firm_name="Example Injury Law",
            contact_name="Jane Founder",
            contact_email="jane@examplelaw.com",
            contact_title="Founder & Trial Attorney",
            contact_source="pif_leadership",
            state="CA",
        ),
    )

    assert scored.persona == "founder/owner"
    assert scored.score > 100
    assert scored.score_breakdown["persona:founder_owner"] == 100
    assert scored.score_breakdown["email_quality:direct_named_email"] == 12
    assert scored.features["email_quality"] == "direct_named_email"
    assert "firm_fit:personal_injury_marker" in scored.signals
    assert scored.suppressions == []
    assert "no comms history found" in scored.reason


def test_contact_selection_penalizes_generic_inbox_and_suppresses_missing_persona():
    scored = score_contact_selection(
        ContactSelectionInput(
            contact_id="c2",
            pif_id="p2",
            firm_name="Example Law",
            contact_name="",
            contact_email="info@examplelaw.com",
            contact_title="",
            contact_source="pif_leadership",
        ),
    )

    assert "missing_persona" in scored.suppressions
    assert scored.score_breakdown["email_quality:generic_inbox"] == -30
    assert scored.score_breakdown["risk:missing_persona"] == -1000


def test_contact_selection_policy_override_changes_component_weight():
    weights = contact_selection_weights({
        "email_quality": {"generic_inbox": -55},
    })
    scored = score_contact_selection(
        ContactSelectionInput(
            contact_id="c3",
            pif_id="p3",
            firm_name="Example Injury Law",
            contact_name="Jane Owner",
            contact_email="info@examplelaw.com",
            contact_title="Owner",
            contact_source="pif_leadership",
        ),
        policy_weights=weights,
    )

    assert scored.score_breakdown["email_quality:generic_inbox"] == -55


def test_front_warmth_feature_is_weighted_when_policy_includes_it():
    scored = score_contact_selection(
        ContactSelectionInput(
            contact_id="c-front",
            pif_id="p-front",
            firm_name="Warm Injury Law",
            contact_name="Jane Owner",
            contact_email="jane@warminjury.com",
            contact_title="Owner",
            contact_source="front",
            front_warm_score=42,
        ),
        policy_weights={
            "front_warmth": {"weight": 1, "max_bonus": 75},
        },
    )

    assert scored.score_breakdown["front_warmth:warm_score"] == 42
    assert scored.features["front_warm_score"] == 42
    assert "front_warmth:warm_score" in scored.signals


def test_target_lead_persona_only_allows_owner_partner_coo_equivalents():
    allowed_titles = [
        "Founder & Trial Attorney",
        "Managing Partner",
        "Partner",
        "Principal Attorney",
        "Managing Attorney",
        "Shareholder",
        "CEO",
        "President",
        "COO",
        "Chief Operating Officer",
        "Operations Manager",
        "Office Manager",
        "Owner",
    ]
    blocked_titles = [
        "",
        "Intake Manager",
        "Personal Injury Department Manager",
        "Attorney",
    ]

    for title in allowed_titles:
        assert is_target_lead_persona(title)
    for title in blocked_titles:
        assert not is_target_lead_persona(title)
    assert not is_target_lead_persona("", "patients_dm")
