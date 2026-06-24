from types import SimpleNamespace

import pytest

from app.db.models import FirmContactRow, LeadGenBatchItemRow
from app.services import lead_gen_email_agent


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, model, key):
        if model is FirmContactRow:
            return SimpleNamespace(
                id=key,
                pif_id="p1",
                email="owner@example.com",
                full_name="Owner",
                linkedin_url=None,
            )
        if model is LeadGenBatchItemRow:
            return SimpleNamespace(id=key, batch_id="batch-1", reason_json={})
        return None

    async def commit(self):
        return None


@pytest.mark.asyncio
async def test_ai_audit_first_touch_bypasses_review_evidence_gate(monkeypatch):
    item = {
        "id": "item-1",
        "contact_id": "contact-1",
        "pif_id": "p1",
        "firm_name": "Firm LLP",
        "contact_name": "Owner",
        "contact_email": "owner@example.com",
        "persona": "founder_owner",
        "template_key": "possible_minds_dynamic",
        "approval_status": "pending",
        "score": 90,
        "reason": {"action_type": "first_touch"},
    }

    async def fake_get_batch(*_args, **_kwargs):
        return {"batch": {"id": "batch-1"}, "items": [item], "observations": []}

    async def fake_research(**_kwargs):
        return {"status": "ok"}

    async def fake_compose(**kwargs):
        assert kwargs["composer_variant_key"] == "ai-audit"
        return SimpleNamespace(
            subject="Subject",
            body="Body",
            reasoning="Reason",
            angle="audit",
            cta="cta",
            risk_flags=[],
            requires_human_review=False,
            blog_link_used=None,
            composer_experiment_key=None,
            composer_variant_key="ai-audit",
            skill_path="skill",
            skill_sha256="sha",
            brief_version="v1",
        )

    async def fake_create_action(**_kwargs):
        return {"id": "action-1", "status": "waiting_for_approval"}

    async def fake_trace(**_kwargs):
        return None

    monkeypatch.setenv("REQUIRE_REVIEW_EVIDENCE_FIRST_TOUCH", "true")
    monkeypatch.setattr(lead_gen_email_agent, "get_batch", fake_get_batch)
    monkeypatch.setattr(lead_gen_email_agent, "AsyncSessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(lead_gen_email_agent, "research_contact_context", fake_research)
    monkeypatch.setattr(lead_gen_email_agent, "compose_lead_email", fake_compose)
    monkeypatch.setattr(lead_gen_email_agent, "create_send_email_action", fake_create_action)
    monkeypatch.setattr(lead_gen_email_agent, "safe_record_product_trace", fake_trace)

    result = await lead_gen_email_agent._compose_batch_items(
        batch_id="batch-1",
        created_by="operator",
        composer_variant_key="ai-audit",
        approve_actions=False,
        policy_check_first_action=False,
        template_key="possible_minds_dynamic",
        only_undrafted_pending=True,
        limit=1,
    )

    assert result["held"] == []
    assert len(result["drafts"]) == 1
    assert result["drafts"][0]["action_id"] == "action-1"
