"""Carrier status + switcher endpoints.

GET  /api/carrier       — full status for both Twilio + Telnyx; marks which is default
PUT  /api/carrier       — set the DB default_carrier (body: {"carrier": "twilio"|"telnyx"})
GET  /api/carrier/list  — lightweight list for populating UI dropdowns
"""
import base64
import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.providers.settings_provider import get_settings_provider

router = APIRouter(prefix="/api", tags=["carrier"])


def _mask(value: str, keep_head: int = 4, keep_tail: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= keep_head + keep_tail:
        return "*" * len(value)
    return f"{value[:keep_head]}…{value[-keep_tail:]}"


async def _describe_twilio() -> dict[str, Any]:
    """Fetch live Twilio account + balance + number status."""
    s = get_settings()
    out: dict[str, Any] = {
        "provider": "twilio",
        "label": (os.getenv("TWILIO_ACCOUNT_LABEL", "") or "").strip() or None,
        "account_sid": s.twilio_account_sid,
        "account_sid_masked": _mask(s.twilio_account_sid),
        "from_number": s.twilio_from_number,
        "configured": bool(s.twilio_account_sid and s.twilio_auth_token and s.twilio_from_number),
        "status": None,
        "account_type": None,
        "account_name": None,
        "balance": None,
        "currency": None,
        "number_status": None,
        "reachable": False,
        "error": None,
    }
    if not out["configured"]:
        out["error"] = "TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM_NUMBER not set"
        return out

    basic = base64.b64encode(
        f"{s.twilio_account_sid}:{s.twilio_auth_token}".encode()
    ).decode()
    headers = {"Authorization": f"Basic {basic}"}
    base = f"https://api.twilio.com/2010-04-01/Accounts/{s.twilio_account_sid}"
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            acct = await client.get(f"{base}.json", headers=headers)
            bal = await client.get(f"{base}/Balance.json", headers=headers)
            nums = await client.get(
                f"{base}/IncomingPhoneNumbers.json",
                headers=headers,
                params={"PhoneNumber": s.twilio_from_number},
            )
        if acct.status_code == 200:
            a = acct.json()
            out["status"] = a.get("status")
            out["account_type"] = a.get("type")
            out["account_name"] = a.get("friendly_name")
            out["reachable"] = True
        else:
            out["error"] = f"account HTTP {acct.status_code}"
        if bal.status_code == 200:
            b = bal.json()
            out["balance"] = b.get("balance")
            out["currency"] = b.get("currency")
        if nums.status_code == 200:
            items = nums.json().get("incoming_phone_numbers", [])
            if items:
                out["number_status"] = items[0].get("status")
    except Exception as e:
        out["error"] = str(e)[:200]
    return out


async def _describe_telnyx() -> dict[str, Any]:
    """Fetch live Telnyx balance + number config."""
    api_key = os.getenv("TELNYX_API_KEY", "")
    from_number = os.getenv("TELNYX_FROM_NUMBER", "")
    label = (os.getenv("TELNYX_ACCOUNT_LABEL", "") or "").strip() or None
    out: dict[str, Any] = {
        "provider": "telnyx",
        "label": label,
        "account_sid": "",
        "account_sid_masked": _mask(api_key),
        "from_number": from_number,
        "configured": bool(api_key and from_number),
        "status": None,
        "account_type": None,
        "account_name": None,
        "balance": None,
        "currency": None,
        "number_status": None,
        "reachable": False,
        "error": None,
    }
    if not out["configured"]:
        out["error"] = "TELNYX_API_KEY / TELNYX_FROM_NUMBER not set"
        return out

    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            bal = await client.get("https://api.telnyx.com/v2/balance", headers=headers)
            num = await client.get(
                "https://api.telnyx.com/v2/phone_numbers",
                headers=headers,
                params={"filter[phone_number]": from_number},
            )
        if bal.status_code == 200:
            b = bal.json().get("data", {})
            out["balance"] = b.get("balance")
            out["currency"] = b.get("currency")
            out["reachable"] = True
            # Telnyx doesn't have a first-class "status" on the balance API;
            # treat reachable+configured as "active" for UI consistency.
            out["status"] = "active"
        else:
            out["error"] = f"balance HTTP {bal.status_code}: {bal.text[:120]}"
        if num.status_code == 200:
            items = num.json().get("data", [])
            if items:
                out["number_status"] = items[0].get("status")
    except Exception as e:
        out["error"] = str(e)[:200]
    return out


@router.get("/carrier")
async def get_carrier():
    """Show status for both carriers + the current default."""
    settings = await get_settings_provider().get_settings()
    default = (getattr(settings, "default_carrier", "twilio") or "twilio").lower()

    twilio_info = await _describe_twilio()
    telnyx_info = await _describe_telnyx()

    # Return a flat shape matching v1 (active carrier's fields at top level)
    # plus a `carriers` dict so clients can see both. The top-level fields
    # reflect whichever is currently default so existing UI keeps working.
    active = telnyx_info if default == "telnyx" else twilio_info

    return {
        **active,
        "provider": active["provider"],
        "default_carrier": default,
        "carriers": {"twilio": twilio_info, "telnyx": telnyx_info},
    }


@router.put("/carrier")
async def set_carrier(body: dict):
    """Set the DB default_carrier. Body: {"carrier": "twilio" | "telnyx"}."""
    new = str(body.get("carrier", "") or "").strip().lower()
    if new not in ("twilio", "telnyx"):
        raise HTTPException(status_code=400, detail="carrier must be 'twilio' or 'telnyx'")
    sp = get_settings_provider()
    settings = await sp.get_settings()
    settings.default_carrier = new
    await sp.save_settings(settings)
    return {"default_carrier": new}
