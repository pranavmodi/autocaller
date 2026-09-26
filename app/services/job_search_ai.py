"""Direct Responses transport for saved Job Agent searches only."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace
from typing import Literal

from openai import AsyncOpenAI, APIConnectionError, APIStatusError, APITimeoutError
from pydantic import BaseModel, create_model

from app.services.job_browser_ai import strict_schema


class SourceCheck(BaseModel):
    url: str
    status: Literal['searched', 'unavailable', 'not_checked']
    reason: str


def response_schema(value):
    """Keep URL validation in Pydantic: Responses doesn't support format=uri."""
    if isinstance(value, list):
        return [response_schema(v) for v in value]
    if not isinstance(value, dict):
        return value
    return {k: response_schema(v) for k, v in value.items()
            if not (k == 'format' and v == 'uri')}


def output_type(required, mode):
    # Import lazily: the career runner calls this transport, and owns these schemas.
    from app.services.daily_career_search import CandidateFields, Decision
    if required == 'config':
        from app.services.job_saved_searches import SearchSettings
        return create_model('SearchConfiguration', config=(SearchSettings, ...))
    if required == 'decisions':
        return create_model('SearchDecisions', decisions=(list[Decision], ...))
    if required != 'candidates':
        raise ValueError('Unsupported direct search output type')
    if mode == 'candidate_repair':
        candidate = create_model('RepairedCandidate', __base__=CandidateFields, candidate_id=(str, ...))
        return create_model('SearchRepairs', candidates=(list[candidate], ...))
    return create_model('SearchDiscovery', candidates=(list[CandidateFields], ...),
                        queries_used=(list[str], ...), source_checks=(list[SourceCheck], ...))


async def direct_search(*, payload, required, model, skill_path, timeout_s,
                        allow_tools, attempt_observer):
    """Web search for discovery; supplied evidence only for verification/repair.

    No provider fallback: a failed API call stays attributable to this run's
    selected provider. The runner owns retry budgets, deadlines and heartbeats.
    """
    try:
        key = os.getenv('OPENAI_API_KEY', '').strip()
        if not key:
            raise ValueError('OpenAI API requires OPENAI_API_KEY on the server. Set it or select OpenClaw gateway.')
        result_type = output_type(required, payload['mode'])
        await attempt_observer({'phase': 'started'})
        async with AsyncOpenAI(api_key=key, base_url='https://api.openai.com/v1',
                              timeout=timeout_s, max_retries=0) as client:
            response = await client.responses.create(
                model=model, instructions=skill_path.read_text(),
                input=json.dumps(payload, ensure_ascii=False, default=str),
                text={'format': {'type': 'json_schema', 'name': result_type.__name__,
                                 'strict': True, 'schema': response_schema(strict_schema(result_type.model_json_schema()))}},
                tools=[{'type': 'web_search'}] if allow_tools else [],
                tool_choice='required' if allow_tools else 'none',
                include=['web_search_call.action.sources'] if allow_tools else [],
                store=False, max_output_tokens=16000,
                prompt_cache_key='possibleos:job-search:responses:v1')
        if response.status != 'completed' or not response.output_text:
            raise ValueError('OpenAI returned an incomplete search response. No candidates were accepted from this response.')
        parsed = result_type.model_validate_json(response.output_text).model_dump(mode='json')
        usage = response.usage.model_dump() if response.usage else {}
        await attempt_observer({'phase': 'completed'})
        return SimpleNamespace(parsed=parsed, usage=usage, metadata={
            'provider': 'openai', 'model': response.model, 'response_id': response.id,
            'web_search_calls': [item.model_dump() for item in response.output if item.type == 'web_search_call']})
    except Exception as exc:
        if isinstance(exc, APITimeoutError):
            message = 'OpenAI API search request timed out.'
        elif isinstance(exc, APIConnectionError):
            message = 'Could not connect to OpenAI API. Check the server connection.'
        elif isinstance(exc, APIStatusError):
            guidance = {400: 'Check model support for web search and structured output.',
                        401: 'Check the server API key.', 403: 'Check API project access.',
                        404: 'Check the configured model.', 429: 'Check API quota and rate limits.'}
            message = f'OpenAI API returned HTTP {exc.status_code}. ' + guidance.get(exc.status_code, 'Retry later.')
        else:
            message = str(exc)
        await attempt_observer({'phase': 'failed', 'error': message})
        raise ValueError(message) from exc
