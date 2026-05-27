"""Selectable email sequence registry."""
from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Optional

from app.services.sequences import precise_pain_4step, precise_records_audit
from app.services.sequences.common import Ctx, RenderedStep


DEFAULT_TEMPLATE_KEY = precise_pain_4step.TEMPLATE_KEY


@dataclass(frozen=True)
class SequenceTemplateInfo:
    template_key: str
    label: str
    description: str
    steps_total: int
    default_variant: str


_MODULES: dict[str, ModuleType] = {
    precise_pain_4step.TEMPLATE_KEY: precise_pain_4step,
    precise_records_audit.TEMPLATE_KEY: precise_records_audit,
}


def normalize_template_key(template_key: Optional[str]) -> str:
    key = (template_key or DEFAULT_TEMPLATE_KEY).strip()
    if key not in _MODULES:
        raise ValueError(f"unknown sequence template: {key}")
    return key


def get_template_module(template_key: Optional[str]) -> ModuleType:
    return _MODULES[normalize_template_key(template_key)]


def list_templates() -> list[SequenceTemplateInfo]:
    out: list[SequenceTemplateInfo] = []
    for key, module in _MODULES.items():
        variant = module.variant_for(pain_quote=None)
        out.append(SequenceTemplateInfo(
            template_key=key,
            label=getattr(module, "LABEL", key),
            description=getattr(module, "DESCRIPTION", ""),
            steps_total=module.steps_total(variant),
            default_variant=variant,
        ))
    return out


def variant_for(template_key: Optional[str], *, pain_quote: Optional[str]) -> str:
    module = get_template_module(template_key)
    return module.variant_for(pain_quote=pain_quote)


def steps_total(template_key: Optional[str], variant: str) -> int:
    return get_template_module(template_key).steps_total(variant)


def cadence_for(template_key: Optional[str], variant: str) -> list[int]:
    return get_template_module(template_key).cadence_for(variant)


def render_step(
    template_key: Optional[str],
    step_num: int,
    variant: str,
    ctx: Ctx,
) -> RenderedStep:
    return get_template_module(template_key).render_step(step_num, variant, ctx)
