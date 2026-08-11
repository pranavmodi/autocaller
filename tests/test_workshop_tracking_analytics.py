from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.workshop_tracking_analytics import (
    _contacts_with_activity,
    _dedupe_page_events,
    _event_label,
    _session_quality,
    _workshop_page_key,
)


def _event(*, event: str, page: str, at: datetime, ua: str = "Mozilla/5.0", ms: int = 0):
    return SimpleNamespace(
        id=f"{event}-{page}-{at.timestamp()}",
        contact_id="contact-1",
        created_at=at,
        raw_event_json={
            "event": event,
            "page": page,
            "session_id": "session-1",
            "time_on_page_ms": ms,
            "user_agent": ua,
        },
    )


def test_workshop_page_key_normalizes_global_and_explicit_beacons():
    assert _workshop_page_key("workshops/ai-for-filevine-case-managers") == "filevine-case-managers"
    assert _workshop_page_key("workshop-filevine-case-managers") == "filevine-case-managers"


def test_duplicate_global_and_page_beacons_are_collapsed():
    now = datetime.now(timezone.utc)
    rows = [
        _event(event="content_revealed", page="workshop-filevine-case-managers", at=now),
        _event(
            event="content_revealed",
            page="workshops/ai-for-filevine-case-managers",
            at=now + timedelta(milliseconds=75),
        ),
    ]

    deduped = _dedupe_page_events(rows)

    assert len(deduped) == 1


def test_short_session_without_meaningful_action_is_unconfirmed():
    now = datetime.now(timezone.utc)
    rows = [
        _event(event="session_ready", page="workshop-filevine-case-managers", at=now),
        _event(event="first_pointer", page="workshop-filevine-case-managers", at=now, ms=500),
        _event(event="page_leave", page="workshop-filevine-case-managers", at=now, ms=4200),
    ]

    assert _session_quality(rows) == "suspect"


def test_prompt_reveal_is_human_unless_user_agent_is_scanner():
    now = datetime.now(timezone.utc)
    human = [_event(event="content_revealed", page="workshop-filevine-case-managers", at=now)]
    scanner = [
        _event(
            event="content_revealed",
            page="workshop-filevine-case-managers",
            at=now,
            ua="Mozilla/5.0 HeadlessChrome/142.0",
        )
    ]

    assert _session_quality(human) == "human"
    assert _session_quality(scanner) == "scanner"
    assert _event_label("content_revealed", {}, "human")[0] == "Prompt revealed"


def test_contacts_without_activity_in_the_selected_window_are_omitted():
    contacts = {
        "inactive": {
            "contact_name": "Inactive Person",
            "last_activity_at": None,
        },
        "older": {
            "contact_name": "Older Activity",
            "last_activity_at": "2026-08-09T10:00:00+00:00",
        },
        "newer": {
            "contact_name": "Newer Activity",
            "last_activity_at": "2026-08-10T10:00:00+00:00",
        },
    }

    rows = _contacts_with_activity(contacts)

    assert [row["contact_name"] for row in rows] == [
        "Newer Activity",
        "Older Activity",
    ]
