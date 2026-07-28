from app.services import firm_intel_sync as svc


def test_people_filter_values_accepts_single_and_multiple_values():
    assert svc._people_filter_values("Case Manager") == ["Case Manager"]
    assert svc._people_filter_values([" Case Manager ", "", "Attorney"]) == [
        "Case Manager",
        "Attorney",
    ]


def test_person_matches_any_uses_or_semantics():
    assert svc._person_matches_any(
        "Senior Case Manager",
        ["Founding Partner", "Case Manager"],
    )
    assert not svc._person_matches_any(
        "Intake Specialist",
        ["Founding Partner", "Case Manager"],
    )


def test_person_matches_any_preserves_unfiltered_behavior():
    assert svc._person_matches_any("Attorney", None)
    assert svc._person_matches_any("Attorney", [])
    assert svc._person_matches_any("Attorney", [""])
