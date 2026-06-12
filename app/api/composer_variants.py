"""Lead email composer skill variant endpoints."""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from app.services.lead_email_composer_variants import (
    composer_variant_stats,
    create_composer_skill_variant,
    discover_composer_skill_variants,
    update_composer_skill_variant_manifest,
    variant_to_dict,
)


router = APIRouter(tags=["composer-variants"])


class UpdateComposerVariantRequest(BaseModel):
    label: str
    description: str | None = None


@router.get("/api/lead-email-composer/variants")
async def list_composer_variants():
    return {
        "variants": [variant_to_dict(variant) for variant in discover_composer_skill_variants()],
    }


@router.patch("/api/lead-email-composer/variants/{variant_key}")
async def update_composer_variant(variant_key: str, req: UpdateComposerVariantRequest):
    try:
        variant = update_composer_skill_variant_manifest(
            variant_key,
            label=req.label,
            description=req.description,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return variant_to_dict(variant)


@router.post("/api/lead-email-composer/variants/upload")
async def upload_composer_variant(
    file: UploadFile = File(...),
    label: str = Form(...),
    description: str = Form(""),
    allocation_weight: int = Form(100),
    active: bool = Form(True),
):
    filename = (file.filename or "").strip()
    if filename and filename != "SKILL.md" and not filename.lower().endswith(".md"):
        raise HTTPException(status_code=400, detail="Upload a SKILL.md markdown file.")
    raw = await file.read()
    try:
        skill_text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise HTTPException(status_code=400, detail="SKILL.md must be UTF-8 text.") from e
    try:
        variant = create_composer_skill_variant(
            label=label,
            description=description,
            skill_text=skill_text,
            allocation_weight=allocation_weight,
            active=active,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return variant_to_dict(variant)


@router.get("/api/lead-email-composer/variant-stats")
async def get_composer_variant_stats(days: int = Query(30, ge=1, le=365)):
    return await composer_variant_stats(days=days)


@router.get("/api/lead-email-composer/report")
async def get_composer_ab_report(days: int = 60):
    from app.services.lead_email_composer_variants import composer_ab_report

    return await composer_ab_report(days=days)
