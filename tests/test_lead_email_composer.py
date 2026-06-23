import json

import pytest

from app.services.lead_email_composer import (
    CONSULT_URL,
    _blog_posts,
    _conversation_state,
    _ensure_consult_signature,
    _ensure_signature,
    _has_visibility_report_link,
    _sanitize_body_salutation,
    _sanitize_email_copy,
    _sanitize_subject,
    _sender_payload,
    _visibility_report_outbound_ready,
    fetch_competitive_context_for_email,
)


class ContactStub:
    def __init__(
        self,
        *,
        first_name: str | None = None,
        full_name: str | None = None,
        pif_id: str | None = None,
        email: str | None = None,
        id: str = "contact-1",
    ):
        self.id = id
        self.first_name = first_name
        self.full_name = full_name
        self.pif_id = pif_id
        self.email = email


def test_ensure_consult_signature_appends_required_link(monkeypatch):
    monkeypatch.setenv("SALES_REP_NAME", "Pranav")
    monkeypatch.setenv("SALES_REP_TITLE", "Founder")

    body = _ensure_consult_signature("Hi Sarah,\n\nQuick note.", _sender_payload())

    assert body.endswith(f"-- Pranav\nFounder, Possible Minds\n{CONSULT_URL}")


def test_ensure_consult_signature_does_not_duplicate_link():
    body = f"Hi Sarah,\n\n-- Pranav\nFounder, Possible Minds\n{CONSULT_URL}"

    assert _ensure_consult_signature(body, {"name": "Pranav", "title": "Founder"}) == body


def test_ensure_signature_adds_consult_and_audit_links(monkeypatch):
    monkeypatch.setenv("AIAUDIT_LINK_SECRET", "test-secret")
    monkeypatch.setenv("OUTREACH_PUBLIC_BASE_URL", "https://possible.example")
    contact = ContactStub(pif_id="pif-1")

    body = _ensure_signature(
        "Hi Sarah,\n\nQuick note.",
        {"name": "Pranav", "title": "Founder"},
        contact=contact,  # type: ignore[arg-type]
        variant_key="baseline",
    )

    assert CONSULT_URL in body
    assert "https://possible.example/aiaudit/go?t=" in body
    assert "P.S. If you're weighing AI tools" in body


def test_ensure_signature_removes_generated_duplicate_signature(monkeypatch):
    monkeypatch.setenv("AIAUDIT_LINK_SECRET", "test-secret")
    monkeypatch.setenv("OUTREACH_PUBLIC_BASE_URL", "https://possible.example")
    contact = ContactStub(pif_id="pif-1")

    body = _ensure_signature(
        "Hi Sarah,\n\nQuick note.\n\n-- Pranav\nFounder, Possible Minds",
        {"name": "Pranav", "title": "Founder"},
        contact=contact,  # type: ignore[arg-type]
        variant_key="baseline",
        audit_url="https://possible.example/a/abc123",
    )

    assert body.count("-- Pranav") == 1
    assert body.count("Founder, Possible Minds") == 1
    assert (
        "P.S. If you're weighing AI tools, here's a 10-minute read on whether your "
        "firm is set up to benefit before you buy: https://possible.example/a/abc123"
    ) in body


def test_ensure_signature_uses_audit_as_primary_cta_for_audit_variant(monkeypatch):
    monkeypatch.setenv("AIAUDIT_LINK_SECRET", "test-secret")
    monkeypatch.setenv("OUTREACH_PUBLIC_BASE_URL", "https://possible.example")
    contact = ContactStub(pif_id="pif-1")

    body = _ensure_signature(
        "Hi Sarah,\n\nI made a quick AI-readiness read for your firm.",
        {"name": "Pranav", "title": "Founder"},
        contact=contact,  # type: ignore[arg-type]
        variant_key="ai-audit",
    )

    assert "https://possible.example/aiaudit/go?t=" in body
    assert "Here it is — about 10 minutes:" in body
    # For the audit variant the link is the primary CTA: it must sit in the body
    # ABOVE the sign-off, never inside the signature.
    assert body.index("/aiaudit/go?t=") < body.index("-- Pranav")
    sign_off_tail = body[body.index("-- Pranav"):]
    assert "/aiaudit/go?t=" not in sign_off_tail
    # The consult link appears in the signature for every variant, including
    # the audit variant.
    assert f"Book a consult: {CONSULT_URL}" in sign_off_tail


def test_visibility_report_link_detection_and_gates():
    assert _has_visibility_report_link("View it: https://possible.example/v/abc123")
    assert _has_visibility_report_link("View it: https://visibility.example/r/scan-123")
    assert not _has_visibility_report_link("No report link here.")

    assert _visibility_report_outbound_ready({
        "email_variants": [{"gates": {"outbound_ready": True}}],
    })
    assert not _visibility_report_outbound_ready({
        "email_variants": [{"gates": {"outbound_ready": False}}],
    })
    assert not _visibility_report_outbound_ready({})


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

    resend_state = _conversation_state(
        reply_count=0,
        zoho_sent_count=0,
        resend_sent_count=1,
    )

    assert not resend_state["is_first_touch"]
    assert resend_state["prior_outbound_count"] == 1
    assert resend_state["has_resend_sent_history"]
    assert resend_state["prior_outbound_source"] == "resend_logs"


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


@pytest.mark.asyncio
async def test_competitive_context_filters_dedupes_and_caps(monkeypatch):
    async def fake_get_competitors(**kwargs):
        assert kwargs["pif_id"] == "pif-target"
        return {
            "firm": {
                "pif_id": "pif-target",
                "firm_name": "Target Injury Law",
                "domain": "targetlaw.com",
                "metro": "los-angeles",
            },
            "competitors": [
                {
                    "pif_id": "pif-vendor",
                    "firm_name": "Precise Imaging",
                    "domain": "precisemri.com",
                    "metro": "los-angeles",
                    "score": 0.99,
                    "components": {"geo": 1.0, "case_mix": 1.0},
                    "evidence": {"why": "same metro"},
                },
                {
                    "pif_id": "pif-beta",
                    "firm_name": "Beta Accident Law",
                    "domain": "betalaw.com",
                    "metro": "los-angeles",
                    "score": 0.91,
                    "components": {"geo": 1.0, "case_mix": 1.0, "value_tier": 1.0},
                    "evidence": {"why": "same metro; case mix"},
                },
                {
                    "pif_id": "pif-beta-duplicate",
                    "firm_name": "Beta Accident Law APC",
                    "domain": "betalaw.com",
                    "metro": "los-angeles",
                    "score": 0.89,
                    "components": {"geo": 1.0, "case_mix": 1.0},
                    "evidence": {"why": "duplicate domain"},
                },
                {
                    "pif_id": "pif-gamma",
                    "firm_name": "Gamma Trial Lawyers",
                    "domain": "gammatrial.com",
                    "metro": "los-angeles",
                    "score": 0.73,
                    "components": {"geo": 1.0, "case_mix": 0.8},
                    "evidence": {"why": "same metro"},
                },
            ],
        }

    monkeypatch.setattr("app.services.lead_email_composer._get_competitors_for_context", fake_get_competitors)
    contact = ContactStub(pif_id="pif-target", email="owner@targetlaw.com")

    context = await fetch_competitive_context_for_email(
        contact=contact,  # type: ignore[arg-type]
        firm_name="Target Injury Law",
        limit=2,
    )

    assert context["status"] == "ok"
    assert [row["firm_name"] for row in context["competitors"]] == [
        "Beta Accident Law",
        "Gamma Trial Lawyers",
    ]
    assert context["competitors"][0]["confidence"] == "high"
    assert "Do not name competitors" in context["usage_guidance"]


@pytest.mark.asyncio
async def test_competitive_context_soft_fails_without_identifier():
    contact = ContactStub(pif_id=None, email=None)

    context = await fetch_competitive_context_for_email(
        contact=contact,  # type: ignore[arg-type]
        firm_name="Unknown Firm",
    )

    assert context["status"] == "unavailable"
    assert context["competitors"] == []
