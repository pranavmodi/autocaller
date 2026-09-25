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
async def main():
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
