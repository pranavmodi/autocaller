import datetime as dt
import imaplib,json,os,re
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
from pathlib import Path
from dotenv import load_dotenv

targets=json.loads((Path(__file__).parent/'candidates.json').read_text())
load_dotenv('/home/pranav/possibleos/.env')
m=imaplib.IMAP4_SSL(os.getenv('ZOHO_IMAP_HOST','imap.zoho.com'),int(os.getenv('ZOHO_IMAP_PORT','993')),timeout=40)
m.login(os.environ['ZOHO_IMAP_USER'],os.environ['ZOHO_IMAP_PASSWORD'])
result={t['email']:[] for t in targets}; coverage=[]; errors=[]
for raw in m.list()[1]:
 line=raw.decode(errors='replace'); fm=re.match(r'^\(.*?\)\s+".*?"\s+(.+)$',line)
 if not fm or '\\Noselect' in line: continue
 folder=fm.group(1)
 try:
  if m.select(folder,readonly=True)[0]!='OK': raise RuntimeError('select failed')
  typ,data=m.uid('SEARCH',None,'SINCE 01-Aug-2026'); ids=data[0].split()
  coverage.append({'folder':folder,'since':'2026-08-01','messages':len(ids)})
  for start in range(0,len(ids),100):
   typ,rows=m.uid('FETCH',b','.join(ids[start:start+100]),'(BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT DATE MESSAGE-ID IN-REPLY-TO REFERENCES AUTO-SUBMITTED)])')
   for row in rows or []:
    if not isinstance(row,tuple): continue
    h=BytesParser(policy=policy.default).parsebytes(row[1]); u=re.search(rb'UID (\d+)',row[0])
    if not u: continue
    uid=u.group(1).decode(); fr={v.lower() for _,v in getaddresses(h.get_all('From',[]))}; to={v.lower() for _,v in getaddresses(h.get_all('To',[])+h.get_all('Cc',[]))}
    subj=str(h.get('Subject','')); bounce=any('mailer-daemon' in x or 'postmaster' in x for x in fr) or any(x in subj.lower() for x in ['undeliver','delivery failure','delivery status notification','returned mail'])
    direct=[t for t in targets if t['email'] in fr|to or (any(x.endswith('@'+t['email'].split('@')[1]) for x in fr) and t['email'].split('@')[1] not in ['gmail.com','aol.com'])]
    body=''
    if bounce or (direct and folder.strip('"')!='Sent'):
     _,full=m.uid('FETCH',uid,'(BODY.PEEK[])')
     b=next((r[1] for r in full if isinstance(r,tuple)),b'')
     msg=BytesParser(policy=policy.default).parsebytes(b)
     for part in msg.walk():
      if part.get_content_type() in ('text/plain','message/delivery-status'):
       try: body+=str(part.get_content())+'\n'
       except Exception: body+=str(part.get_payload())+'\n'
    for t in targets:
     if t not in direct and not (bounce and t['email'] in body.lower()): continue
     result[t['email']].append({'folder':folder,'uid':uid,'from':str(h.get('From','')),'to':str(h.get('To','')),'subject':subj,'date':str(h.get('Date','')),'message_id':str(h.get('Message-ID','')),'in_reply_to':str(h.get('In-Reply-To','')),'references':str(h.get('References','')),'auto_submitted':str(h.get('Auto-Submitted','')),'bounce':bounce,'body':body[:12000]})
 except Exception as e: errors.append({'folder':folder,'error':str(e)})
m.logout()
print(json.dumps({'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),'coverage':coverage,'errors':errors,'matches':result}))
