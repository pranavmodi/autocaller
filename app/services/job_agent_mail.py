"""Zoho CLI delivery, read-only duplicate checks, and attachment-aware Sent verification."""
from __future__ import annotations

import hashlib
import imaplib
import json
import re
import subprocess
import time
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
from pathlib import Path

from app.services.inbound_email import inbound_email_config, parse_inbound_message, _sent_mailbox
from app.services.job_agent_resumes import RESUME_ROOT
from app.services.career_job_store import source_identity


def cli_result(stdout):
    for line in reversed(stdout.splitlines()):
        try:
            result = json.loads(line.strip())
            if isinstance(result, dict) and isinstance(result.get('status'), dict):
                return result
        except ValueError:
            continue
    raise RuntimeError('Zoho CLI returned no parseable status.')


def send_cli(email, attachment_path):
    from app.services.email_notification_service import _zoho_account_id, _zoho_upload_attachment
    # The existing authenticated uploader returns the metadata required by the CLI.
    uploaded = _zoho_upload_attachment(_zoho_account_id(), attachment_path)
    attachment = '::'.join(uploaded[key] for key in ('attachmentName', 'attachmentPath', 'storeName'))
    result = subprocess.run(['/usr/local/bin/zmail-possibleos', 'message', 'send',
        '--from-address=' + email['from'], '--to-address=' + email['to'], '--subject=' + email['subject'],
        '--content=' + email['body_text'], '--mail-format=plaintext', '--attachments=' + attachment,
        '-f', 'JSON'], capture_output=True, text=True, timeout=150)
    parsed = cli_result(result.stdout)
    if result.returncode != 0 or str(parsed['status'].get('code')) != '200':
        raise RuntimeError('Zoho CLI did not confirm provider acceptance.')
    return {'transport': 'zoho_cli', 'accepted': True, 'status_code': 200}


def _messages(recipient, *, include_pending=False):
    cfg = inbound_email_config()
    if not cfg.configured:
        raise RuntimeError('Zoho mailbox access is required for duplicate checks and Sent verification.')
    connection = imaplib.IMAP4_SSL(cfg.host, cfg.port, timeout=40)
    try:
        connection.login(cfg.user, cfg.password)
        mailboxes = [_sent_mailbox()]
        if include_pending:
            status, listing = connection.list()
            if status != 'OK':
                raise RuntimeError('Could not inspect pending mailbox folders.')
            for entry in listing:
                decoded = entry.decode('utf-8', errors='replace')
                match = re.search(r'"([^"\\]*(?:\\.[^"\\]*)*)"\s*$', decoded)
                name = match.group(1) if match else decoded.rsplit(' ', 1)[-1]
                if any(word in name.casefold() for word in ('draft', 'outbox', 'scheduled')) and name not in mailboxes:
                    mailboxes.append(name)
        for mailbox in mailboxes:
            status, _ = connection.select('"' + mailbox.replace('"', '\\"') + '"', readonly=True)
            if status != 'OK':
                raise RuntimeError('Could not inspect a required mailbox folder.')
            # Recipient is already validated; quote for the IMAP string grammar.
            quoted = '"' + recipient.replace('\\', '\\\\').replace('"', '\\"') + '"'
            status, result = connection.uid('SEARCH', None, 'TO', quoted)
            if status != 'OK':
                raise RuntimeError('Zoho mailbox search did not complete.')
            for uid in reversed((result[0] or b'').split()):
                status, fetched = connection.uid('FETCH', uid, '(BODY.PEEK[])')
                if status != 'OK':
                    raise RuntimeError('A matching mailbox message could not be inspected.')
                raw = next((part[1] for part in fetched if isinstance(part, tuple) and isinstance(part[1], bytes)), None)
                if raw:
                    yield mailbox, uid.decode(), raw
    finally:
        try:
            connection.logout()
        except Exception:
            pass


def _normalized(value):
    return ' '.join(str(value).split()).casefold()


def previous_packet(posting):
    source = source_identity(posting['source_url'])
    for path in (RESUME_ROOT / 'applications').rglob('handoff.json'):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        email = data.get('email') if isinstance(data.get('email'), dict) else {}
        sent = data.get('email_sent') is True or data.get('sent') is True or data.get('email_status') == 'sent_verified' or email.get('status') == 'sent_verified'
        if not sent:
            continue
        job = data.get('job') if isinstance(data.get('job'), dict) else {}
        urls = [data.get('job_url'), job.get('url'), data.get('source_url')]
        if any(isinstance(url, str) and url and source_identity(url) == source for url in urls):
            return {'kind': 'previous_application', 'evidence_file': str(path.relative_to(RESUME_ROOT)),
                    'message': 'A previous application packet records an email sent for this job.'}
    return None


def duplicate_check(email, posting):
    previous = previous_packet(posting)
    if previous:
        return previous
    for mailbox, uid, raw in _messages(email['to'], include_pending=True):
        parsed = parse_inbound_message(raw_message=raw, account_email=email['from'], mailbox=mailbox, uid=uid)
        if (_normalized(parsed.subject) == _normalized(email['subject']) or
            posting['source_url'] in parsed.body_text or
            (_normalized(posting['title']) in _normalized(parsed.subject) and len(posting['title']) > 5)):
            return {'kind': 'mailbox_match', 'mailbox': mailbox, 'uid': uid,
                    'subject': parsed.subject, 'message_id': parsed.message_id}
    return None


def verify_sent(email, attachment_sha256):
    for attempt in range(3):
        for mailbox, uid, raw in _messages(email['to']):
            message = BytesParser(policy=policy.default).parsebytes(raw)
            parsed = parse_inbound_message(raw_message=raw, account_email=email['from'], mailbox=mailbox, uid=uid)
            if _normalized(parsed.subject) != _normalized(email['subject']):
                continue
            if _normalized(parsed.body_text) != _normalized(email['body_text']):
                continue
            senders = {addr.casefold() for _, addr in getaddresses(message.get_all('From', []))}
            if email['from'].casefold() not in senders:
                continue
            hashes = [hashlib.sha256(part.get_payload(decode=True) or b'').hexdigest()
                      for part in message.walk() if part.get_filename()]
            if attachment_sha256 in hashes:
                return {'mailbox': mailbox, 'uid': uid, 'message_id': parsed.message_id,
                        'provider_message_id': message.get('X-ZM-MESSAGEID'),
                        'attachment_sha256': attachment_sha256, 'recipient_delivery': 'not_confirmed'}
        if attempt < 2:
            time.sleep(2)
    return None
