import json,subprocess,sys
from pathlib import Path
base=Path(__file__).parent
drafts=json.loads((base/'drafts.json').read_text())['drafts']
def sql(q):
    return json.loads(subprocess.check_output(['sudo','-u','postgres','psql','-d','autocaller','-X','-q','-t','-A','-c',q],text=True))
def cli(args):
    p=subprocess.run(['./bin/possibleos',*args,'--json'],capture_output=True,text=True)
    if p.returncode: raise RuntimeError(p.stdout+p.stderr)
    return json.loads(p.stdout)
items=sql("SELECT json_agg(x) FROM (SELECT id,contact_email FROM lead_gen_batch_items WHERE batch_id='57846e3f584040c2938dede98ab5e6f5') x")
for d in drafts:
    if not int(sys.argv[1])<=d['rank']<=int(sys.argv[2]):continue
    eligible=sql((base/'final_eligibility.sql').read_text())
    assert any(x['email']==d['email'] for x in eligible),('no longer eligible',d['email'])
    item=next(x['id'] for x in items if x['contact_email']==d['email'])
    r=cli(['lead-gen','edit-draft',item,'--draft-file',str(base/f"draft_{d['rank']:02}.txt"),'--transport','resend','--in-reply-to',d['thread']['in_reply_to'],'--references',d['thread']['references'],'--action-type','follow_up','--at',d['scheduled_for'],'--actor','codex','--no-editor','--no-execute'])
    p=cli(['actions','policy-check',r['action']['id'],'--actor','codex'])
    r['policy']=p['policy'];r['rank']=d['rank'];r['email']=d['email']
    print(json.dumps(r),flush=True)
    assert r['policy']['allowed'],('policy held',d['email'])
