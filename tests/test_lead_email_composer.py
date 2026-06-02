import json

from app.services.lead_email_composer import (
    CONSULT_URL,
    _blog_posts,
    _conversation_state,
    _ensure_consult_signature,
    _sanitize_body_salutation,
    _sanitize_email_copy,
    _sanitize_subject,
    _sender_payload,
)


class ContactStub:
    def __init__(self, *, first_name: str | None, full_name: str | None):
        self.first_name = first_name
        self.full_name = full_name


def test_ensure_consult_signature_appends_required_link(monkeypatch):
    monkeypatch.setenv("SALES_REP_NAME", "Pranav")
    monkeypatch.setenv("SALES_REP_TITLE", "Founder")

    body = _ensure_consult_signature("Hi Sarah,\n\nQuick note.", _sender_payload())

    assert body.endswith(f"-- Pranav\nFounder, Possible Minds\n{CONSULT_URL}")


def test_ensure_consult_signature_does_not_duplicate_link():
    body = f"Hi Sarah,\n\n-- Pranav\nFounder, Possible Minds\n{CONSULT_URL}"

    assert _ensure_consult_signature(body, {"name": "Pranav", "title": "Founder"}) == body


def test_sanitize_email_copy_removes_generated_dash_punctuation():
    body = (
        "Hi Sean —\n\n"
        "We built this for Precise Imaging — now I am curious what you are improving."
    )

    sanitized = _sanitize_email_copy(body)

    assert "—" not in sanitized
    assert "–" not in sanitized
    assert sanitized.startswith("Hi Sean,")
    assert "Precise Imaging - now" in sanitized


def test_sanitize_subject_removes_weak_precise_quick_question_prefix():
    assert (
        _sanitize_subject("Quick question about Precise Imaging status updates")
        == "Precise Imaging status updates"
    )


def test_sanitize_body_salutation_removes_firm_name_greeting():
    body = "Hi Atlantic,\n\nQuick question."
    contact = ContactStub(first_name="Atlantic", full_name="Atlantic Injury Center")

    sanitized = _sanitize_body_salutation(
        body,
        contact=contact,  # type: ignore[arg-type]
        firm_name="Atlantic Injury Center",
    )

    assert sanitized.startswith("Hi,\n\n")


def test_sanitize_body_salutation_keeps_real_person_greeting():
    body = "Hi Erica,\n\nQuick question."
    contact = ContactStub(first_name="Erica", full_name="Erica Smith")

    sanitized = _sanitize_body_salutation(
        body,
        contact=contact,  # type: ignore[arg-type]
        firm_name="Atlantic Injury Center",
    )

    assert sanitized.startswith("Hi Erica,\n\n")


def test_conversation_state_replaces_sequence_payload():
    assert _conversation_state(
        reply_count=0,
        zoho_sent_count=0,
    )["is_first_touch"]

    state = _conversation_state(
        reply_count=2,
        zoho_sent_count=1,
    )

    assert not state["is_first_touch"]
    assert state["prior_outbound_count"] == 1
    assert state["prior_reply_count"] == 2
    assert state["has_zoho_sent_history"]
    assert state["prior_outbound_source"] == "zoho_sent"


def test_blog_posts_supports_json_and_comma_env(monkeypatch):
    monkeypatch.setenv(
        "LEAD_GEN_BLOG_LINKS_JSON",
        json.dumps([{"title": "Ops", "url": "https://getpossibleminds.com/blog/ops"}]),
    )
    assert _blog_posts() == [{"title": "Ops", "url": "https://getpossibleminds.com/blog/ops"}]

    monkeypatch.delenv("LEAD_GEN_BLOG_LINKS_JSON")
    monkeypatch.setenv(
        "LEAD_GEN_BLOG_LINKS",
        "https://getpossibleminds.com/blog/a, https://getpossibleminds.com/blog/b",
    )
    assert _blog_posts() == [
        {"title": "", "url": "https://getpossibleminds.com/blog/a"},
        {"title": "", "url": "https://getpossibleminds.com/blog/b"},
    ]
