import httpx
import pytest

from app.services.listening_client import (
    ListeningClient,
    ListeningClientError,
    MissionControlUnavailable,
)


@pytest.mark.asyncio
async def test_listening_client_fetches_brief_version():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/listening/brief"
        assert request.url.params["version"] == "2"
        return httpx.Response(200, json={"version": 2, "brief_md": "# Brief"})

    client = ListeningClient(
        base_url="http://mc.test/api/listening",
        transport=httpx.MockTransport(handler),
    )

    data = await client.brief(version=2)

    assert data["version"] == 2
    assert data["brief_md"] == "# Brief"


@pytest.mark.asyncio
async def test_listening_client_searches_insights_with_filters():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/listening/insights"
        assert request.url.params["q"] == "intake"
        assert request.url.params["type"] == "objection"
        assert request.url.params["who"] == "intake_manager"
        assert request.url.params["limit"] == "5"
        return httpx.Response(200, json={"insights": [{"id": 1}]})

    client = ListeningClient(
        base_url="http://mc.test/api/listening",
        transport=httpx.MockTransport(handler),
    )

    data = await client.insights(
        q="intake",
        insight_type="objection",
        who="intake_manager",
        limit=5,
    )

    assert data["insights"] == [{"id": 1}]


@pytest.mark.asyncio
async def test_listening_client_reports_mission_control_unreachable():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    client = ListeningClient(
        base_url="http://mc.test/api/listening",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(MissionControlUnavailable, match="unreachable"):
        await client.stats()


@pytest.mark.asyncio
async def test_listening_client_reports_http_errors():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "busy"})

    client = ListeningClient(
        base_url="http://mc.test/api/listening",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ListeningClientError, match="HTTP 503"):
        await client.sources()
