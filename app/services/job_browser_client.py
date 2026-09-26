"""Worker-side connection to the separate browser owner. No automatic RPC retries."""
from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import httpx

from app.services.job_browser_broker import socket_path


class PersistentBrowserSession:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.observation_id = None
        self.action_id = None

    async def request(self, method, endpoint='', **kwargs):
        transport = httpx.AsyncHTTPTransport(uds=socket_path(), retries=0)
        try:
            async with httpx.AsyncClient(transport=transport, base_url='http://browser', timeout=90) as client:
                response = await client.request(method, f'/sessions/{self.run_id}{endpoint}', **kwargs)
            if response.is_error:
                try:
                    detail = response.json().get('detail', 'Browser service request failed.')
                except ValueError:
                    detail = 'Browser service request failed; inspect the saved page before retrying.'
                raise ValueError(str(detail))
            return response.json()
        except httpx.TransportError as exc:
            raise ValueError('Cannot reach the browser service. The page may still be open. Reconnect before taking another action.') from exc

    async def status(self):
        return await self.request('GET', timeout=3)

    async def attach(self):
        status = await self.status()
        if not status['available']:
            raise ValueError('The original browser session is gone. Reconnect cannot recreate it. Review submission evidence before starting a new attempt.')
        return status

    async def open(self, url):
        return await self.request('POST', '/open', json={'url': url})

    async def observe(self, screenshot: Path):
        result = await self.request('POST', '/observe')
        self.observation_id = result['observation_id']
        return result['snapshot']

    async def execute(self, action, resume: Path):
        action_id, self.action_id = self.action_id or uuid4().hex, None
        return await self.request('POST', '/execute', json={
            'action_id': action_id, 'observation_id': self.observation_id,
            'resume_sha256': hashlib.sha256(resume.read_bytes()).hexdigest(),
            'action': action.model_dump()})

    async def close(self):
        await self.request('DELETE')

    async def detach(self):
        # Intentionally leaves Playwright, Chromium, page and cookies in the broker.
        self.observation_id = None
