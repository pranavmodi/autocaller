"""Evidence-aware daily selection: prefer firms with usable review evidence
while reserving a few discovery slots for no-evidence firms."""
from app.services.lead_gen_daily import _select_by_persona_quota


def _recs(n):
    # descending score; one persona so quota never binds in these tests
    return [{"pif_id": f"f{i}", "persona": "p", "score": 100 - i, "firm_name": f"F{i}"} for i in range(n)]


QUOTA = {"p": 1000}


def test_low_scored_evidence_firms_are_pulled_in():
    recs = _recs(25)
    evidence = {f"f{i}" for i in range(15, 25)}  # 10 evidence firms, all low-scored
    sel = _select_by_persona_quota(recs, quota=QUOTA, batch_size=20,
                                   evidence_pifs=evidence, no_evidence_reserve=3)
    ids = {r["pif_id"] for r in sel}
    assert len(sel) == 20
    assert evidence <= ids  # every evidence firm made it in despite low score


def test_evidence_capped_by_reserve_when_plentiful():
    recs = _recs(40)
    evidence = {f"f{i}" for i in range(40)}  # everyone has evidence
    # 5 of them aren't evidence so a reserve is possible
    evidence -= {f"f{i}" for i in range(35, 40)}
    sel = _select_by_persona_quota(recs, quota=QUOTA, batch_size=20,
                                   evidence_pifs=evidence, no_evidence_reserve=3)
    n_ev = sum(1 for r in sel if r["pif_id"] in evidence)
    assert len(sel) == 20
    assert n_ev == 17  # batch_size - reserve
    assert 20 - n_ev == 3  # reserved discovery slots filled with no-evidence


def test_reserve_not_forced_when_no_no_evidence_firms():
    recs = _recs(20)
    evidence = {r["pif_id"] for r in recs}  # all evidence, none to reserve
    sel = _select_by_persona_quota(recs, quota=QUOTA, batch_size=20,
                                   evidence_pifs=evidence, no_evidence_reserve=3)
    assert len(sel) == 20
    assert all(r["pif_id"] in evidence for r in sel)  # reserve shrinks to 0


def test_backcompat_score_only_when_no_evidence_set():
    recs = _recs(25)
    sel = _select_by_persona_quota(recs, quota=QUOTA, batch_size=20)
    assert [r["pif_id"] for r in sel] == [f"f{i}" for i in range(20)]
