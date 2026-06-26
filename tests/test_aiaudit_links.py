import asyncio
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from app.api import aiaudit
from app.db.models import FirmContactRow
from app.services.aiaudit_links import build_audit_link, build_audit_token, verify_audit_token
from app.services.aiaudit_prefill import audit_preanswer_params


class FakeResult:
    def __init__(self, *, rows=None, row=None):
        self._rows = rows or []
        self._row = row

    def all(self):
        return self._rows

    def one(self):
        return self._row


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


def test_audit_token_uses_auth_session_secret_fallback(monkeypatch):
    monkeypatch.delenv("AIAUDIT_LINK_SECRET", raising=False)
    monkeypatch.setenv("AUTH_SESSION_SECRET", "session-secret")

    token = build_audit_token(contact_id="contact-1", source="ai_audit_email")

    assert verify_audit_token(token)["contact_id"] == "contact-1"


def test_audit_preanswer_params_only_uses_high_confidence_case_systems():
    assert audit_preanswer_params(
        contact_tech_signals={"case_mgmt": "Filevine"}
    ) == {"pa.case_system": "3"}
    assert audit_preanswer_params(
        contact_tech_signals={"case_mgmt": "unknown"}
    ) == {}
    assert audit_preanswer_params(contact_tech_signals={}) == {}


def test_prefill_for_payload_adds_case_system_preanswer(monkeypatch):
    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, model, key):
            if model is FirmContactRow:
                return SimpleNamespace(
                    pif_id="pif-1",
                    tech_signals={"case_mgmt": "filevine"},
                )
            return None

    monkeypatch.setattr(aiaudit, "AsyncSessionLocal", lambda: FakeSession())

    async def fake_resolve_firm_name(pif_id):
        return "Demo Firm"

    monkeypatch.setattr(aiaudit, "resolve_firm_name", fake_resolve_firm_name)

    query = asyncio.run(aiaudit._prefill_for_payload({"contact_id": "contact-1"}))

    assert query["firm"] == "Demo Firm"
    assert query["case_mgmt"] == "filevine"
    assert query["pa.case_system"] == "3"


def test_click_analytics_includes_human_session_rollup(monkeypatch):
    compiled_sql = []

    class FakeSession:
        def __init__(self):
            self.results = [
                FakeResult(rows=[]),
                FakeResult(rows=[]),
                FakeResult(row=(1, 1, 1, None, None)),
                FakeResult(row=SimpleNamespace(
                    human_session_count=2,
                    distinct_human_sessions=2,
                )),
                FakeResult(rows=[
                    SimpleNamespace(
                        page="/consult",
                        sessions=2,
                        distinct_sessions=2,
                        median_time_on_page_ms=1500,
                    ),
                ]),
                FakeResult(rows=[
                    SimpleNamespace(day="2026-06-26", distinct_sessions=2),
                ]),
            ]

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def execute(self, _stmt):
            compiled_sql.append(str(_stmt.compile(dialect=postgresql.dialect())))
            return self.results.pop(0)

    monkeypatch.setattr(aiaudit, "AsyncSessionLocal", lambda: FakeSession())

    response = asyncio.run(
        aiaudit.audit_click_analytics(
            since_days=30,
            group_by="firm_name",
            limit=50,
        )
    )

    assert response["summary"]["click_count"] == 1
    assert response["summary"]["human_session_count"] == 2
    assert response["summary"]["distinct_human_sessions"] == 2
    assert response["summary"]["human_to_click_ratio"] == 2.0
    assert response["human_sessions_by_page"] == [
        {
            "page": "/consult",
            "sessions": 2,
            "distinct_sessions": 2,
            "median_time_on_page_ms": 1500.0,
        },
    ]
    assert response["human_sessions_by_day"] == [
        {"day": "2026-06-26", "distinct_sessions": 2},
    ]
    assert any("lead_gen_observations" in sql for sql in compiled_sql)
    assert any("percentile_cont" in sql for sql in compiled_sql)
