"""Mission Control listening-system client.

Autocaller is a read-only consumer of the listening API. Keep this module thin:
normalize loopback HTTP errors into operator-friendly exceptions, and leave the
Mission Control data model intact for callers that need raw detail.
"""
from __future__ import annotations

import os
from typing import Any

import httpx


LISTENING_BASE_URL = os.getenv(
    "LISTENING_API_BASE_URL",
    "http://127.0.0.1:8001/api/listening",
).rstrip("/")


class ListeningClientError(RuntimeError):
    """Raised when Mission Control's listening API cannot satisfy a request."""


class MissionControlUnavailable(ListeningClientError):
    """Raised when Mission Control is down, slow, or unreachable."""


def _clean_params(params: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if value is not None}


class ListeningClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_s: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or LISTENING_BASE_URL).rstrip("/")
        self.timeout_s = timeout_s or float(os.getenv("LISTENING_API_TIMEOUT_S", "45"))
        self.transport = transport

    async def _get(self, path: str, **params: Any) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_s,
                transport=self.transport,
            ) as client:
                resp = await client.get(url, params=_clean_params(params) or None)
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException as e:
            raise MissionControlUnavailable(
                f"Mission Control listening API timed out after {self.timeout_s:.0f}s."
            ) from e
        except httpx.ConnectError as e:
            raise MissionControlUnavailable(
                "Mission Control listening API is unreachable at "
                f"{self.base_url}. Is Mission Control running on :8001?"
            ) from e
        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response is not None else "unknown"
            body = (e.response.text if e.response is not None else "")[:240]
            raise ListeningClientError(
                f"Mission Control listening API returned HTTP {status}: {body}"
            ) from e
        except httpx.HTTPError as e:
            raise MissionControlUnavailable(
                f"Mission Control listening API request failed: {e}"
            ) from e
        except ValueError as e:
            raise ListeningClientError(
                "Mission Control listening API returned invalid JSON."
            ) from e
        if not isinstance(data, dict):
            raise ListeningClientError(
                "Mission Control listening API returned a non-object JSON payload."
            )
        return data

    async def brief(self, *, version: int | None = None) -> dict[str, Any]:
        return await self._get("/brief", version=version)

    async def insights(
        self,
        *,
        q: str | None = None,
        insight_type: str | None = None,
        cluster: str | None = None,
        who: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return await self._get(
            "/insights",
            q=q,
            type=insight_type,
            cluster=cluster,
            who=who,
            limit=limit,
        )

    async def stats(self) -> dict[str, Any]:
        return await self._get("/stats")

    async def digest(self) -> dict[str, Any]:
        return await self._get("/digest")

    async def sources(
        self,
        *,
        enabled: bool | None = None,
        proposed: bool = False,
        limit: int = 200,
    ) -> dict[str, Any]:
        return await self._get(
            "/sources",
            enabled=enabled,
            proposed=proposed,
            limit=limit,
        )
