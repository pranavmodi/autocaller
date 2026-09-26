import json,subprocess,datetime
from pathlib import Path
base=Path(__file__).parent
drafts=json.loads((base/'drafts.json').read_text())['drafts']
old={x['email']:x for x in json.loads((base/'scheduled.json').read_text())['recipients']}
def sql(q):return json.loads(subprocess.check_output(['sudo','-u','postgres','psql','-d','autocaller','-X','-q','-t','-A','-c',q],text=True))
def cli(args):
    r=subprocess.run(['./bin/possibleos',*args,'--json'],capture_output=True,text=True)
    if r.returncode:raise RuntimeError(r.stdout+r.stderr)
    return json.loads(r.stdout)
for d in drafts:
    prior=old[d['email']]
    live=sql("SELECT row_to_json(x) FROM (SELECT id,status,scheduled_for,started_at,completed_at,input_json FROM agent_actions WHERE id='"+prior['action_id']+"') x")
    assert live['status']=='approved' and not live['started_at'] and not live['completed_at'],(d['email'],'not safe to edit')
    assert datetime.datetime.fromisoformat(live['scheduled_for'])>datetime.datetime.now(datetime.timezone.utc)
    assert live['input_json']['body'] in (prior['body'],d['body']),(d['email'],'concurrent copy change')
    r=cli(['lead-gen','edit-draft',prior['item_id'],'--draft-file',str(base/f"draft_{d['rank']:02}.txt"),'--transport','resend','--in-reply-to',d['thread']['in_reply_to'],'--references',d['thread']['references'],'--action-type','follow_up','--at',d['scheduled_for'],'--actor','codex-consistency-review','--no-editor','--no-execute'])
    assert r['updated_existing'] and not r['created'] and r['action']['id']==prior['action_id'],r
    p=cli(['actions','policy-check',prior['action_id'],'--actor','codex-consistency-review'])
    assert p['policy']['allowed'],p
    print(json.dumps({'rank':d['rank'],'email':d['email'],'action_id':prior['action_id'],'updated_existing':r['updated_existing'],'scheduled_for':r['action']['scheduled_for'],'policy':p['policy'],'body_sha256':r['action']['input']['approval']['body_sha256']}),flush=True)
