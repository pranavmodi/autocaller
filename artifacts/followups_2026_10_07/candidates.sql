WITH h AS (
 SELECT lower(recipient_email) email,max(sent_at) last_sent,count(*) touches,
 count(*) FILTER(WHERE sent_at>now()-interval '30 days') touches30,
 bool_or(status IN ('bounced','complained')) bad
 FROM email_logs WHERE status IN ('sent','delivered','bounced','complained','sent_verified') GROUP BY 1
), pool AS (
 SELECT DISTINCT ON (lower(i.contact_email)) i.contact_id,i.pif_id,i.firm_name,i.contact_name,i.contact_title,
 lower(i.contact_email) email,a.id source_action,a.input_json
 FROM agent_actions a JOIN lead_gen_batch_items i ON i.id=a.input_json->>'batch_item_id'
 WHERE a.status='succeeded' AND coalesce(a.input_json->>'in_reply_to','')<>''
 ORDER BY lower(i.contact_email),a.completed_at DESC
)
SELECT row_to_json(q)::text FROM (
 SELECT p.*,h.last_sent,h.touches,h.touches30,
 (SELECT json_agg(json_build_object('id',e.id,'subject',e.subject,'body',e.body_excerpt,'sent_at',e.sent_at,'status',e.status,'provider_id',e.message_id)) FROM email_logs e WHERE lower(e.recipient_email)=p.email) history
 FROM pool p JOIN h USING(email)
 WHERE NOT h.bad AND h.last_sent<now()-interval '14 days' AND h.touches30<=2
 AND NOT EXISTS(SELECT 1 FROM inbound_emails x WHERE lower(x.from_email)=p.email)
 AND NOT EXISTS(SELECT 1 FROM agent_actions x WHERE x.status IN ('approved','waiting_for_approval','running')
 AND (lower(x.input_json->>'to')=p.email OR x.input_json->>'pif_id'=p.pif_id))
 ORDER BY h.touches,h.last_sent LIMIT 45
) q;
