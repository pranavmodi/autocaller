import datetime as dt
import imaplib, json, os, re
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
from pathlib import Path
from dotenv import load_dotenv

targets = json.loads((Path(__file__).parent / "targets.json").read_text())
load_dotenv("/home/pranav/possibleos/.env")
imap = imaplib.IMAP4_SSL(
    os.getenv("ZOHO_IMAP_HOST", "imap.zoho.com"),
    int(os.getenv("ZOHO_IMAP_PORT", "993")),
    timeout=40,
)
imap.login(os.environ["ZOHO_IMAP_USER"], os.environ["ZOHO_IMAP_PASSWORD"])
result = {t["email"].lower(): [] for t in targets}
coverage, errors = [], []

for raw in imap.list()[1]:
    line = raw.decode(errors="replace")
    match = re.match(r'^\(.*?\)\s+".*?"\s+(.+)$', line)
    if not match or "\\Noselect" in line:
        continue
    folder = match.group(1)
    try:
        if imap.select(folder, readonly=True)[0] != "OK":
            raise RuntimeError("select failed")
        typ, data = imap.uid("SEARCH", None, "SINCE 01-Aug-2026")
        ids = data[0].split()
        coverage.append({"folder": folder, "since": "2026-08-01", "messages": len(ids)})
        for start in range(0, len(ids), 100):
            typ, rows = imap.uid(
                "FETCH",
                b",".join(ids[start : start + 100]),
                "(BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT DATE MESSAGE-ID IN-REPLY-TO REFERENCES AUTO-SUBMITTED)])",
            )
            for row in rows or []:
                if not isinstance(row, tuple):
                    continue
                header = BytesParser(policy=policy.default).parsebytes(row[1])
                uid_match = re.search(rb"UID (\d+)", row[0])
                if not uid_match:
                    continue
                uid = uid_match.group(1).decode()
                froms = {v.lower() for _, v in getaddresses(header.get_all("From", []))}
                tos = {v.lower() for _, v in getaddresses(header.get_all("To", []) + header.get_all("Cc", []))}
                subject = str(header.get("Subject", ""))
                bounce = any("mailer-daemon" in x or "postmaster" in x for x in froms) or any(
                    term in subject.lower() for term in ("undeliver", "delivery failure", "delivery status notification", "returned mail")
                )
                for target in targets:
                    email = target["email"].lower()
                    if email not in tos and not (folder.strip('"') == "Sent" and email in {v.lower() for _, v in getaddresses(header.get_all("To", []))}):
                        continue
                    # Sent copies provide the RFC ancestry; non-Sent copies are reply/bounce evidence.
                    result[email].append({
                        "folder": folder,
                        "uid": uid,
                        "from": str(header.get("From", "")),
                        "to": str(header.get("To", "")),
                        "subject": subject,
                        "date": str(header.get("Date", "")),
                        "message_id": str(header.get("Message-ID", "")),
                        "in_reply_to": str(header.get("In-Reply-To", "")),
                        "references": str(header.get("References", "")),
                        "auto_submitted": str(header.get("Auto-Submitted", "")),
                        "bounce": bounce,
                    })
    except Exception as exc:
        errors.append({"folder": folder, "error": f"{type(exc).__name__}: {exc}"})

imap.logout()
print(json.dumps({"checked_at": dt.datetime.now(dt.timezone.utc).isoformat(), "coverage": coverage, "errors": errors, "matches": result}, indent=2))
