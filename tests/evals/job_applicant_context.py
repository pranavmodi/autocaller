"""Live model evaluation of contextual answer reuse; no browser side effects."""
import asyncio
import copy
from dotenv import load_dotenv
load_dotenv()
from app.services.job_browser import model_decision, resolve_saved_question
from app.services.job_browser_tools import BrowserAction

PROFILE=[
 {'id':'current','revision':1,'question':'Current residence','answer':'Bengaluru, India','scope':'global','scope_value':'','context':{}},
 {'id':'future','revision':1,'question':'Planned relocation and preferred work location','answer':'Moving shortly to Medellín, Colombia. Preferred future remote work location is Colombia. No move date is confirmed.','scope':'global','scope_value':'','context':{}},
 {'id':'auth','revision':1,'question':'Are you authorized to work in the United States?','answer':'No','scope':'country','scope_value':'United States','context':{}},
 {'id':'address','revision':1,'question':'Home address and other details','answer':'Home address: Example Street, Bengaluru, Karnataka, India. Preferred contact is email.','scope':'contextual','scope_value':'','context':{'firm_name':'Old Employer','title':'AI Engineer'}},
 {'id':'pay','revision':1,'question':'Desired compensation for a US senior AI engineering role','answer':'USD 180,000 annually','scope':'role','scope_value':'US senior AI engineering roles','context':{}},
]
BASE={'posting':{'firm_name':'Example Legal','title':'Entry-level intake specialist','location':'Colombia'},
 'resume':{'text':'Alex Example, software engineer and founder, Bengaluru, India.'},'preferences':{},
 'ai_provider':'openai','openai_model':'gpt-5-mini','saved_profile':PROFILE,'answers':[],
 'snapshot':{'url':'https://example.com/apply','frames':[]}}
async def location(label,expected):
 state=copy.deepcopy(BASE)
 state['snapshot']['frames']=[{'text':'Example Legal application. '+label,
  'controls':[{'id':'e1','tag':'select','label':label,'required':True,'value':'',
    'options':[{'value':'india','label':'India'},{'value':'colombia','label':'Colombia'}]}]}]
 result,_=await model_decision('decide',state,action_schema=BrowserAction.model_json_schema())
 action=BrowserAction.model_validate(result['action'])
 assert action.kind=='select' and action.value==expected,action.model_dump()
 print(label,action.value,flush=True)

async def explicit_sponsorship():
 state=copy.deepcopy(BASE)
 state['posting'].update(firm_name='Example Health',title='Senior AI Engineer',location='United States')
 state['saved_profile'].append({'id':'sponsorship','revision':1,
  'question':'Will Example Health need to sponsor your US employment authorization?',
  'answer':'No. Select No for sponsorship. I am still not currently authorized to work in the US.',
  'scope':'company','scope_value':'Example Health','context':{}})
 state['error']='Earlier agent wrongly blocked: no US authorization implies sponsorship must be Yes.'
 state['snapshot']['frames']=[{'text':'Example Health application. US SPONSORSHIP: Will you now or in the future require employer sponsorship? Required.',
  'controls':[{'id':'sponsor_yes','tag':'input','type':'radio','label':'Yes','value':'Yes','checked':False,'required':True},
              {'id':'sponsor_no','tag':'input','type':'radio','label':'No','value':'No','checked':False,'required':True}]}]
 result,_=await model_decision('decide',state,action_schema=BrowserAction.model_json_schema())
 action=BrowserAction.model_validate(result['action'])
 assert action.kind in {'check','click'} and action.element=='sponsor_no',action.model_dump()
 result,_=await model_decision('audit_action',state,proposed_action=action.model_dump())
 assert result['allowed'] is True,result
 print('Explicit sponsorship No decision and audit passed:',result,flush=True)
 state['snapshot']['frames']=[{'text':'Are you currently authorized to work in the United States? Required.',
  'controls':[{'id':'auth_yes','tag':'input','type':'radio','label':'Yes','value':'Yes','checked':False,'required':True},
              {'id':'auth_no','tag':'input','type':'radio','label':'No','value':'No','checked':False,'required':True}]}]
 for element,expected in [('auth_no',True),('auth_yes',False)]:
  action=BrowserAction(kind='check',element=element,checked=True,
   summary='Answer current US work authorization.',evidence='Applicant explicitly says current US work authorization is No.')
  result,_=await model_decision('audit_action',state,proposed_action=action.model_dump())
  assert result['allowed'] is expected,result
  print('Authorization audit:',element,result,flush=True)

async def main():
 await explicit_sponsorship()
 await location('Current country of residence','india')
 await location('Preferred country for future remote work','colombia')
 state=copy.deepcopy(BASE)
 resolution,_=await resolve_saved_question(state,'What is your home address and desired compensation for this Colombia intake role?')
 print('Partial resolution:',resolution.model_dump(),flush=True)
 assert resolution.answer and resolution.missing_question
 assert any(c.id=='address' for c in resolution.citations)
 # A citation may explain why a source was excluded; it must not become the answer.
 assert '180,000' not in resolution.answer and '180000' not in resolution.answer
 print('Partial question reused:',resolution.answer,'Missing:',resolution.missing_question,flush=True)
 resolution,_=await resolve_saved_question(state,'Will you require this employer to sponsor or otherwise support your US work authorization?')
 # The resolver can restate known authorization while asking about sponsorship.
 # Inspect the printed answer: it must not invent an employer-sponsorship need.
 print('Sponsorship resolution:',resolution.model_dump(),flush=True)
 assert resolution.missing_question
 assert all(c.id=='auth' for c in resolution.citations)
 print('Sponsorship kept separate from authorization:',resolution.missing_question,flush=True)
if __name__=='__main__': asyncio.run(main())
