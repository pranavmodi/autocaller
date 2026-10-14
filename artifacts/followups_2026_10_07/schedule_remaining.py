import json,subprocess,sys
from pathlib import Path
base=Path(__file__).parent
plans=json.loads((base/'draft_plan.json').read_text())
items={x['email']:x['id'] for x in json.loads((base/'items.json').read_text())}
def cli(args):
 r=subprocess.run(['./bin/possibleos']+args+['--json'],capture_output=True,text=True,timeout=150)
 if r.returncode: raise RuntimeError(r.stdout+r.stderr)
 return json.loads(r.stdout)
for index,p in enumerate(plans[1:],2):
 r=cli(['lead-gen','edit-draft',items[p['email']],'--draft-file',str(base/f'draft_{index:02}.txt'),'--at',p['scheduled_for'],'--transport','resend','--in-reply-to',p['in_reply_to'],'--references',p['references'],'--action-type','follow_up','--actor','codex','--no-editor','--no-execute'])
 a=r['action']; print(json.dumps({'event':'scheduled','email':p['email'],'action':a['id'],'status':a['status'],'at':a['scheduled_for']}),flush=True)
 policy=cli(['actions','policy-check',a['id'],'--actor','codex'])['policy']
 print(json.dumps({'event':'policy','email':p['email'],'action':a['id'],'policy':policy}),flush=True)
 if not policy['allowed']: sys.exit(2)
