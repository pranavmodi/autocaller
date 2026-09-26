WITH hist AS (
 SELECT lower(recipient_email) email,count(*) total,count(*) FILTER(WHERE status IN ('sent','delivered')) successes,max(sent_at) latest,
 bool_or(status NOT IN ('sent','delivered')) bad
 FROM email_logs GROUP BY lower(recipient_email)
), latest AS (SELECT DISTINCT ON(lower(recipient_email)) * FROM email_logs ORDER BY lower(recipient_email),sent_at DESC),
pool AS (
 SELECT DISTINCT ON(lower(c.email)) c.id contact_id,c.pif_id,c.full_name,c.first_name,c.email,c.title,c.research_title,c.source,c.persona,
 f.firm_name,f.website,f.entity_type,h.total,h.latest,
 l.id prior_log_id,l.subject prior_subject,l.body_excerpt prior_body,l.transport prior_transport,l.message_id prior_provider_id,
 (SELECT max(sent_at) FROM email_logs e WHERE (e.pif_id=c.pif_id OR split_part(lower(e.recipient_email),'@',2)=split_part(lower(c.email),'@',2)) AND e.status IN ('sent','delivered')) firm_latest,
 (SELECT count(*) FROM inbound_emails i WHERE lower(i.from_email)=lower(c.email) OR i.matched_pif_id=c.pif_id OR split_part(lower(i.from_email),'@',2)=split_part(lower(c.email),'@',2)) inbound_count,
 (SELECT count(*) FROM lead_gen_observations o WHERE (o.contact_id=c.id OR o.pif_id=c.pif_id) AND (event_type IN ('email_reply','email_bounce','unsubscribe','opt_out') OR classified_outcome IN ('replied','unsubscribed','not_interested','bounced','opted_out'))) negative_count,
 (SELECT count(*) FROM agent_actions a LEFT JOIN lead_gen_batch_items b ON b.id=a.input_json->>'batch_item_id' WHERE a.status IN ('proposed','waiting_for_approval','approved','queued','running') AND (b.pif_id=c.pif_id OR b.contact_id=c.id OR split_part(lower(b.contact_email),'@',2)=split_part(lower(c.email),'@',2) OR a.input_json::text ILIKE '%'||c.email||'%' OR a.input_json::text LIKE '%'||c.pif_id||'%')) pending_count
 FROM firm_contacts c JOIN hist h ON h.email=lower(c.email) JOIN latest l ON lower(l.recipient_email)=h.email JOIN pif_directory_firms f ON f.id=c.pif_id
 WHERE h.total BETWEEN 1 AND 2 AND NOT h.bad AND h.latest<now()-interval '7 days' AND h.latest>now()-interval '70 days'
 AND concat(c.title,' ',c.research_title) ~* '(founder|owner|partner|president|chief|\mCEO\M|\mCOO\M)'
 AND split_part(lower(c.email),'@',1) !~ '^(info|contact|support|office|admin|reception|intake|help|team|recruitment|careers)$'
 AND l.subject !~* '(application|resume|career|workshop registration)'
 ORDER BY lower(c.email),c.updated_at DESC
)
SELECT COALESCE(json_agg(x),'[]') FROM (SELECT * FROM pool WHERE inbound_count=0 AND negative_count=0 AND pending_count=0 AND firm_latest<now()-interval '7 days' ORDER BY latest DESC LIMIT 65) x;
