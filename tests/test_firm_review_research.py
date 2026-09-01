from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import firm_reviews
from app.services.firm_review_research import (
    INDEPENDENT_REVIEW_SOURCES,
    _domains_match,
    _listing_from_search_payload,
    _reviews_from_profile_payload,
    merge_review_payloads,
    normalize_review_sources,
)


def test_findlaw_is_counted_as_an_independent_review_source():
    assert "findlaw" in INDEPENDENT_REVIEW_SOURCES


def test_google_listing_domain_allows_punctuation_only_variants():
    assert _domains_match("burg-brock.com", "burgbrock.com") is True
    assert _domains_match("examplefirm.com", "differentfirm.com") is False


def test_normalize_review_sources_preserves_verbatim_text_and_deduplicates():
    result = normalize_review_sources([
        {
            "source": "Google",
            "listing_url": "https://maps.google.com/example",
            "coverage_note": "Two public reviews were accessible.",
            "reviews": [
                {
                    "reviewer_name": "Jane D.",
                    "rating": 5,
                    "review_date": "2026-08-30",
                    "text": "They kept me informed throughout the case.",
                    "review_url": "https://maps.google.com/example/review/1",
                },
                {
                    "reviewer_name": "Jane D.",
                    "rating": 5,
                    "review_date": "2026-08-30",
                    "text": "They kept me informed throughout the case.",
                },
            ],
        },
        {
            "source": "Yelp",
            "listing_url": "not-a-url",
            "reviews": [{"text": "Ignore this."}],
        },
    ])

    assert len(result) == 1
    assert result[0]["source"] == "google"
    assert result[0]["coverage_note"] == "Two public reviews were accessible."
    review = result[0]["reviews"][0]
    assert {key: review[key] for key in ("reviewer_name", "rating", "review_date", "text", "review_url")} == {
        "reviewer_name": "Jane D.",
        "rating": 5.0,
        "review_date": "2026-08-30",
        "text": "They kept me informed throughout the case.",
        "review_url": "https://maps.google.com/example/review/1",
    }
    assert len(review["text_hash"]) == 64
    assert review["collected_at"]


def test_normalize_review_sources_rejects_invalid_rating_and_date():
    result = normalize_review_sources([
        {
            "source": "avvo",
            "listing_url": "https://www.avvo.com/example",
            "reviews": [{
                "reviewer_name": "Client",
                "rating": 9,
                "review_date": "August 2026",
                "text": "Very responsive.",
            }],
        },
    ])

    review = result[0]["reviews"][0]
    assert review["rating"] is None
    assert review["review_date"] is None
    assert review["text"] == "Very responsive."


def test_listing_from_google_search_payload_extracts_identity():
    listing = [None] * 19
    listing[7] = [None, "examplefirm.com"]
    listing[10] = "0x1234:0x10"
    listing[11] = "Example Firm"
    row = [None] * 15
    row[14] = listing

    assert _listing_from_search_payload([["query", [row]]]) == {
        "cid": "16",
        "firm_name": "Example Firm",
        "website": "examplefirm.com",
    }


def test_reviews_from_google_profile_payload_preserves_verbatim_record():
    identity = [None] * 5
    identity[2] = 1_725_235_200_000_000
    identity[4] = [None, None, None, None, None, ["Jane D."]]
    content = [None] * 16
    content[0] = [5]
    content[15] = [["They kept me informed throughout the case."]]
    metadata = [None] * 5
    metadata[3] = ["https://www.google.com/maps/reviews/example"]
    record = ["review-id", identity, content, None, metadata]
    payload = [None] * 7
    payload[6] = [None] * 176
    payload[6][175] = [None] * 10
    payload[6][175][9] = [[[[record]]]]

    assert _reviews_from_profile_payload(payload, "https://www.google.com/maps?cid=16") == [{
        "reviewer_name": "Jane D.",
        "rating": 5.0,
        "review_date": "2024-09-02",
        "text": "They kept me informed throughout the case.",
        "review_url": "https://www.google.com/maps/reviews/example",
    }]


def test_review_research_endpoint_queues_local_task(monkeypatch):
    async def fake_start(pif_id: str):
        return {
            "task_id": "firm-reviews-task-1",
            "pif_id": pif_id,
            "firm_name": "Example Injury Law",
            "status": "queued",
            "message": "Queued for local public-review research",
        }

    monkeypatch.setattr(firm_reviews, "start_firm_review_research", fake_start)
    app = FastAPI()
    app.include_router(firm_reviews.router)
    client = TestClient(app)

    response = client.post("/api/firms/firm-1/reviews/research")

    assert response.status_code == 200
    assert response.json()["task_id"] == "firm-reviews-task-1"


def test_merge_review_payloads_never_erases_prior_reviews():
    existing = {
        "sources": [{
            "source": "google",
            "listing_url": "https://maps.google.com/example",
            "coverage_note": "Earlier collection",
            "reviews": [
                {"reviewer_name": "A", "review_date": "2026-01-01", "text": "First review"},
                {"reviewer_name": "B", "review_date": "2026-01-02", "text": "Second review"},
            ],
        }],
    }
    incoming = {
        "sources": [{
            "source": "google",
            "listing_url": "https://maps.google.com/example",
            "coverage_note": "Smaller later sample",
            "reviews": [{"reviewer_name": "A", "review_date": "2026-01-01", "text": "First review"}],
        }],
    }

    merged, summary = merge_review_payloads(existing, incoming)

    assert merged["review_count"] == 2
    assert [review["text"] for review in merged["sources"][0]["reviews"]] == ["First review", "Second review"]
    assert summary["reviews_added"] == 0
    assert summary["deduplicated"] == 1
