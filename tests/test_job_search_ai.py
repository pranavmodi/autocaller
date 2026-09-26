import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.services import job_search_ai as ai, daily_career_search as career
from app.services import job_saved_searches as saved
from tests.test_job_saved_searches import settings, Session

@pytest.mark.asyncio
@pytest.mark.parametrize('mode,required,tools', [('discovery','candidates',True),('verification','decisions',False),('candidate_repair','candidates',False)])
async def test_direct_transport_uses_responses_typed_output_and_only_discovery_browses(monkeypatch, mode, required, tools):
    monkeypatch.setenv('OPENAI_API_KEY','unit-test-only')
    payload={required:[]}
    if mode=='discovery': payload.update(queries_used=[],source_checks=[])
    response=SimpleNamespace(status='completed',output_text=json.dumps(payload),usage=None,model='test-model',id='r',output=[])
    client=AsyncMock();client.__aenter__.return_value=client;client.responses.create=AsyncMock(return_value=response)
    monkeypatch.setattr(ai,'AsyncOpenAI',lambda **kwargs:client)
    observer=AsyncMock()
    result=await ai.direct_search(payload={'mode':mode},required=required,model='test-model',skill_path=career.SKILL,
                                 timeout_s=5,allow_tools=tools,attempt_observer=observer)
    call=client.responses.create.call_args.kwargs
    assert call['model']=='test-model' and call['store'] is False
    assert call['tools']==([{'type':'web_search'}] if tools else [])
    assert call['tool_choice']==('required' if tools else 'none')
    assert call['text']['format']['strict'] is True
    assert result.parsed[required]==[]
    assert result.metadata['provider']=='openai'
    assert [c.args[0]['phase'] for c in observer.await_args_list]==['started','completed']

@pytest.mark.asyncio
async def test_missing_api_key_never_falls_back(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    observer=AsyncMock()
    with pytest.raises(ValueError,match='OPENAI_API_KEY'):
        await ai.direct_search(payload={'mode':'discovery'},required='candidates',model='test',skill_path=career.SKILL,
                               timeout_s=5,allow_tools=True,attempt_observer=observer)
    assert observer.call_args.args[0]['phase']=='failed'

@pytest.mark.asyncio
async def test_run_uses_snapshot_provider_for_research_and_verification(monkeypatch):
    direct=AsyncMock(return_value=SimpleNamespace(parsed={'candidates':[],'decisions':[]},usage={},metadata={'provider':'openai'}))
    gateway=AsyncMock(side_effect=AssertionError('unexpected gateway fallback'))
    monkeypatch.setattr(ai,'direct_search',direct)
    monkeypatch.setattr(career,'call_skill_json',gateway)
    monkeypatch.setattr(career,'checkpoint',AsyncMock())
    audit={'settings_snapshot':{'ai_provider':'openai','openai_model':'saved-model'},'llm_calls':0,'usage':[]}
    for mode,key in [('discovery','candidates'),('verification','decisions')]:
        await career.llm({'mode':mode},key,career.SearchConfig(),audit,'r')
    assert [c.kwargs['allow_tools'] for c in direct.await_args_list]==[True,False]
    assert all(c.kwargs['model']=='saved-model' for c in direct.await_args_list)
    assert len(audit['provider_responses'])==2
    gateway.assert_not_called()

@pytest.mark.asyncio
async def test_provider_snapshot_survives_later_settings_edits(monkeypatch):
    row=SimpleNamespace(id='s',revision=3,config=settings(ai_provider='openai',openai_model='saved-model').model_dump())
    session=Session(row)
    monkeypatch.setattr(saved,'ensure',AsyncMock())
    monkeypatch.setattr(saved,'AsyncSessionLocal',lambda:session)
    await saved.enqueue('s')
    row.config['ai_provider']='gateway'
    run=session.added[0]
    assert run.result['settings_snapshot']['ai_provider']=='openai'
    assert saved.summary(run)['model']=='saved-model'

@pytest.mark.asyncio
async def test_settings_assistant_keeps_selected_provider(monkeypatch):
    direct=AsyncMock(return_value=SimpleNamespace(parsed={'config':settings().model_dump()}))
    monkeypatch.setattr(ai,'direct_search',direct)
    result=await saved.draft(saved.ParseSearch(description='Legal AI jobs',ai_provider='openai',openai_model='custom'))
    assert result['config']['ai_provider']=='openai'
    assert result['config']['openai_model']=='custom'
    assert result['config']['schedule_enabled'] is False
    assert direct.call_args.kwargs['allow_tools'] is False

def test_api_schema_removes_unsupported_uri_format_but_validates_returned_urls():
    from app.services.job_browser_ai import strict_schema
    result_type=ai.output_type('candidates','discovery')
    schema=ai.response_schema(strict_schema(result_type.model_json_schema()))
    assert '"format": "uri"' not in json.dumps(schema)
    with pytest.raises(ValueError):
        result_type.model_validate({'candidates':[{'firm_name':'Firm','canonical_domain':'firm.com',
            'source_url':'not a URL','employer_evidence_url':'https://firm.com','title':'AI engineer','contact_urls':[]}],
            'queries_used':[],'source_checks':[]})


def test_repair_schema_preserves_candidate_identity():
    schema=ai.output_type('candidates','candidate_repair').model_json_schema()
    assert 'candidate_id' in schema['$defs']['RepairedCandidate']['required']
