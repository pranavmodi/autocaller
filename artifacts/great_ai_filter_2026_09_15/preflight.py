import json, subprocess, datetime
from pathlib import Path

BASE=Path('/home/pranav/possibleos/artifacts')
pool=json.loads((BASE/'blog_followups_2026_09_11/candidates.json').read_text())['candidates']
def sql(q):
    return json.loads(subprocess.check_output(['sudo','-u','postgres','psql','-d','autocaller','-X','-q','-t','-A','-c',q],text=True).strip() or '[]')
def quote(x): return "'"+str(x).replace("'","''")+"'"
out=[]
for p in pool:
    e=quote(p['email'].lower()); d=quote(p['email'].split('@')[-1].lower()); cid=quote(p['contact_id']); fid=quote(p['canonical_firm_id'])
    q=f'''SELECT json_build_object(
      'contact',(SELECT row_to_json(c) FROM firm_contacts c WHERE id={cid}),
      'history',COALESCE((SELECT json_agg(x ORDER BY sent_at DESC) FROM (SELECT id,recipient_email,subject,body_excerpt,status,sent_at,transport,message_id FROM email_logs WHERE lower(recipient_email)={e}) x),'[]'),
      'firm_latest',(SELECT max(sent_at) FROM email_logs WHERE (pif_id={fid} OR split_part(lower(recipient_email),'@',2)={d}) AND status IN ('sent','delivered')),
      'inbound',(SELECT count(*) FROM inbound_emails WHERE lower(from_email)={e} OR matched_pif_id={fid} OR split_part(lower(from_email),'@',2)={d}),
      'negative',(SELECT count(*) FROM lead_gen_observations WHERE (contact_id={cid} OR pif_id={fid}) AND (event_type IN ('email_reply','email_bounce','unsubscribe','opt_out') OR classified_outcome IN ('replied','unsubscribed','not_interested','bounced','opted_out'))),
      'pending',(SELECT count(*) FROM agent_actions a LEFT JOIN lead_gen_batch_items b ON b.id=a.input_json->>'batch_item_id' WHERE a.status IN ('proposed','waiting_for_approval','approved','queued','running') AND (b.pif_id={fid} OR b.contact_id={cid} OR split_part(lower(b.contact_email),'@',2)={d} OR a.input_json::text ILIKE '%'||{d}||'%' OR a.input_json::text LIKE '%'||{fid}||'%' OR a.input_json::text LIKE '%'||{cid}||'%'))
    );'''
    evidence=sql(q); reasons=[]
    good=[x for x in evidence['history'] if x['status'] in ['sent','delivered']]
    if not 1<=len(good)<=2: reasons.append('touch_count_not_1_or_2')
    if any(x['status'] not in ['sent','delivered'] for x in evidence['history']): reasons.append('non_success_email_status')
    for k in ['inbound','negative','pending']:
        if evidence[k]: reasons.append(k)
    if evidence['firm_latest'] and datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(evidence['firm_latest'])<datetime.timedelta(days=7): reasons.append('firm_contact_within_7_days')
    for h in evidence['history'][1:]: h.pop('body_excerpt',None)
    for k in ['latest_context','vendor_stack','practice_areas','prior_subjects','eligibility_basis']: p.pop(k,None)
    p['fresh_evidence']=evidence;p['hold_reasons']=reasons
    if reasons: p={k:p[k] for k in ['name','email','hold_reasons']}
    out.append(p)
print(json.dumps({'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'candidates':out}))
