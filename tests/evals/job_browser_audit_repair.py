"""Synthetic model test for recoverable form-validation audit feedback."""
import asyncio
from dotenv import load_dotenv
load_dotenv()
from app.services.job_browser import model_decision
from app.services.job_browser_tools import BrowserAction
async def main():
 state={'posting':{'firm_name':'Example Health','title':'Engineer'},
  'resume':{'text':'Alex Example is a software engineer who builds workflow automation.'},
  'preferences':{},'answers':[],'saved_profile':[],'ai_provider':'openai','openai_model':'gpt-5.6-luna',
  'snapshot':{'url':'https://example.com/apply','frames':[{'text':'Example Health Engineer application. About you is required.',
   'controls':[{'id':'e1','tag':'textarea','label':'About you','required':True,'value':'','validation':'Please fill out this field.'},
               {'id':'e2','tag':'button','type':'submit','label':'Submit application'}]}]}}
 proposal=BrowserAction(kind='submit',element='e2',summary='Submit application')
 audit,_=await model_decision('audit_action',state,proposed_action=proposal.model_dump())
 assert not audit['allowed'] and audit['recovery']=='correct_form' and audit['repair_hint'],audit
 state['audit_feedback']={'reason':audit['reason'],'repair_hint':audit['repair_hint'],'rejected_action':proposal.model_dump()}
 decision,_=await model_decision('decide',state,action_schema=BrowserAction.model_json_schema())
 action=BrowserAction.model_validate(decision['action'])
 assert action.kind=='fill' and action.element=='e1' and action.value,action.model_dump()
 print('PASS: audit requests correction, then controller fills the missing field:',action.value,flush=True)
if __name__=='__main__':asyncio.run(main())
