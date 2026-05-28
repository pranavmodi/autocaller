import pytest

from app.services.sequence_recommendations import (
    Recommendation,
    _has_usable_email,
    _looks_like_non_law_firm,
)
from app.services.sequences.common import Ctx
from app.services.sequences.registry import (
    DEFAULT_TEMPLATE_KEY,
    cadence_for,
    is_dynamic_template,
    list_templates,
    normalize_template_key,
    render_step,
    steps_total,
    variant_for,
)


def _ctx():
    return Ctx(first_name="Sarah", firm_name="Liu Law", rep_name="Pranav")


def test_records_audit_template_renders_records_specific_first_step():
    variant = variant_for("precise_records_audit", pain_quote=None)

    assert variant == "records_only"
    assert steps_total("precise_records_audit", variant) == 3
    assert cadence_for("precise_records_audit", variant) == [0, 5, 12]

    rendered = render_step("precise_records_audit", 1, variant, _ctx())

    assert rendered.subject == "Precise Imaging -- quick records question"
    assert rendered.message_type == "records_audit_step_1"
    assert "20-minute records workflow audit" in rendered.body
    assert "Liu Law" in rendered.body


def test_registry_lists_both_sequence_templates():
    keys = {t.template_key for t in list_templates()}

    assert DEFAULT_TEMPLATE_KEY == "possible_minds_dynamic"
    assert "possible_minds_dynamic" in keys
    assert "precise_pain_4step" in keys
    assert "precise_records_audit" in keys
    assert is_dynamic_template("possible_minds_dynamic")


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
