from types import SimpleNamespace

from app.services.engagement_analytics import (
    _recipient_status,
    _review_subject_firm,
    _selected_sources,
)


def test_selected_sources_treats_linkedin_as_a_workshop_channel():
    assert _selected_sources("workshops", "linkedin") == {"workshop_linkedin"}
    assert _selected_sources("workshops", "email") == {
        "workshop_email",
        "workshop_signature",
    }


def test_selected_sources_keeps_review_outreach_in_email_channel():
    assert _selected_sources("client_communication", "email") == {
        "solution_client_communication"
    }
    assert _selected_sources("client_communication", "linkedin") == set()


def test_recipient_status_uses_highest_funnel_stage():
    row = {
        "replies": 0,
        "meaningful_actions": 0,
        "confirmed_visits": 0,
        "raw_clicks": 1,
        "delivered": 1,
        "sent": 1,
    }
    assert _recipient_status(row) == "Unconfirmed click"
    row["confirmed_visits"] = 1
    assert _recipient_status(row) == "Visited"
    row["replies"] = 1
    assert _recipient_status(row) == "Replied"


def test_review_subject_supplies_current_firm_name():
    item = SimpleNamespace(
        reason_json={
            "agent_draft": {
                "subject": "Marlene A. submitted a Yelp review about Fiore Legal, Inc."
            }
        }
    )
    assert _review_subject_firm(item) == "Fiore Legal, Inc."
