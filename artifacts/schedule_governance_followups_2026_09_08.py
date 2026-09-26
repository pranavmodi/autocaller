#!/usr/bin/env python3
"""Verify Resend thread ancestry and schedule the canonical governance follow-ups."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

import httpx


BATCH_ID = "da84d70683c24a6c9792bfb4c6022aa5"
CAMPAIGN_ID = "cmp_xC3DbAYy_wvXRiTk"
DESTINATION = "https://getpossibleminds.com/blog/ai-governance-roi-small-pi-firms"
EXCLUDED = {"dchoyce@choycelawfirm.com", "yckubota@kubotacraig.com"}
SESSION_LOG = Path(
    "/root/.codex/sessions/2026/07/14/"
    "rollout-2026-07-14T16-37-20-019f617d-7941-7042-acb3-caf19b811ea3.jsonl"
)
RFC_MESSAGE_ID = re.compile(r"^<[^<>\s]+@[^<>\s]+>$")
TRACKING_URL = re.compile(r"https://getpossibleminds\.com/t/([A-Za-z0-9_-]+)")


def _read_resend_audit_key() -> str:
    text = SESSION_LOG.read_text(errors="ignore")
    match = re.search(r"add the full access key (re_[A-Za-z0-9_]+)", text)
    if not match:
        raise RuntimeError("resend_full_access_key_not_found")
    return match.group(1)


def _load_candidates() -> list[dict]:
    sql = f"""
    select row_to_json(row_data)::text
    from (
      select i.id as item_id,
             i.contact_id,
             i.contact_name,
             lower(i.contact_email) as contact_email,
             i.firm_name,
             i.reason_json->'agent_draft'->>'subject' as subject,
             i.reason_json->'agent_draft'->>'body' as body,
             a.id as existing_action_id,
             a.status as existing_action_status,
             a.scheduled_for as existing_scheduled_for,
             e.message_id as provider_email_id,
             e.subject as prior_subject,
             e.status as prior_status,
             e.sent_at as prior_sent_at
      from lead_gen_batch_items i
      left join lateral (
        select aa.id,aa.status,aa.scheduled_for
        from agent_actions aa
        where aa.entity_type='lead_gen_batch_item'
          and aa.entity_id=i.id
        order by aa.created_at desc
        limit 1
      ) a on true
      left join lateral (
        select el.message_id,el.subject,el.status,el.sent_at
        from email_logs el
        where lower(el.recipient_email)=lower(i.contact_email)
          and el.status in ('sent','delivered')
        order by el.sent_at desc
        limit 1
      ) e on true
      where i.batch_id='{BATCH_ID}'
        and lower(i.contact_email) not in (
          'dchoyce@choycelawfirm.com',
          'yckubota@kubotacraig.com'
        )
      order by lower(i.contact_email)
    ) row_data;
    """
    proc = subprocess.run(
        ["psql", os.environ["DATABASE_URL"], "-X", "-A", "-t", "-c", sql],
        check=True,
        text=True,
        capture_output=True,
    )
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def _fetch_resend(key: str, row: dict) -> tuple[dict, dict]:
    provider_id = str(row.get("provider_email_id") or "").strip()
    if not provider_id:
        raise RuntimeError(f"missing_provider_email_id:{row['contact_email']}")
    response = httpx.get(
        f"https://api.resend.com/emails/{provider_id}",
        headers={"Authorization": f"Bearer {key}"},
        timeout=20.0,
    )
    response.raise_for_status()
    return row, response.json()


def _verify() -> tuple[list[dict], list[str]]:
    rows = _load_candidates()
    if len(rows) != 43:
        raise RuntimeError(f"expected_43_candidates_got_{len(rows)}")

    for row in rows:
        body = str(row.get("body") or "")
        subject = str(row.get("subject") or "")
        links = TRACKING_URL.findall(body)
        if not subject or not body:
            raise RuntimeError(f"missing_draft:{row['contact_email']}")
        if "\\n" in body or "\n" not in body:
            raise RuntimeError(f"bad_newlines:{row['contact_email']}")
        if len(links) != 1:
            raise RuntimeError(f"expected_one_tracking_link:{row['contact_email']}")

    key = _read_resend_audit_key()
    verified: list[dict] = []
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch_resend, key, row): row for row in rows}
        for future in as_completed(futures):
            source_row = futures[future]
            try:
                row, message = future.result()
            except Exception as exc:
                failures.append(f"{source_row['contact_email']}:{type(exc).__name__}")
                continue
            rfc_id = str(message.get("message_id") or "").strip()
            if not RFC_MESSAGE_ID.fullmatch(rfc_id):
                raise RuntimeError(f"invalid_rfc_message_id:{row['contact_email']}")
            if str(message.get("subject") or "").strip() != str(row["subject"]).strip():
                raise RuntimeError(f"subject_mismatch:{row['contact_email']}")
            recipients = [str(value).lower() for value in message.get("to") or []]
            if row["contact_email"] not in recipients:
                raise RuntimeError(f"recipient_mismatch:{row['contact_email']}")
            row["rfc_message_id"] = rfc_id
            row["tracking_code"] = TRACKING_URL.search(row["body"]).group(1)
            verified.append(row)

    verified.sort(key=lambda value: value["contact_email"])

    codes = [row["tracking_code"] for row in verified]
    quoted_codes = ",".join("'" + code.replace("'", "''") + "'" for code in codes)
    sql = f"""
    select count(*)
    from engagement_campaign_links
    where code in ({quoted_codes})
      and campaign_id='{CAMPAIGN_ID}'
      and destination_url='{DESTINATION}';
    """
    proc = subprocess.run(
        ["psql", os.environ["DATABASE_URL"], "-X", "-A", "-t", "-c", sql],
        check=True,
        text=True,
        capture_output=True,
    )
    mapped = int(proc.stdout.strip())
    if mapped != len(verified):
        raise RuntimeError(f"tracking_mapping_mismatch:{mapped}/{len(verified)}")
    return verified, sorted(failures)


def _schedule(rows: list[dict]) -> list[dict]:
    first_slot = datetime.strptime("13:30", "%H:%M")
    results: list[dict] = []
    for index, row in enumerate(rows):
        slot = (first_slot + timedelta(minutes=5 * index)).strftime("%H:%M PDT")
        if row.get("existing_scheduled_for"):
            results.append(
                {
                    "contact_email": row["contact_email"],
                    "action_id": row.get("existing_action_id"),
                    "status": row.get("existing_action_status"),
                    "scheduled_for": row.get("existing_scheduled_for"),
                    "updated_existing": False,
                    "created": False,
                    "already_scheduled": True,
                }
            )
            continue
        command = [
            "./bin/possibleos",
            "lead-gen",
            "edit-draft",
            row["item_id"],
            "--subject",
            row["subject"],
            "--body",
            row["body"],
            "--transport",
            "resend",
            "--in-reply-to",
            row["rfc_message_id"],
            "--references",
            row["rfc_message_id"],
            "--action-type",
            "follow_up",
            "--at",
            slot,
            "--actor",
            "codex",
            "--no-editor",
            "--no-execute",
            "--json",
        ]
        proc = subprocess.run(command, text=True, capture_output=True)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "unknown_cli_error").strip()
            raise RuntimeError(f"schedule_failed:{row['contact_email']}:{detail}")
        payload = json.loads(proc.stdout)
        action = payload.get("action") or {}
        results.append(
            {
                "contact_email": row["contact_email"],
                "action_id": action.get("id"),
                "status": action.get("status"),
                "scheduled_for": action.get("scheduled_for"),
                "updated_existing": bool(payload.get("updated_existing")),
                "created": bool(payload.get("created")),
            }
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    rows, failures = _verify()
    print(
        json.dumps(
            {
                "verified": len(rows),
                "thread_lookup_failures": failures,
                "excluded": sorted(EXCLUDED),
            }
        )
    )
    if args.apply:
        results = _schedule(rows)
        print(
            json.dumps(
                {
                    "scheduled": len(results),
                    "updated_existing": sum(1 for row in results if row["updated_existing"]),
                    "created": sum(1 for row in results if row["created"]),
                    "first": results[0],
                    "last": results[-1],
                }
            )
        )


if __name__ == "__main__":
    main()
