from app.api.lead_gen import _normalized_country_filter, _page_event_conditions


def test_normalized_country_filter_accepts_non_india_aliases():
    assert _normalized_country_filter("non_in") == "non_in"
    assert _normalized_country_filter("Non-India") == "non_in"
    assert _normalized_country_filter("exclude_in") == "non_in"


def test_non_india_filter_excludes_only_india():
    conditions = _page_event_conditions(0, "non_in")

    assert len(conditions) == 3
    assert "!=" in str(conditions[-1])
