import json,subprocess,os,re,time,requests,runpy
from pathlib import Path
from dotenv import load_dotenv
base=Path(__file__).parent
ds=json.loads((base/'drafts.json').read_text())['drafts']
mail=json.loads((base/'mailbox_audit.json').read_text())['matches']
load_dotenv('/home/pranav/possibleos/.env')
audit_key=runpy.run_path('/home/pranav/possibleos/artifacts/schedule_governance_followups_2026_09_08.py')['_read_resend_audit_key']()
def sql(q):return json.loads(subprocess.check_output(['sudo','-u','postgres','psql','-d','autocaller','-X','-q','-t','-A','-c',q],text=True).strip() or '[]')
def quote(x):return "'"+x.replace("'","''")+"'"
def norm(x):return re.sub(r'^(re:\s*)+','',x.strip(),flags=re.I).lower()
out=[]
for d in ds:
    e=quote(d['email']);cid=quote(d['contact_id'])
    actions=sql(f"SELECT COALESCE(json_agg(x),'[]') FROM (SELECT a.id,a.status,a.input_json,a.execution_result_json FROM agent_actions a LEFT JOIN lead_gen_batch_items b ON b.id=a.input_json->>'batch_item_id' WHERE a.status='succeeded' AND (lower(b.contact_email)=lower({e}) OR b.contact_id={cid} OR a.input_json::text ILIKE '%'||{e}||'%') ORDER BY a.completed_at DESC) x")
    row={'email':d['email'],'subject':d['subject'],'sources':[]}
    for m in mail.get(d['email'],[]):
        if m['folder'].strip('"')=='Sent' and norm(m['subject'])==norm(d['subject']) and re.fullmatch(r'<[^<>\s]+@[^<>\s]+>',m['message_id']):
            row['sources'].append({'source':'zoho_sent','uid':m['uid'],'subject':m['subject'],'in_reply_to':m['message_id'],'references':(m['references']+' '+m['message_id']).strip()})
    for a in actions:
        inp=a['input_json'];sub=inp.get('subject') or '';hdr=inp.get('in_reply_to') or ''
        if norm(sub)==norm(d['subject']) and re.fullmatch(r'<[^<>\s]+@[^<>\s]+>',hdr):
            row['sources'].append({'source':'successful_action_ancestry','action_id':a['id'],'subject':sub,'in_reply_to':hdr,'references':inp.get('references') or hdr})
    if not row['sources'] and d['prior_transport']=='resend':
        r=requests.get('https://api.resend.com/emails/'+d['prior_provider_id'],headers={'Authorization':'Bearer '+audit_key},timeout=20)
        row['provider_status']=r.status_code
        if r.status_code==200:
            p=r.json();tos=p.get('to',[]);hdr=p.get('message_id') or ''
            if d['email'].lower() in [x.lower() for x in tos] and norm(p.get('subject',''))==norm(d['subject']) and re.fullmatch(r'<[^<>\s]+@[^<>\s]+>',hdr):
                row['sources'].append({'source':'resend_api','provider_id':d['prior_provider_id'],'subject':p['subject'],'in_reply_to':hdr,'references':hdr})
        time.sleep(.6)
    row['action_candidates']=[{'id':a['id'],'keys':list(a['input_json'].keys())} for a in actions] if not row['sources'] else []
    out.append(row)
print(json.dumps(out))
