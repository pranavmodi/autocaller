from types import SimpleNamespace

from app.services.aiaudit_links import build_audit_link, build_audit_token, verify_audit_token


def test_audit_token_round_trip(monkeypatch):
    monkeypatch.setenv("AIAUDIT_LINK_SECRET", "test-secret")

    token = build_audit_token(
        contact_id="contact-1",
        pif_id="pif-1",
        batch_item_id="item-1",
        source="ai_audit_signature",
    )

    payload = verify_audit_token(token)
    assert payload is not None
    assert payload["contact_id"] == "contact-1"
    assert payload["pif_id"] == "pif-1"
    assert payload["batch_item_id"] == "item-1"
    assert payload["source"] == "ai_audit_signature"
    assert payload["nonce"]


def test_audit_token_rejects_tampering(monkeypatch):
    monkeypatch.setenv("AIAUDIT_LINK_SECRET", "test-secret")

    token = build_audit_token(contact_id="contact-1", source="ai_audit_email")
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")

    assert verify_audit_token(tampered) is None


def test_build_audit_link_uses_outreach_public_base(monkeypatch):
    monkeypatch.setenv("AIAUDIT_LINK_SECRET", "test-secret")
    monkeypatch.setenv("OUTREACH_PUBLIC_BASE_URL", "https://possible.example")
    contact = SimpleNamespace(id="contact-1", pif_id="pif-1")

    url = build_audit_link(contact, batch_item_id="item-1", source="ai_audit_signature")

    assert url.startswith("https://possible.example/aiaudit/go?t=")
    assert verify_audit_token(url.split("t=", 1)[1])["contact_id"] == "contact-1"
