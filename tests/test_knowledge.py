import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.api import knowledge as knowledge_api
from app.services.knowledge import derive_title, normalize_tags


def test_derive_title_uses_first_nonempty_line_and_preserves_content_separately():
    assert derive_title("\n  A useful LinkedIn post  \nBody text") == "A useful LinkedIn post"
    assert len(derive_title("x" * 300)) == 255


def test_normalize_tags_trims_lowercases_and_deduplicates():
    assert normalize_tags([" Intake ", "AI", "intake", ""]) == ["intake", "ai"]


def test_create_request_requires_content_and_valid_http_url():
    with pytest.raises(ValidationError):
        knowledge_api.KnowledgeCreateRequest(content="")
    with pytest.raises(ValidationError):
        knowledge_api.KnowledgeCreateRequest(content="Useful", source_url="not-a-url")


def test_post_knowledge_entry_converts_url_before_persisting(monkeypatch):
    create = AsyncMock(return_value={"id": 1, "title": "Useful"})
    monkeypatch.setattr(knowledge_api, "create_knowledge_entry", create)

    result = asyncio.run(knowledge_api.post_knowledge_entry(
        knowledge_api.KnowledgeCreateRequest(
            content="Useful",
            source_type="linkedin",
            source_url="https://www.linkedin.com/posts/example",
            tags=["AI"],
        )
    ))

    assert result["entry"]["id"] == 1
    create.assert_awaited_once()
    assert create.await_args.kwargs["source_url"].startswith("https://www.linkedin.com/")
