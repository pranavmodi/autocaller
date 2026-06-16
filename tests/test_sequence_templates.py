import pytest

from app.services.sequence_recommendations import (
    Recommendation,
    _has_usable_email,
    _looks_like_non_law_firm,
)
from app.services.sequences.registry import (
    DEFAULT_TEMPLATE_KEY,
    cadence_for,
    is_dynamic_template,
    list_templates,
    normalize_template_key,
    steps_total,
    variant_for,
)


def test_registry_lists_only_dynamic_composer_template():
    keys = {t.template_key for t in list_templates()}

    assert DEFAULT_TEMPLATE_KEY == "possible_minds_dynamic"
    assert keys == {"possible_minds_dynamic"}
    assert is_dynamic_template("possible_minds_dynamic")
    variant = variant_for("possible_minds_dynamic", pain_quote=None)
    assert steps_total("possible_minds_dynamic", variant) == 3
    assert cadence_for("possible_minds_dynamic", variant) == [0, 3, 7]


def test_dynamic_sequence_count_and_cadence_can_be_overridden(monkeypatch):
    monkeypatch.setenv("SEQUENCE_STEPS", "4")
    monkeypatch.setenv("SEQUENCE_CADENCE_DAYS", "0,2,5,9")

    variant = variant_for("possible_minds_dynamic", pain_quote=None)

    assert steps_total("possible_minds_dynamic", variant) == 4
    assert cadence_for("possible_minds_dynamic", variant) == [0, 2, 5, 9]


def test_unknown_sequence_template_is_rejected():
    with pytest.raises(ValueError, match="unknown sequence template"):
        normalize_template_key("not-a-real-template")


def test_recommendation_filter_suppresses_obvious_non_law_firms():
    assert _looks_like_non_law_firm("Bay Radiology", "Owner")
    assert _looks_like_non_law_firm("Rafii Cheung Auto Injury Clinic", "Owner / Chiropractor")
    assert not _looks_like_non_law_firm("BD&J", "Founder & Managing Partner Attorney")
    assert not _looks_like_non_law_firm("BH Injury Firm", "Founder & Trial Attorney")


def test_recommendation_filter_requires_sendable_email():
    assert _has_usable_email("founder@examplelaw.com")
    assert not _has_usable_email("null")
    assert not _has_usable_email("[email protected]")


def test_recommendation_dataclass_tracks_contact_fields():
    rec = Recommendation(
        contact_id="c1",
        pif_id="p1",
        firm_name="Example Law",
        contact_name="Alex",
        contact_email="alex@examplelaw.com",
        contact_title="Founder",
        contact_source="pif_leadership",
        persona="founder/owner",
        score=100,
        reason="test",
    )

    assert rec.contact_email == "alex@examplelaw.com"
