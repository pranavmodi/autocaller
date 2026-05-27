"""Public Resend webhook endpoint."""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request

from app.services.resend_webhooks import (
    ResendWebhookVerificationError,
    ingest_resend_webhook,
    parse_resend_event,
    verify_svix_signature,
)


router = APIRouter(tags=["resend-webhooks"])


def _is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost", ""}


@router.post("/api/resend/webhook")
async def resend_webhook(request: Request):
    raw_body = await request.body()
    secret = os.getenv("RESEND_WEBHOOK_SECRET", "").strip()
    if secret:
        try:
            verify_svix_signature(
                payload=raw_body,
                headers=request.headers,
                secret=secret,
            )
        except ResendWebhookVerificationError as e:
            raise HTTPException(status_code=400, detail=str(e))
    elif not (
        _is_loopback(request)
        or os.getenv("RESEND_WEBHOOK_ALLOW_UNSIGNED", "").lower() in {"1", "true", "yes"}
    ):
        raise HTTPException(status_code=503, detail="resend_webhook_secret_not_configured")

    try:
        payload = parse_resend_event(raw_body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return await ingest_resend_webhook(
        payload,
        provider_event_id=request.headers.get("svix-id"),
    )
