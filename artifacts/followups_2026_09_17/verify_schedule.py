import json,subprocess,hashlib,datetime
from pathlib import Path
from zoneinfo import ZoneInfo
base=Path(__file__).parent
drafts=json.loads((base/'drafts.json').read_text())['drafts']
batch='57846e3f584040c2938dede98ab5e6f5'
def sql(q):return json.loads(subprocess.check_output(['sudo','-u','postgres','psql','-d','autocaller','-X','-q','-t','-A','-c',q],text=True))
rows=sql("SELECT json_agg(x) FROM (SELECT b.id AS item_id,b.contact_email,b.contact_id,b.pif_id,b.reason_json,a.id AS action_id,a.status,a.input_json,a.policy_result_json,a.scheduled_for,a.started_at,a.completed_at FROM lead_gen_batch_items b JOIN agent_actions a ON a.entity_id=b.id WHERE b.batch_id='"+batch+"' ORDER BY a.scheduled_for) x")
assert len(rows)==20
assert len({d['email'] for d in drafts})==len({d['pif_id'] for d in drafts})==len({d['email'].split('@')[1] for d in drafts})==20
out=[]
for d in drafts:
    matches=[r for r in rows if r['contact_email']==d['email']];assert len(matches)==1,(d['email'],'action count')
    r=matches[0];inp=r['input_json'];h=d['thread'];time=datetime.datetime.fromisoformat(r['scheduled_for']);expected=datetime.datetime.fromisoformat(d['scheduled_for'].replace('Z','+00:00'))
    checks={'approved':r['status']=='approved','policy_allowed':r['policy_result_json'].get('allowed') is True,'body_exact':inp['body']==d['body'],'subject_exact':inp['subject']==d['subject'],'body_hash':hashlib.sha256(d['body'].encode()).hexdigest()==inp['approval']['body_sha256'],'subject_hash':hashlib.sha256(d['subject'].encode()).hexdigest()==inp['approval']['subject_sha256'],'thread_exact':inp['in_reply_to']==h['in_reply_to'] and inp['references']==h['references'],'thread_approved':inp['approval']['in_reply_to']==h['in_reply_to'] and inp['approval']['references']==h['references'],'follow_up':inp['lead_gen_action_type']=='follow_up','resend':inp['transport']=='resend','time_exact':time==expected,'future':time>datetime.datetime.now(datetime.timezone.utc),'not_executed':r['started_at'] is None and r['completed_at'] is None,'real_newlines':'\n\n' in inp['body'] and '\\n' not in inp['body'],'no_placeholders':'{{' not in inp['body'],'one_question':inp['body'].count('?')==1}
    before=json.loads((base/'scheduled_before_consistency_review.json').read_text()) if (base/'scheduled_before_consistency_review.json').exists() else None
    if before:
        original=next(x for x in before['recipients'] if x['email']==d['email'])
        checks.update({'same_action_id':r['action_id']==original['action_id'],'no_reintroduction':"I'm Pranav" not in inp['body'],'stored_draft_matches':r['reason_json']['agent_draft']['body']==d['body'] and r['reason_json']['agent_draft']['subject']==d['subject'],'subject_preserved':d['subject']==original['subject'],'schedule_preserved':time==datetime.datetime.fromisoformat(original['scheduled_for_utc'])})
    assert all(checks.values()),(d['email'],checks)
    conflict=sql("SELECT count(*) FROM agent_actions a LEFT JOIN lead_gen_batch_items b ON b.id=a.input_json->>'batch_item_id' WHERE a.status IN ('proposed','waiting_for_approval','approved','queued','running') AND a.id<>'"+r['action_id']+"' AND (b.pif_id='"+d['pif_id']+"' OR split_part(lower(b.contact_email),'@',2)='"+d['email'].split('@')[1]+"' OR lower(a.input_json->>'to')='"+d['email']+"')")
    assert conflict==0,(d['email'],'duplicate')
    out.append({**d,'state':'approved_and_scheduled','batch_id':batch,'item_id':r['item_id'],'action_id':r['action_id'],'scheduled_for_utc':time.isoformat(),'scheduled_for_pdt':time.astimezone(ZoneInfo('America/Los_Angeles')).isoformat(),'scheduled_for_ist':time.astimezone(ZoneInfo('Asia/Kolkata')).isoformat(),'validation':checks,'duplicate_actions':conflict,'policy':r['policy_result_json']})
today=sql("SELECT COALESCE(json_agg(x),'[]') FROM (SELECT transport,status,count(*) FROM email_logs WHERE sent_at>='2026-09-17T07:00:00Z' AND sent_at<'2026-09-18T07:00:00Z' GROUP BY transport,status) x")
print(json.dumps({'verified_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'batch_id':batch,'campaign_id':None,'tracking':'No links included; contextual follow-ups rather than content campaign','scheduled':len(out),'sent':0,'held':0,'policy_allowed':len(out),'transport':'resend','today_email_log_counts':today,'recipients':out}))
