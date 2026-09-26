import json,subprocess,hashlib,datetime
from pathlib import Path
from zoneinfo import ZoneInfo
base=Path(__file__).parent
drafts=json.loads((base/'drafts.json').read_text())['drafts']
threads={x['email']:x['sources'][0] for x in json.loads((base/'thread_sources_final.json').read_text())}
q="""SELECT json_agg(x) FROM (SELECT b.id AS item_id,b.contact_email,b.contact_id,b.pif_id,b.reason_json,a.id AS action_id,a.status,a.input_json,a.policy_result_json,a.scheduled_for,a.started_at,a.completed_at FROM lead_gen_batch_items b JOIN agent_actions a ON a.entity_id=b.id WHERE b.batch_id='ea467e41220147d287e948a605569c09' ORDER BY a.scheduled_for) x;"""
def sql(q):return json.loads(subprocess.check_output(['sudo','-u','postgres','psql','-d','autocaller','-X','-q','-t','-A','-c',q],text=True))
rows=sql(q);out=[]
for d in drafts:
    matches=[r for r in rows if r['contact_email']==d['email']];assert len(matches)==1,(d['email'],'action count')
    r=matches[0];inp=r['input_json'];h=threads[d['email']];time=datetime.datetime.fromisoformat(r['scheduled_for']);expected=datetime.datetime(2026,9,15,8,30,tzinfo=ZoneInfo('America/Los_Angeles'))+datetime.timedelta(minutes=10*(d['rank']-1))
    checks={'approved':r['status']=='approved','policy_allowed':r['policy_result_json'].get('allowed') is True,'body_exact':inp['body']==d['body'],'subject_exact':inp['subject']==d['subject'],'body_hash':hashlib.sha256(d['body'].encode()).hexdigest()==inp['approval']['body_sha256'],'subject_hash':hashlib.sha256(d['subject'].encode()).hexdigest()==inp['approval']['subject_sha256'],'thread_exact':inp['in_reply_to']==h['in_reply_to'] and inp['references']==h['references'],'thread_approved':inp['approval']['in_reply_to']==h['in_reply_to'] and inp['approval']['references']==h['references'],'follow_up':inp['lead_gen_action_type']=='follow_up','resend':inp['transport']=='resend','time_exact':time==expected,'future':time>datetime.datetime.now(datetime.timezone.utc),'not_executed':r['started_at'] is None and r['completed_at'] is None}
    assert all(checks.values()),(d['email'],checks)
    conflict=sql("SELECT count(*) FROM agent_actions a LEFT JOIN lead_gen_batch_items b ON b.id=a.input_json->>'batch_item_id' WHERE a.status IN ('proposed','waiting_for_approval','approved','queued','running') AND a.id<>"+"'"+r['action_id']+"' AND (b.pif_id='"+d['pif_id']+"' OR split_part(lower(b.contact_email),'@',2)='"+d['email'].split('@')[1]+"')")
    assert conflict==0,(d['email'],'duplicate')
    out.append({**d,'state':'approved_and_scheduled','approved':True,'batch_id':'ea467e41220147d287e948a605569c09','item_id':r['item_id'],'action_id':r['action_id'],'scheduled_for_utc':time.isoformat(),'scheduled_for_pdt':time.astimezone(ZoneInfo('America/Los_Angeles')).isoformat(),'scheduled_for_ist':time.astimezone(ZoneInfo('Asia/Kolkata')).isoformat(),'thread_source':h,'validation':checks,'duplicate_actions':conflict,'policy':r['policy_result_json']})
print(json.dumps({'verified_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'batch_id':'ea467e41220147d287e948a605569c09','campaign_id':'cmp_kKDzFyfMFvszsMWP','scheduled':len(out),'sent':0,'held':0,'policy_allowed':len(out),'transport':'resend','recipients':out}))
