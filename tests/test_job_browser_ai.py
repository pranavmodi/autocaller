import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.services import job_agent as core, job_browser as browser, job_browser_ai as ai


def test_provider_config_validates_without_secret_fields():
    assert core.JobAgentConfig().browser_ai_provider == 'gateway'
    for value in ['other', '']:
        with pytest.raises(ValidationError):
            core.JobAgentConfig(browser_ai_provider=value)
    with pytest.raises(ValidationError):
        core.JobAgentConfig(browser_openai_model=' ')
    assert 'OPENAI_API_KEY' not in core.JobAgentConfig().model_dump()


def test_missing_api_key_blocks_only_direct_provider(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    assert browser.provider_settings(core.JobAgentConfig())['ai_provider'] == 'gateway'
    with pytest.raises(ValueError, match='OPENAI_API_KEY'):
        browser.provider_settings(core.JobAgentConfig(), 'openai')


def test_structured_schema_requires_all_fields_and_no_defaults():
    schema = ai.strict_schema(ai.Decision.model_json_schema())
    def check(value):
        if isinstance(value, dict):
            assert 'default' not in value
            if value.get('type') == 'object':
                assert value['additionalProperties'] is False
                assert set(value['required']) == set(value['properties'])
            for child in value.values(): check(child)
        elif isinstance(value, list):
            for child in value: check(child)
    check(schema)


@pytest.mark.asyncio
async def test_model_dispatch_preserves_gateway_default_and_uses_direct_api(monkeypatch):
    gateway = AsyncMock(return_value=SimpleNamespace(parsed={'action': {}}, model='openclaw/main', usage={}))
    direct = AsyncMock(return_value=({'allowed': True}, {'provider':'openai'}))
    monkeypatch.setattr(browser,'call_skill_json',gateway)
    monkeypatch.setattr(ai,'direct_decision',direct)
    state={'posting':{},'resume':{'text':'Fixture'},'preferences':{}}
    _, meta=await browser.model_decision('decide',state)
    assert meta['provider']=='gateway'
    state.update(ai_provider='openai',openai_model='test-model')
    await browser.model_decision('audit_action',state)
    assert direct.await_args.kwargs['model']=='test-model'
    assert gateway.await_count==1
    direct.side_effect=ValueError('API unavailable')
    with pytest.raises(ValueError,match='API unavailable'):
        await browser.model_decision('audit_action',state)
    assert gateway.await_count==1  # No implicit fallback.


@pytest.mark.asyncio
@pytest.mark.parametrize('status,output,success',[
    ('completed',json.dumps({'allowed':True,'effect':'input','reason':'Resume fact'}),True),
    ('incomplete','',False),
    ('completed','',False),
    ('completed','not json',False),
    ('completed',json.dumps({'allowed':'true','effect':'input','reason':'Fact'}),False),
])
async def test_direct_response_is_validated_before_execution(monkeypatch,status,output,success):
    monkeypatch.setenv('OPENAI_API_KEY','test-placeholder')
    create=AsyncMock(return_value=SimpleNamespace(status=status,output_text=output,
        model='test-model',id='fixture-response',usage=None))
    received={}
    class FakeClient:
        def __init__(self,**kwargs):
            received.update(kwargs)
            self.responses=SimpleNamespace(create=create)
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
    monkeypatch.setattr(ai,'AsyncOpenAI',FakeClient)
    if success:
        parsed,meta=await ai.direct_decision('audit_action',{},model='test-model',instructions='Fixture')
        assert parsed['allowed'] is True and meta['provider']=='openai'
        assert 'test-placeholder' not in json.dumps(meta)
    else:
        with pytest.raises(ValueError):
            await ai.direct_decision('audit_action',{},model='test-model',instructions='Fixture')
    assert received['base_url']=='https://api.openai.com/v1'
    assert received['max_retries']==0
    assert create.await_args.kwargs['store'] is False
    assert create.await_args.kwargs['tools']==[]


@pytest.mark.asyncio
async def test_profile_edits_invalidate_derived_answers(monkeypatch):
    capture={}
    async def direct(mode,payload,**kwargs):
        capture.update(payload)
        return {},{}
    monkeypatch.setattr(ai,'direct_decision',direct)
    state={'posting':{},'resume':{'text':'Applicant'},'preferences':{},'ai_provider':'openai',
        'saved_profile':[{'id':'changed','revision':2},{'id':'current','revision':1}],
        'answers':[{'answer':'old address','source':'profile','citations':[{'id':'changed','revision':1}]},
                   {'answer':'deleted fact','source':'profile','citations':[{'id':'deleted','revision':1}]},
                   {'answer':'current fact','source':'profile','citations':[{'id':'current','revision':1}]},
                   {'answer':'operator reply'}]}
    await browser.model_decision('decide',state)
    assert [item['answer'] for item in capture['operator_answers']]==['current fact','operator reply']
    assert 'answer_policy' in capture
