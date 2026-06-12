"""Selection must consider prior email history (fix for the blind-selection gap).

Query order in recommend_sequence_contacts:
 1 policy row, 2 sms_pifs, 3 call patient_ids, 4 emailed_contact_emails,
 5 emailed_pifs_all, 6 recent_emailed_pifs, 7 batch_contact_ids,
 8 recent_batch_pifs, 9 sequence_contact_ids, [10 sequenced_pifs if 9 nonempty],
 11 contacts, 12 patient_rows, 13 front_warm_rows
"""
from types import SimpleNamespace

import pytest

from app.services import sequence_recommendations as sr


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, results):
        self._results = list(results)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, _stmt):
        return _Result(self._results.pop(0))


def _contact(cid, pif, email, name="Jane Founder", title="Founder"):
    return SimpleNamespace(
        id=cid, pif_id=pif, email=email, full_name=name, title=title,
        source="pif_leadership",
    )


@pytest.mark.asyncio
async def test_prior_email_contact_and_recent_firm_are_suppressed(monkeypatch):
    contacts = [
        # emailed before (recipient match) -> suppressed_prior_email_contact
        _contact("c-emailed", "pif-old", "emailed@oldfirm.com"),
        # sat in a batch before -> suppressed_prior_email_contact
        _contact("c-batched", "pif-batch", "fresh@batchfirm.com"),
        # firm emailed within cooldown (different contact) -> suppressed_recent_email_firm
        _contact("c-recent-firm", "pif-recent", "other@recentfirm.com"),
        # clean candidate at firm emailed long ago -> selected, has_prior_comms=True
        _contact("c-clean-oldfirm", "pif-cold", "new@coldfirm.com"),
        # fully untouched -> selected, has_prior_comms=False
        _contact("c-clean", "pif-fresh", "owner@freshfirm.com"),
    ]
    results = [
        [None],                                   # 1 policy (fallback default)
        [],                                       # 2 sms_pifs
        [],                                       # 3 call patient ids
        ["emailed@oldfirm.com"],                  # 4 emailed_contact_emails (sent)
        ["pif-cold"],                             # 5 emailed_pifs_all (old send)
        ["pif-recent"],                           # 6 recent_emailed_pifs
        ["c-batched"],                            # 7 batch_contact_ids
        ["pif-recent"],                           # 8 recent_batch_pifs
        [],                                       # 9 sequence_contact_ids
        contacts,                                 # 11 contacts (10 skipped: 9 empty)
        [("pif-old", "Old Firm", "CA"), ("pif-batch", "Batch Firm", "CA"),
         ("pif-recent", "Recent Firm", "CA"), ("pif-cold", "Cold Firm", "CA"),
         ("pif-fresh", "Fresh Firm", "CA")],      # 12 patient rows
        [],                                       # 13 front warm rows
    ]
    # patient rows arrive as (patient_id, firm_name, state) with pif-/mc- keys
    results[10] = [(f"pif-{p}", n, s) for p, n, s in
                   [("pif-old", "Old Firm", "CA"), ("pif-batch", "Batch Firm", "CA"),
                    ("pif-recent", "Recent Firm", "CA"), ("pif-cold", "Cold Firm", "CA"),
                    ("pif-fresh", "Fresh Firm", "CA")]]

    monkeypatch.setattr(sr, "AsyncSessionLocal", lambda: _FakeSession(results))

    out = await sr.recommend_sequence_contacts(template_key="possible_minds_dynamic", limit=10)

    picked = {r["contact_id"] for r in out["recommended"]}
    assert "c-emailed" not in picked
    assert "c-batched" not in picked
    assert "c-recent-firm" not in picked
    assert "c-clean" in picked
    assert "c-clean-oldfirm" in picked

    counts = out["counts"]
    assert counts["suppressed_prior_email_contact"] == 2
    assert counts["suppressed_recent_email_firm"] == 1

    by_id = {r["contact_id"]: r for r in out["recommended"]}
    assert by_id["c-clean-oldfirm"]["selection_features"]["has_prior_comms"] is True
    assert by_id["c-clean"]["selection_features"]["has_prior_comms"] is False
