"""Direct OpenAI Responses transport for the browser controller's typed decisions."""
from __future__ import annotations

import json
import os
from typing import Literal

from openai import AsyncOpenAI, APIConnectionError, APIStatusError, APITimeoutError
from pydantic import BaseModel, ConfigDict, Field

from app.services.job_browser_tools import BrowserAction


class Decision(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    action: BrowserAction


class ActionAudit(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    allowed: bool
    effect: Literal['input', 'navigation', 'advance', 'submit', 'blocked']
    reason: str
    recovery: Literal['none', 'correct_form', 'stop'] = 'stop'
    repair_hint: str = ''


class Confirmation(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    confirmed: bool
    reason: str


class ProfileCitation(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str
    quote: str


class ProfileResolution(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    answer: str
    missing_question: str
    citations: list[ProfileCitation]
    reason: str


class QuitReasons(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    reasons: list[str] = Field(max_length=4)


FORMATS = {'decide': Decision, 'audit_action': ActionAudit, 'verify_confirmation': Confirmation,
           'resolve_question': ProfileResolution, 'suggest_quit_reasons': QuitReasons}


def strict_schema(value):
    """Responses strict mode requires all object properties, without defaults."""
    if isinstance(value, list):
        return [strict_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: strict_schema(item) for key, item in value.items() if key != 'default'}
    if result.get('type') == 'object':
        result['required'] = list(result.get('properties', {}))
        result['additionalProperties'] = False
    return result


async def direct_decision(mode, payload, *, model, instructions):
    key = os.getenv('OPENAI_API_KEY', '').strip()
    if not key:
        raise ValueError('Direct OpenAI API requires OPENAI_API_KEY on the server.')
    output_type = FORMATS[mode]
    try:
        async with AsyncOpenAI(api_key=key, base_url='https://api.openai.com/v1',
                              timeout=90, max_retries=0) as client:
            response = await client.responses.create(
                model=model, instructions=instructions,
                input=json.dumps(payload, ensure_ascii=False),
                text={'format': {'type': 'json_schema', 'name': output_type.__name__,
                                 'strict': True, 'schema': strict_schema(output_type.model_json_schema())}},
                tools=[], store=False, max_output_tokens=4000)
    except APITimeoutError as exc:
        raise ValueError('OpenAI API timed out. Review the saved browser state before resuming.') from exc
    except APIConnectionError as exc:
        raise ValueError('Could not connect to OpenAI API. Check the server connection and resume.') from exc
    except APIStatusError as exc:
        guidance = {401: 'Check the server API key.', 403: 'Check API project and model access.',
                    404: 'Check the configured OpenAI model.', 429: 'Check API quota and rate limits.'}
        raise ValueError(f'OpenAI API returned HTTP {exc.status_code}. ' +
                         guidance.get(exc.status_code, 'Check the model settings or retry later.')) from exc
    if response.status != 'completed' or not response.output_text:
        raise ValueError('OpenAI did not return a complete structured decision. The browser action was not executed.')
    try:
        parsed = output_type.model_validate_json(response.output_text)
    except ValueError as exc:
        raise ValueError('OpenAI returned an invalid browser decision. No action was executed.') from exc
    return parsed.model_dump(), {'provider': 'openai', 'model': response.model,
        'response_id': response.id, 'usage': response.usage.model_dump() if response.usage else None}
