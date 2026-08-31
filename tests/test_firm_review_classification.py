import asyncio

from app.services import firm_review_classification as service


def sample_reviews():
    return {
        "sources": [{
            "source": "bbb",
            "listing_url": "https://www.bbb.org/example",
            "reviews": [{
                "reviewer_name": "Client A",
                "rating": 1,
                "review_date": "2026-08-01",
                "text": "Nobody returned my calls and I never received an update.",
                "review_url": None,
            }],
        }],
    }


def test_review_id_is_stable_and_changes_with_text():
    data = sample_reviews()
    source = data["sources"][0]
    review = source["reviews"][0]

    first = service.review_id(source, review)
    second = service.review_id(source, dict(review))
    changed = service.review_id(source, {**review, "text": "Different text"})

    assert first == second
    assert first.startswith("review_")
    assert changed != first


def test_normalize_classification_enforces_controlled_vocabulary():
    normalized = service.normalize_classification({
        "review_id": "review_1",
        "overall_sentiment": "negative",
        "sentiment_score": -4,
        "source_quality": "independent_review",
        "journey_stages": ["case_management", "made_up"],
        "themes": [{
            "theme": "proactive_updates",
            "sentiment": "negative",
            "intensity": 9,
            "evidence": "never received an update",
            "explicit_or_inferred": "explicit",
        }],
        "failure_modes": ["status_silence", "invented"],
        "process_satisfaction": "negative",
        "outcome_status": "outcome_not_mentioned",
        "outcome_satisfaction": "unknown",
        "actionability": ["directly_controllable"],
        "referral_intent": "negative",
        "information_density": "high",
        "firsthand_signal": "firsthand",
        "confidence": 1.4,
    }, "review_1")

    assert normalized["sentiment_score"] == -1.0
    assert normalized["confidence"] == 1.0
    assert normalized["journey_stages"] == ["case_management"]
    assert normalized["failure_modes"] == ["status_silence"]
    assert normalized["themes"][0]["intensity"] == 3


def test_classify_reviews_json_attaches_versioned_classification(monkeypatch):
    async def fake_batch(firm_name, reviews, semaphore):
        assert firm_name == "Example Law"
        return [{
            "review_id": reviews[0]["review_id"],
            "overall_sentiment": "negative",
            "sentiment_score": -0.9,
            "source_quality": "independent_review",
            "journey_stages": ["case_management"],
            "themes": [],
            "praise_drivers": [],
            "failure_modes": ["no_callback", "status_silence"],
            "staff_roles_mentioned": ["firm_generally"],
            "process_satisfaction": "negative",
            "outcome_status": "outcome_not_mentioned",
            "outcome_satisfaction": "unknown",
            "actionability": ["directly_controllable"],
            "operational_owners": ["case_management"],
            "referral_intent": "unclear",
            "information_density": "medium",
            "firsthand_signal": "firsthand",
            "confidence": 0.95,
        }]

    monkeypatch.setattr(service, "_classify_batch", fake_batch)
    result = asyncio.run(service.classify_reviews_json("Example Law", sample_reviews()))
    review = result["sources"][0]["reviews"][0]

    assert result["classification_status"] == "completed"
    assert result["classified_count"] == 1
    assert result["unclassified_count"] == 0
    assert review["review_id"].startswith("review_")
    assert review["classification"]["classification_version"] == service.CLASSIFICATION_VERSION
    assert review["classification"]["failure_modes"] == ["no_callback", "status_silence"]


def test_classify_reviews_locally_produces_complete_baseline_tags():
    result = service.classify_reviews_locally(sample_reviews())
    classification = result["sources"][0]["reviews"][0]["classification"]

    assert result["classification_status"] == "completed"
    assert result["classified_count"] == 1
    assert classification["classification_method"] == "local_rules_v1"
    assert classification["overall_sentiment"] == "negative"
    assert classification["failure_modes"] == ["no_callback", "status_silence"]
    assert any(theme["theme"] == "proactive_updates" for theme in classification["themes"])
