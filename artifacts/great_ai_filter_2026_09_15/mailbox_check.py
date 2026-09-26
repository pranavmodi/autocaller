import os,json,imaplib,re,datetime
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses,parsedate_to_datetime
from dotenv import load_dotenv
from pathlib import Path
base=Path(__file__).parent
pool=[p for p in json.loads((base/'db_preflight.json').read_text())['candidates'] if not p['hold_reasons']]
load_dotenv('/home/pranav/possibleos/.env')
c=imaplib.IMAP4_SSL(os.getenv('ZOHO_IMAP_HOST','imap.zoho.com'),int(os.getenv('ZOHO_IMAP_PORT','993')),timeout=30)
c.login(os.environ['ZOHO_IMAP_USER'],os.environ['ZOHO_IMAP_PASSWORD'])
result={p['email'].lower():[] for p in pool}; coverage=[]; errors=[]
for raw in c.list()[1]:
    line=raw.decode(); m=re.match(r'^\(.*?\)\s+".*?"\s+(.+)$',line)
    if not m or '\\Noselect' in line: continue
    folder=m.group(1)
    try:
        if c.select(folder,readonly=True)[0]!='OK': raise RuntimeError('select failed')
        typ,data=c.uid('SEARCH',None,'SINCE 01-May-2026')
        ids=data[0].split();coverage.append({'folder':folder,'since':'2026-05-01','messages':len(ids)})
        for start in range(0,len(ids),100):
            typ,rows=c.uid('FETCH',b','.join(ids[start:start+100]),'(BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT DATE MESSAGE-ID IN-REPLY-TO REFERENCES AUTO-SUBMITTED)])')
            for row in rows or []:
                if not isinstance(row,tuple):continue
                msg=BytesParser(policy=policy.default).parsebytes(row[1]);uid=re.search(rb'UID (\d+)',row[0]).group(1).decode()
                froms={v.lower() for _,v in getaddresses(msg.get_all('From',[]))};tos={v.lower() for _,v in getaddresses(msg.get_all('To',[])+msg.get_all('Cc',[]))}
                bounce=any('mailer-daemon' in x or 'postmaster' in x for x in froms) or any(x in str(msg.get('Subject','')).lower() for x in ['undeliver','delivery failure','delivery status notification'])
                matched=[p for p in pool if p['email'].lower() in tos or any(a.split('@')[-1]==p['email'].split('@')[-1].lower() for a in froms)]
                text=''
                if bounce or (matched and folder.strip('"') not in ['Sent','Drafts'] and not any('possiblemind' in x for x in froms)):
                    _,parts=c.uid('FETCH',uid,'(BODY.PEEK[])')
                    full=BytesParser(policy=policy.default).parsebytes(next(x[1] for x in parts if isinstance(x,tuple)))
                    text='\n'.join(x.get_content() for x in full.walk() if x.get_content_type()=='text/plain' and x.get_content_disposition()!='attachment')
                    if bounce: matched=[p for p in pool if p['email'].lower() in text.lower()]
                for p in matched:
                    e=p['email'].lower();item={'folder':folder,'uid':uid,'from':str(msg.get('From','')),'to':str(msg.get('To','')),'subject':str(msg.get('Subject','')),'date':str(msg.get('Date','')),'message_id':str(msg.get('Message-ID','')),'in_reply_to':str(msg.get('In-Reply-To','')),'references':str(msg.get('References',''))}
                    if text:item['body_excerpt']=text[:3500]
                    item['bounce']=bounce;result[e].append(item)
    except Exception as exc:errors.append({'folder':folder,'error':type(exc).__name__+': '+str(exc)})
c.logout()
print(json.dumps({'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'coverage':coverage,'errors':errors,'matches':result}))
