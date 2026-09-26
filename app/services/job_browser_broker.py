"""Own Playwright independently of the application worker; private Unix socket only.

Restarting this service DOES destroy browsers. Restarting the backend does not.
Tombstones prevent an old run from silently opening a new page after broker loss.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
import fcntl
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.services.job_browser_tools import BrowserAction, BrowserSession

ROOT = Path(__file__).resolve().parents[2] / 'var/job-browser'


def socket_path():
    return os.getenv('JOB_BROWSER_SOCKET', str(ROOT / 'broker.sock'))


@contextmanager
def private_socket(path):
    """Pre-bind: uvicorn's own UDS binding otherwise changes its mode to 0666."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_fd = os.open(str(path) + '.lock', os.O_CREAT | os.O_RDWR, 0o600)
    bound = None
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path.unlink(missing_ok=True)  # Only the exclusive owner may clear a stale socket.
        bound = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        bound.bind(str(path))
        path.chmod(0o600)
        bound.setblocking(False)
        yield bound
    finally:
        if bound is not None:
            bound.close()
            path.unlink(missing_ok=True)
        os.close(lock_fd)


def identifier(value: str):
    try:
        if UUID(value).hex != value:
            raise ValueError()
    except ValueError:
        raise HTTPException(422, 'Invalid browser session identifier.')
    return value


class OpenRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    url: str = Field(max_length=2000)


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action_id: str
    observation_id: str
    resume_sha256: str
    action: BrowserAction


@dataclass
class Session:
    browser: BrowserSession
    url: str
    instance: str = field(default_factory=lambda: uuid4().hex)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    observation_id: str | None = None
    operations: dict = field(default_factory=dict)

    def status(self):
        return {'available': bool(self.browser.browser and self.browser.browser.is_connected()),
                'busy': self.lock.locked(), 'instance': self.instance,
                'current_url': self.browser.snapshot.get('url', self.url)}


def create_app(root: Path = ROOT):
    sessions: dict[str, Session] = {}
    creation_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app):
        yield
        for item in list(sessions.values()):
            await item.browser.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    # Exposed to local tests only, never as an HTTP endpoint.
    app.state.sessions = sessions

    def directory(run_id):
        path = root / identifier(run_id)
        if path.is_symlink() or not path.is_dir():
            raise HTTPException(404, 'Saved application directory not found.')
        return path

    def existing(run_id):
        identifier(run_id)
        item = sessions.get(run_id)
        if not item or not item.status()['available']:
            raise HTTPException(410, 'The original browser session is gone. Reconnect cannot recreate it.')
        return item

    @app.get('/health')
    async def health():
        return {'ok': True, 'sessions': len(sessions)}

    @app.get('/sessions/{run_id}')
    async def status(run_id: str):
        identifier(run_id)
        item = sessions.get(run_id)
        return item.status() if item else {'available': False, 'busy': False}

    @app.post('/sessions/{run_id}/open')
    async def open_session(run_id: str, request: OpenRequest):
        path = directory(run_id)
        async with creation_lock:
            if run_id in sessions:
                item = existing(run_id)
                if item.url != request.url:
                    raise HTTPException(409, 'This session already belongs to a different starting URL.')
                return item.status()  # Idempotent reconnect; never navigate again.
            marker = path / 'browser-session.json'
            if marker.exists():
                raise HTTPException(410, 'This browser was closed or lost. Start a new attempt only if submission is ruled out.')
            if len(sessions) >= int(os.getenv('JOB_BROWSER_MAX_SESSIONS', '3')):
                raise HTTPException(409, 'Browser capacity reached. Close an unused session before continuing.')
            item = Session(BrowserSession(), request.url)
            # Write before launch; a crashed or timed-out creation is not blindly retried.
            with marker.open('x') as stream:
                json.dump({'instance': item.instance}, stream)
            marker.chmod(0o600)
            try:
                await item.browser.open(request.url)
            except BaseException:
                await item.browser.close()
                raise
            sessions[run_id] = item
            return item.status()

    @app.post('/sessions/{run_id}/observe')
    async def observe(run_id: str):
        item = existing(run_id)
        async with item.lock:
            item.observation_id = None  # Invalidate old handles even if observation fails.
            snapshot = await item.browser.observe(directory(run_id) / 'page.png')
            item.observation_id = uuid4().hex
            return {'snapshot': snapshot, 'observation_id': item.observation_id}

    @app.post('/sessions/{run_id}/execute')
    async def execute(run_id: str, request: ExecuteRequest):
        identifier(request.action_id)
        item = existing(run_id)
        fingerprint = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
        async with item.lock:
            previous = item.operations.get(request.action_id)
            if previous:
                if previous['fingerprint'] != fingerprint:
                    raise HTTPException(409, 'Action identifier reused with different contents.')
                if previous['status'] != 'completed':
                    raise HTTPException(409, 'This action may have run. Inspect the page; do not replay it.')
                return {'status': 'completed', 'replayed': False, 'already_completed': True}
            if not item.observation_id or request.observation_id != item.observation_id:
                raise HTTPException(409, 'The page observation changed. Inspect again before acting.')
            resume = directory(run_id) / 'resume.pdf'
            if resume.is_symlink() or hashlib.sha256(resume.read_bytes()).hexdigest() != request.resume_sha256:
                raise HTTPException(409, 'The selected resume changed.')
            item.operations[request.action_id] = {'fingerprint': fingerprint, 'status': 'started'}
            item.observation_id = None  # One action per observation.
            try:
                await item.browser.execute(request.action, resume)
            except BaseException:
                item.operations[request.action_id]['status'] = 'uncertain'
                raise
            item.operations[request.action_id]['status'] = 'completed'
            return {'status': 'completed', 'replayed': False}

    @app.delete('/sessions/{run_id}')
    async def close(run_id: str):
        identifier(run_id)
        async with creation_lock:
            item = sessions.get(run_id)
            if item:
                async with item.lock:
                    await item.browser.close()
                    sessions.pop(run_id, None)
        return {'closed': True}

    return app


if __name__ == '__main__':
    import uvicorn
    from dotenv import load_dotenv
    load_dotenv(ROOT.parents[1] / '.env')
    os.umask(0o077)
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    with private_socket(socket_path()) as listener:
        server = uvicorn.Server(uvicorn.Config(create_app(), log_level='warning', access_log=False))
        asyncio.run(server.serve(sockets=[listener]))
