"""Skill-variant discovery, assignment, and stats for lead email composition."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.db.models import LeadGenBatchItemRow, LeadGenObservationRow, ProductTraceRow


BASE_SKILL_DIR = Path(__file__).resolve().parents[1] / "skills/possible-minds-lead-email-composer"
BASE_SKILL_PATH = BASE_SKILL_DIR / "SKILL.md"
VARIANTS_DIR = BASE_SKILL_DIR / "variants"
EXPERIMENT_KEY = "lead-email-composer-skill-ab-v1"
MAX_SKILL_UPLOAD_BYTES = 200_000


@dataclass(frozen=True)
class ComposerSkillVariant:
    key: str
    label: str
    description: str
    skill_path: str
    skill_sha256: str | None
    allocation_weight: int = 100
    active: bool = True
    is_baseline: bool = False


def _file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return None


def _read_manifest(directory: Path) -> dict[str, Any]:
    path = directory / "variant.json"
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text())
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _slugify_variant_key(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:80].strip("-")


def discover_composer_skill_variants() -> list[ComposerSkillVariant]:
    variants: list[ComposerSkillVariant] = [
        ComposerSkillVariant(
            key="baseline",
            label="Baseline",
            description="Default Possible Minds lead email composer skill.",
            skill_path=str(BASE_SKILL_PATH),
            skill_sha256=_file_sha256(BASE_SKILL_PATH),
            allocation_weight=100,
            active=BASE_SKILL_PATH.exists(),
            is_baseline=True,
        )
    ]
    if VARIANTS_DIR.exists():
        for skill_file in sorted(VARIANTS_DIR.glob("*/SKILL.md")):
            directory = skill_file.parent
            manifest = _read_manifest(directory)
            key = str(manifest.get("key") or directory.name).strip()
            if not key or key == "baseline":
                continue
            active = bool(manifest.get("active", True))
            try:
                weight = int(manifest.get("allocation_weight", 100))
            except (TypeError, ValueError):
                weight = 100
            variants.append(ComposerSkillVariant(
                key=key,
                label=str(manifest.get("label") or key.replace("-", " ").replace("_", " ").title()),
                description=str(manifest.get("description") or ""),
                skill_path=str(skill_file),
                skill_sha256=_file_sha256(skill_file),
                allocation_weight=max(0, weight),
                active=active,
                is_baseline=False,
            ))
    return variants


def choose_composer_skill_variant(contact_id: str, *, experiment_key: str = EXPERIMENT_KEY) -> ComposerSkillVariant:
    active = [
        variant for variant in discover_composer_skill_variants()
        if variant.active and variant.allocation_weight > 0 and Path(variant.skill_path).exists()
    ]
    if not active:
        return ComposerSkillVariant(
            key="baseline",
            label="Baseline",
            description="Default Possible Minds lead email composer skill.",
            skill_path=str(BASE_SKILL_PATH),
            skill_sha256=_file_sha256(BASE_SKILL_PATH),
            active=BASE_SKILL_PATH.exists(),
            is_baseline=True,
        )
    # Rendezvous hashing keeps most assignments stable when variants are added.
    best: tuple[int, ComposerSkillVariant] | None = None
    for variant in active:
        digest = hashlib.sha256(f"{experiment_key}:{contact_id}:{variant.key}".encode("utf-8")).hexdigest()
        score = int(digest[:16], 16) * variant.allocation_weight
        if best is None or score > best[0]:
            best = (score, variant)
    return best[1] if best else active[0]


def get_composer_skill_variant(key: str) -> ComposerSkillVariant | None:
    normalized = str(key or "").strip()
    if not normalized:
        return None
    for variant in discover_composer_skill_variants():
        if (
            variant.key == normalized
            and variant.active
            and Path(variant.skill_path).exists()
        ):
            return variant
    return None


def update_composer_skill_variant_manifest(
    key: str,
    *,
    label: str,
    description: str | None = None,
) -> ComposerSkillVariant:
    normalized = str(key or "").strip()
    if not normalized or normalized == "baseline":
        raise ValueError("Only uploaded skill variants can be renamed.")
    variant = get_composer_skill_variant(normalized)
    if variant is None:
        raise ValueError(f"Unknown composer variant: {normalized}")
    directory = Path(variant.skill_path).parent
    manifest_path = directory / "variant.json"
    manifest = _read_manifest(directory)
    clean_label = str(label or "").strip()
    if not clean_label:
        raise ValueError("Variant name is required.")
    manifest["key"] = normalized
    manifest["label"] = clean_label[:120]
    if description is not None:
        manifest["description"] = str(description or "").strip()[:500]
    if "active" not in manifest:
        manifest["active"] = variant.active
    if "allocation_weight" not in manifest:
        manifest["allocation_weight"] = variant.allocation_weight
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    updated = get_composer_skill_variant(normalized)
    if updated is None:
        raise ValueError(f"Could not reload composer variant: {normalized}")
    return updated


def create_composer_skill_variant(
    *,
    label: str,
    skill_text: str,
    description: str | None = None,
    allocation_weight: int = 100,
    active: bool = True,
) -> ComposerSkillVariant:
    clean_label = str(label or "").strip()
    if not clean_label:
        raise ValueError("Variant name is required.")
    if not skill_text.strip():
        raise ValueError("SKILL.md is empty.")
    encoded = skill_text.encode("utf-8")
    if len(encoded) > MAX_SKILL_UPLOAD_BYTES:
        raise ValueError("SKILL.md is too large.")
    if "```" in skill_text[:500]:
        raise ValueError("Upload the raw SKILL.md file, not a fenced code block.")
    if "subject" not in skill_text.lower() or "body" not in skill_text.lower():
        raise ValueError("SKILL.md must describe the subject/body JSON output contract.")
    key = _slugify_variant_key(clean_label)
    if not key or key == "baseline":
        raise ValueError("Variant name must produce a non-baseline key.")
    VARIANTS_DIR.mkdir(parents=True, exist_ok=True)
    directory = VARIANTS_DIR / key
    if directory.exists():
        raise ValueError(f"Variant already exists: {key}")
    directory.mkdir(parents=False, exist_ok=False)
    skill_path = directory / "SKILL.md"
    manifest_path = directory / "variant.json"
    normalized_skill = skill_text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized_skill.endswith("\n"):
        normalized_skill += "\n"
    skill_path.write_text(normalized_skill)
    manifest = {
        "key": key,
        "label": clean_label[:120],
        "description": str(description or "").strip()[:500],
        "allocation_weight": max(0, int(allocation_weight)),
        "active": bool(active),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    variant = get_composer_skill_variant(key)
    if variant is None:
        raise ValueError(f"Could not load uploaded variant: {key}")
    return variant


def variant_to_dict(variant: ComposerSkillVariant) -> dict[str, Any]:
    return {
        "key": variant.key,
        "label": variant.label,
        "description": variant.description,
        "skill_path": variant.skill_path,
        "skill_sha256": variant.skill_sha256,
        "allocation_weight": variant.allocation_weight,
        "active": variant.active,
        "is_baseline": variant.is_baseline,
    }


def _window_start(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _empty_stats(variant: ComposerSkillVariant) -> dict[str, Any]:
    return {
        **variant_to_dict(variant),
        "compose_count": 0,
        "send_count": 0,
        "manual_edit_count": 0,
        "regenerate_count": 0,
        "bounce_count": 0,
        "reply_count": 0,
        "booked_qualified_conversation_count": 0,
        "first_seen_at": None,
        "last_seen_at": None,
    }


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


async def composer_variant_stats(*, days: int = 30) -> dict[str, Any]:
    days = max(1, min(days, 365))
    since = _window_start(days)
    variants = discover_composer_skill_variants()
    stats = {variant.key: _empty_stats(variant) for variant in variants}
    stats.setdefault("unknown", {
        **_empty_stats(ComposerSkillVariant(
            key="unknown",
            label="Unknown",
            description="Rows composed before variant metadata existed.",
            skill_path="",
            skill_sha256=None,
            active=False,
        )),
    })

    async with AsyncSessionLocal() as session:
        traces = (await session.execute(
            select(ProductTraceRow).where(
                ProductTraceRow.created_at >= since,
                ProductTraceRow.event_type.in_([
                    "email_composed",
                    "email_draft_edited",
                    "email_draft_regenerated",
                ]),
            )
        )).scalars().all()
        sent_items = (await session.execute(
            select(LeadGenBatchItemRow).where(
                LeadGenBatchItemRow.updated_at >= since,
            )
        )).scalars().all()
        observations = (await session.execute(
            select(LeadGenObservationRow).where(
                LeadGenObservationRow.created_at >= since,
            )
        )).scalars().all()

    item_variant: dict[str, str] = {}
    for item in sent_items:
        reason = item.reason_json or {}
        variant_key = str(reason.get("last_sent_composer_variant_key") or reason.get("composer_variant_key") or "").strip()
        if not variant_key:
            continue
        item_variant[item.id] = variant_key
        row = stats.setdefault(variant_key, _empty_stats(ComposerSkillVariant(
            key=variant_key,
            label=variant_key,
            description="Discovered from historical send metadata.",
            skill_path="",
            skill_sha256=None,
            active=False,
        )))
        if reason.get("last_sent_at") or reason.get("last_sent_message_id"):
            row["send_count"] += 1
        if item.outcome == "bounce":
            row["bounce_count"] += 1

    for trace in traces:
        context = trace.context_json or {}
        variant_key = str(context.get("composer_variant_key") or "unknown").strip() or "unknown"
        row = stats.setdefault(variant_key, _empty_stats(ComposerSkillVariant(
            key=variant_key,
            label=variant_key,
            description="Discovered from trace metadata.",
            skill_path=str(context.get("skill_path") or ""),
            skill_sha256=str(context.get("skill_sha256") or "") or None,
            active=False,
        )))
        if trace.event_type == "email_composed":
            row["compose_count"] += 1
        elif trace.event_type == "email_draft_edited":
            row["manual_edit_count"] += 1
        elif trace.event_type == "email_draft_regenerated":
            row["regenerate_count"] += 1
        created = trace.created_at.isoformat() if trace.created_at else None
        if created:
            row["first_seen_at"] = min(filter(None, [row["first_seen_at"], created]), default=created)
            row["last_seen_at"] = max(filter(None, [row["last_seen_at"], created]), default=created)

    for observation in observations:
        variant_key = item_variant.get(observation.batch_item_id or "")
        if not variant_key:
            continue
        row = stats.setdefault(variant_key, _empty_stats(ComposerSkillVariant(
            key=variant_key,
            label=variant_key,
            description="Discovered from observation linkage.",
            skill_path="",
            skill_sha256=None,
            active=False,
        )))
        outcome = observation.classified_outcome or ""
        if outcome in {"positive_reply", "reply", "referral", "needs_human_review"}:
            row["reply_count"] += 1
        if outcome == "booked_qualified_conversation":
            row["booked_qualified_conversation_count"] += 1

    rows = list(stats.values())
    for row in rows:
        row["manual_edit_rate"] = _rate(row["manual_edit_count"], row["compose_count"])
        row["send_rate"] = _rate(row["send_count"], row["compose_count"])
        row["reply_rate"] = _rate(row["reply_count"], row["send_count"])
        row["bounce_rate"] = _rate(row["bounce_count"], row["send_count"])
        row["booked_qualified_conversation_rate"] = _rate(
            row["booked_qualified_conversation_count"],
            row["send_count"],
        )
    rows.sort(key=lambda row: (not row.get("active"), -int(row.get("send_count") or 0), row["key"]))
    return {
        "experiment_key": EXPERIMENT_KEY,
        "days": days,
        "variants_dir": str(VARIANTS_DIR),
        "variants": rows,
    }
