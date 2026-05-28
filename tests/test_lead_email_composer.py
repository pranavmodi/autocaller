import json

from app.services.lead_email_composer import (
    CONSULT_URL,
    _blog_posts,
    _ensure_consult_signature,
    _sender_payload,
)


def test_ensure_consult_signature_appends_required_link(monkeypatch):
    monkeypatch.setenv("SALES_REP_NAME", "Pranav")
    monkeypatch.setenv("SALES_REP_TITLE", "Founder")

    body = _ensure_consult_signature("Hi Sarah,\n\nQuick note.", _sender_payload())

    assert body.endswith(f"-- Pranav\nFounder, Possible Minds\n{CONSULT_URL}")


def test_ensure_consult_signature_does_not_duplicate_link():
    body = f"Hi Sarah,\n\n-- Pranav\nFounder, Possible Minds\n{CONSULT_URL}"

    assert _ensure_consult_signature(body, {"name": "Pranav", "title": "Founder"}) == body


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

