import json,subprocess,re,time,os,httpx
from dotenv import load_dotenv
from pathlib import Path
base=Path(__file__).parent
pool=json.loads((base/'replacement_candidates.json').read_text())
load_dotenv('/home/pranav/possibleos/.env')
key=os.getenv('RESEND_API_KEY','')
provider_enabled=False  # Configured key cannot retrieve messages; use stored ancestry only.
def sql(q):return json.loads(subprocess.check_output(['sudo','-u','postgres','psql','-d','autocaller','-X','-q','-t','-A','-c',q],text=True).strip() or '[]')
def norm(s):return re.sub(r'^(re:\s*)+','',s.strip(),flags=re.I).lower()
out=[]
for p in pool:
 e=p['email'].lower().replace("'","''")
 actions=sql(f"SELECT COALESCE(json_agg(x),'[]') FROM (SELECT a.id,a.input_json FROM agent_actions a JOIN lead_gen_batch_items b ON b.id=a.entity_id WHERE a.status='succeeded' AND lower(b.contact_email)='{e}' ORDER BY a.completed_at DESC) x")
 sources=[]
 for a in actions:
  inp=a['input_json'];h=inp.get('in_reply_to') or ''
  if norm(inp.get('subject',''))==norm(p['prior_subject']) and re.fullmatch(r'<[^<>\s]+@[^<>\s]+>',h):sources.append({'source':'succeeded_action_ancestry','action_id':a['id'],'subject':inp['subject'],'in_reply_to':h,'references':inp.get('references') or h})
 result={'email':p['email'],'sources':sources}
 if not sources and p['prior_transport']=='resend' and provider_enabled:
  r=httpx.get('https://api.resend.com/emails/'+p['prior_provider_id'],headers={'Authorization':'Bearer '+key},timeout=20);result['provider_status']=r.status_code
  if r.status_code in (401,403):provider_enabled=False
  if r.status_code==200:
   d=r.json();h=d.get('message_id','');tos=d.get('to',[])
   if p['email'].lower() in [v.lower() for v in tos] and norm(d.get('subject',''))==norm(p['prior_subject']) and re.fullmatch(r'<[^<>\s]+@[^<>\s]+>',h):sources.append({'source':'resend_provider','provider_id':p['prior_provider_id'],'subject':d['subject'],'in_reply_to':h,'references':h})
  time.sleep(.6)
 out.append(result)
print(json.dumps(out))
