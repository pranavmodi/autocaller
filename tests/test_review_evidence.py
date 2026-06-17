"""Phase-1 review-intelligence: v1/v2 evidence parsing + filtering."""
from app.services.review_extraction import evidence_items_from_extraction


def test_v2_evidence_parsed_with_kinds():
    extraction = {
        "extractor_version": "review-intel-v2",
        "evidence": [
            {"kind": "complaint", "theme": "client_communication",
             "quote": "No one called me back.", "confidence": 0.9, "outreach_usable": True},
            {"kind": "praise", "theme": "staff_empathy",
             "quote": "The team was so kind.", "confidence": 0.8, "outreach_usable": True},
            {"kind": "fact", "theme": "language_access",
             "quote": None, "paraphrase": "Offers Spanish-language intake.",
             "confidence": 0.7, "outreach_usable": True},
        ],
    }
    items = evidence_items_from_extraction(extraction)
    assert {e["kind"] for e in items} == {"complaint", "praise", "fact"}
    # ids auto-assigned, confidence coerced to float
    assert all(isinstance(e["confidence"], float) for e in items)


def test_v1_pain_points_mapped_to_complaints():
    extraction = {
        "extractor_version": "yelp-quotes-v1",
        "pain_points": {
            "client_communication": [
                {"quote": "Never heard back.", "reviewer_name": "Jane D.", "confidence": 0.92},
            ]
        },
    }
    items = evidence_items_from_extraction(extraction)
    assert len(items) == 1
    item = items[0]
    assert item["kind"] == "complaint"
    assert item["theme"] == "client_communication"
    assert item["quote"] == "Never heard back."
    assert item["sentiment"] < 0  # complaint default sentiment is negative


def test_unknown_kind_falls_back_to_complaint():
    items = evidence_items_from_extraction(
        {"evidence": [{"kind": "weird", "theme": "x", "quote": "q", "confidence": 0.5}]}
    )
    assert items[0]["kind"] == "complaint"


def test_empty_and_malformed_inputs():
    assert evidence_items_from_extraction(None) == []
    assert evidence_items_from_extraction({}) == []
    assert evidence_items_from_extraction({"evidence": "notalist"}) == []
