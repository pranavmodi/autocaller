"""Composer A/B: subject-axis variants, assignment, and decision math."""
import asyncio

from app.services.lead_email_composer_variants import (
    AB_MIN_SENDS_PER_ARM,
    _ab_verdict,
    _beta_prob_beats,
    choose_composer_skill_variant,
    discover_composer_skill_variants,
)


def test_subject_axis_variants_active_and_old_arms_retired():
    by_key = {v.key: v for v in discover_composer_skill_variants()}
    assert by_key["subject-pain-led"].active
    assert by_key["subject-behavioral"].active
    assert not by_key["possible-minds-lead-email-composer-skill"].active
    assert not by_key["reply-first-precise-proof"].active


def test_variant_skills_swap_subject_block_only():
    from pathlib import Path

    base_dir = Path("app/skills/possible-minds-lead-email-composer")
    base = (base_dir / "SKILL.md").read_text()
    for key, must_contain, must_not in [
        ("subject-pain-led", "every file has a chase", "prefer subject lines\nthat mention Precise Imaging"),
        ("subject-behavioral", "front_signals.behavior", "prefer subject lines\nthat mention Precise Imaging"),
    ]:
        text = (base_dir / "variants" / key / "SKILL.md").read_text()
        assert must_contain in text
        assert must_not not in text
        # everything outside the subject block is inherited from base
        assert "Match the angle to the contact's persona" in text
        assert "## Required First-Touch Opener" in text
        assert "no_patient_data" not in text or "no_patient_data" in base


def test_assignment_is_deterministic_and_spreads():
    import collections

    first = {f"c{i}": choose_composer_skill_variant(f"c{i}").key for i in range(120)}
    second = {f"c{i}": choose_composer_skill_variant(f"c{i}").key for i in range(120)}
    assert first == second
    spread = collections.Counter(first.values())
    assert set(spread) == {"baseline", "subject-pain-led", "subject-behavioral"}
    assert min(spread.values()) >= 20


def test_beta_binomial_decision_math():
    assert _beta_prob_beats(10, 40, 2, 40) > 0.95
    assert _beta_prob_beats(2, 40, 10, 40) < 0.05
    mid = _beta_prob_beats(5, 40, 5, 40)
    assert 0.44 <= mid <= 0.56
    assert _beta_prob_beats(1, 0, 1, 10) is None
    # determinism
    assert _beta_prob_beats(7, 50, 3, 50) == _beta_prob_beats(7, 50, 3, 50)


def test_verdict_gating():
    assert _ab_verdict(0.99, AB_MIN_SENDS_PER_ARM - 1) == "collecting"
    assert _ab_verdict(0.95, AB_MIN_SENDS_PER_ARM) == "winner"
    assert _ab_verdict(0.05, AB_MIN_SENDS_PER_ARM) == "loser"
    assert _ab_verdict(0.7, AB_MIN_SENDS_PER_ARM) == "leading"
    assert _ab_verdict(0.3, AB_MIN_SENDS_PER_ARM) == "trailing"
    assert _ab_verdict(None, 100) == "collecting"
