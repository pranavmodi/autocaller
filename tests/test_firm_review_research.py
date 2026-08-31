from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import firm_reviews
from app.services.firm_review_research import normalize_review_sources


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
    assert result[0]["reviews"] == [{
        "reviewer_name": "Jane D.",
        "rating": 5.0,
        "review_date": "2026-08-30",
        "text": "They kept me informed throughout the case.",
        "review_url": "https://maps.google.com/example/review/1",
    }]


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
