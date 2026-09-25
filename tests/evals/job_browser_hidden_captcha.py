"""Synthetic live-model regression: CAPTCHA integrations alone must not stop forms."""
import asyncio
from dotenv import load_dotenv
load_dotenv()
from app.services.job_browser import model_decision
from app.services.job_browser_tools import BrowserAction

async def main():
    state={'posting':{'firm_name':'Example Health','title':'Engineer','source_url':'https://example.com/job'},
        'resume':{'text':'Alex Example. Email alex@example.com.'},'preferences':{},'answers':[],
        'ai_provider':'openai','openai_model':'gpt-5.6-luna','saved_profile':[],
        'error':'Earlier agent asserted hCaptcha prevents submission based on a hidden frame URL.',
        'snapshot':{'url':'https://example.com/apply','frames':[{'text':'Example Health application. Email required.',
        'controls':[{'id':'e0','tag':'input','type':'email','label':'Email','required':True,'value':''}]}]}}
    result,_=await model_decision('decide',state,action_schema=BrowserAction.model_json_schema())
    action=BrowserAction.model_validate(result['action'])
    assert action.kind=='fill' and action.element=='e0' and action.value=='alex@example.com',action.model_dump()
    audit,_=await model_decision('audit_action',state,proposed_action=action.model_dump())
    assert audit['allowed'] and audit['effect']=='input',audit
    print('PASS: visible form continues despite previous unsupported CAPTCHA assertion',flush=True)
if __name__=='__main__': asyncio.run(main())
