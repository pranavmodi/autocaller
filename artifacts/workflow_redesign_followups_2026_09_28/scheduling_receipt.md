# PI workflow-redesign follow-ups — 2026-09-28

- Campaign: `cmp_rj0PfxnI2Ub_EOAN` — *PI Workflow Redesign Follow-ups - 30 - 2026-09-28*
- Batch: `3de2e84830df4de7b4c5db3b98805fe2`
- Destination: `https://getpossibleminds.com/blog/redesign-pi-workflows-around-ai`
- Live queue: 30 approved `follow_up` actions, all policy-allowed, all unexecuted, with 30 distinct recipient domains.
- Schedule: 08:30–13:20 PDT (15:30–20:20 UTC), 10 minutes apart.
- Transport: Resend, under `resend_first_then_zoho` (Resend cap 50; Zoho cap 0; daily budget 50).
- Scheduler verification: running, no error, 30 pending, 0 due at validation.

The original 30-draft source, including exact bodies, threading fields, schedules, recipient-specific article links, and rationales is in `draft_plan.json`. Three candidates were cancelled before execution after a fresh policy check found newer successful outreach actions. Their live slots were replaced with the following verified threaded actions:

| PDT | Recipient | Firm | Action |
| --- | --- | --- | --- |
| 09:30 | simon@cmplawgroup.com | CMP Law Group | `action_4f0759682aa54d658d3f4541` |
| 09:40 | gregory.ante@antelaw.com | Ante Law Firm | `action_cf9e267193824b83a905b947` |
| 09:50 | tony@rahnamalaw.com | Rahnama Law | `action_58d8f90d07af404594fed0ee` |

Those three used actual Zoho Sent `Message-ID` ancestry, have no observed mailbox reply, bounce, or opt-out, and each has a unique unsent email tracking link. The campaign has 33 links total: 30 correspond to the live actions and three were left unsent after their policy-blocked actions were cancelled.
