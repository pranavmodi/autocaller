"""Operator password auth for the autocaller UI + API.

Single shared password, HMAC-signed session cookie, 30-day expiry. No
user accounts — this is a one-operator tool. When the ops footprint
grows, swap in a real IdP.

Enforcement lives in `AuthMiddleware` (registered in `app/main.py`).
Twilio/Cal.com webhooks + loopback CLI traffic are exempt so the
media-stream + server-to-server paths keep working.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_COOKIE = "ac_sess"
SESSION_DURATION_SECS = 30 * 24 * 3600  # 30 days


def _password() -> str:
    return os.getenv("AUTH_PASSWORD", "")


def _secret() -> bytes:
    s = os.getenv("AUTH_SESSION_SECRET", "").strip()
    if not s:
        # Hard-fail rather than silently using an empty secret — signed
        # cookies with a blank key are forgeable.
        raise RuntimeError("AUTH_SESSION_SECRET must be set when AUTH_PASSWORD is configured")
    return s.encode("utf-8")


def _cookie_secure() -> bool:
    # In prod we want Secure (HTTPS only). Allow disable for local dev.
    return os.getenv("AUTH_COOKIE_SECURE", "true").lower() not in ("false", "0", "no")


def _sign(payload: str) -> str:
    return hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def make_session_token() -> str:
    exp = int(time.time()) + SESSION_DURATION_SECS
    nonce = secrets.token_hex(8)
    payload = f"{exp}.{nonce}"
    return f"{payload}.{_sign(payload)}"


def verify_session_token(token: str) -> bool:
    if not token or not isinstance(token, str):
        return False
    parts = token.split(".")
    if len(parts) != 3:
        return False
    exp_str, nonce, sig = parts
    payload = f"{exp_str}.{nonce}"
    try:
        expected = _sign(payload)
    except RuntimeError:
        # Secret not configured — reject silently rather than 500.
        return False
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        if int(exp_str) < int(time.time()):
            return False
    except ValueError:
        return False
    return True


def auth_configured() -> bool:
    """Is password auth enabled at all? If not, the middleware lets all
    traffic through (dev-mode behaviour). Treat as enabled when BOTH
    AUTH_PASSWORD and AUTH_SESSION_SECRET are set."""
    return bool(_password()) and bool(os.getenv("AUTH_SESSION_SECRET", "").strip())


class LoginRequest(BaseModel):
    password: str


@router.post("/login")
async def login(body: LoginRequest, response: Response) -> dict:
    if not auth_configured():
        # If auth isn't configured, login always succeeds without
        # setting a cookie — the middleware lets traffic through
        # anyway. This keeps dev flows frictionless.
        return {"ok": True, "configured": False}
    pw = body.password or ""
    if not hmac.compare_digest(pw, _password()):
        raise HTTPException(status_code=401, detail="Invalid password")
    token = make_session_token()
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_DURATION_SECS,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(),
        path="/",
    )
    return {"ok": True, "configured": True}


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
async def me(request: Request) -> dict:
    if not auth_configured():
        return {"authenticated": True, "configured": False}
    token = request.cookies.get(SESSION_COOKIE, "")
    return {
        "authenticated": verify_session_token(token),
        "configured": True,
    }
