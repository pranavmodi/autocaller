---
name: review-leadership-outreach
description: Verify Yelp or Google reviews about a law firm, identify relevant firm leaders and stored email addresses, draft concise attributed outreach about review-visible client communication problems, and schedule approved emails through the Possible OS CLI using Resend. Use when Codex is asked to turn a Yelp or Google review into leadership outreach, personalize review-based emails, find leadership recipients, or stagger and verify scheduled review outreach.
---

# Review Leadership Outreach

Turn a verified Yelp or Google review into factual, concise outreach to a small
set of firm leaders. Keep review research, drafting approval, and scheduling as
distinct stages.

## Required Inputs

Establish these values before scheduling:

- Exact firm identity: name, domain, and Possible OS PIF ID when available.
- Review platform: Yelp or Google.
- Reviewer name, rating, date, review text, and source URL.
- Leadership recipients and confirmed stored email addresses.
- Approved subject, body, CTA, signature, transport, date, time zone, and cadence.

Ask only for information that cannot be verified from the live source or the
Possible OS data. Drafting does not authorize scheduling or sending. Schedule
only after the user explicitly approves the drafts or directly asks to schedule
the already-reviewed drafts.

## 1. Verify the Review

Record the platform, reviewer, rating, displayed date, exact relevant text,
business profile, source URL, and retrieval time. Never invent or silently fix
a reviewer name, typo, date, rating, or quotation.

### Google

Read `../google-reviews/SKILL.md` completely before operating Chromium or
extracting Google reviews. Prefer the rendered Google Maps profile, sort by
`Newest` when recency matters, expand `See more`, and confirm the business by
name, address, phone, and domain. Use the profile payload only as a labeled
fallback when the rendered list does not update.

### Yelp

Prefer the firm's direct Yelp business page with `sort_by=date_desc`. Confirm
the business identity and extract the reviewer, rating, date, and expanded
review text.

If Yelp returns DataDome, CAPTCHA, or HTTP 403, do not claim that a directory
excerpt or search snippet is a directly verified Yelp review. Use one of these
paths:

1. Use review text supplied by the user and label it user-provided.
2. Use a reliable embedded Yelp excerpt and label the source and limitations.
3. Stop and report that direct Yelp verification is blocked.

Do not bypass access controls or fabricate missing metadata.

### Quotation Rules

Use one short, relevant excerpt in each email, normally fewer than 25 words.
Attribute it to the named reviewer and platform. If the user supplied the full
review text, preserve their requested wording, but still keep outbound excerpts
short. Do not describe an old review as recent; include the date when age is
material.

## 2. Resolve Firm Leadership

Resolve the exact PIF firm record first. Inspect the stored contact roster:

```bash
./bin/possibleos contacts list --firm <PIF_ID> --limit 100
```

Prefer up to three people whose roles can act on communication operations:

- Founder, owner, managing partner, or managing attorney.
- COO, operations leader, intake leader, or office administrator.
- Marketing director or another leader responsible for reputation and demand.

Use only email addresses present in `firm_contacts`, the firm's stored
leadership record, or another verified internal contact source. Merge a
leadership title with a normalized/Front email only when the name match is
strong. Do not guess an address from the firm's email pattern.

Avoid emailing a large share of one firm. Default to at most three leaders and
stagger them. Check current scheduled actions and recent successful sends before
creating new outreach.

## 3. Draft the Emails

Keep each email plain text, specific, and usually under 120 words. Use this
structure:

1. Name the reviewer and platform.
2. Quote or closely describe the communication problem.
3. Explain the business consequence without overstating causation.
4. Give one relevant proof point.
5. End with one direct CTA link.
6. Add the approved signature.

### Subject Line Guidance

Name the reviewer, platform, and firm in the subject. Use neutral, factual
language that makes the reason for the email immediately clear:

```text
<Reviewer> submitted a <Yelp|Google> review about <Firm>
```

Examples:

```text
Marlene A. submitted a Yelp review about Fiore Legal
Jordan R. submitted a Google review about Example Law Firm
```

Preserve the reviewer's displayed name and punctuation. Use `submitted`, not a
possessive construction: write `Marlene A. submitted`, never `Marlene A.'s
submitted`. Do not use sensational labels such as `bad review`, `damaging
complaint`, or `urgent reputation problem`. Do not call the review `recent` or
`new` unless its verified date supports that claim.

Use this default body pattern when it matches the user's offer:

```text
Hi <First name>,

<Reviewer> wrote in a <Yelp|Google> review, "<short exact excerpt>."

Visible communication complaints can weaken trust when prospective clients
compare firms online. We built a communication triage system for Precise
Imaging that flags missed callbacks, aging inquiries, and unresolved messages.

See how it works: https://getpossibleminds.com/solutions/email-automation

Regards,
Pranav
Founder, Possible Minds
https://getpossibleminds.com
```

Vary the operational angle by role, but do not pretend to know internal facts.
Say a negative review can affect search-result trust or conversion; do not claim
that one review caused a ranking penalty unless evidence proves it. Keep the
reviewer's allegation clearly attributed instead of presenting it as an
independently established fact.

Show the complete drafts before scheduling unless the user has already approved
their exact text in the conversation.

## 4. Schedule Through Possible OS

Use `/home/pranav/possibleos` as the working directory. Do not write directly to
Postgres for outreach operations.

### Preflight

Confirm the requested local time is still in the future:

```bash
date -u '+%Y-%m-%d %H:%M:%S UTC'
TZ=America/Los_Angeles date '+%Y-%m-%d %H:%M:%S %Z'
curl -fsS http://127.0.0.1:8099/health
./bin/possibleos actions scheduler-status --json
./bin/possibleos actions list --scheduled --limit 200 --json
```

Require `running: true` and `last_error: null` before reporting that the queue
will drain normally. If a requested time has passed, do not silently move it to
another day. Ask for a new time unless the user already authorized a flexible
window.

### Create a Tracked Batch

Create one curated batch and add the approved recipients by verified email:

```bash
./bin/possibleos lead-gen create-batch \
  --name "<Firm> review outreach <YYYY-MM-DD>" \
  --template-key possible_minds_dynamic \
  --target-metric meetings_booked \
  --created-by operator \
  --json

./bin/possibleos lead-gen add-contacts <BATCH_ID> \
  --contact <EMAIL_1> \
  --contact <EMAIL_2> \
  --contact <EMAIL_3> \
  --actor operator \
  --json

./bin/possibleos lead-gen items <BATCH_ID> --json
```

Confirm every email maps to the intended person and item ID. Stop if a contact
is skipped or the mapping is ambiguous.

### Create Approved Scheduled Actions

Schedule each exact draft with an explicit Resend transport:

```bash
./bin/possibleos actions send-approved-lead-gen-draft \
  --item <ITEM_ID> \
  --subject "<APPROVED_SUBJECT>" \
  --body "<APPROVED_MULTILINE_BODY>" \
  --transport resend \
  --approved-by operator \
  --at "10:00 PDT" \
  --json
```

Use `send-approved-lead-gen-draft`, not `mode=test`, for leadership outreach.
Default to a 10-minute interval for recipients at the same firm, such as 10:00,
10:10, and 10:20 PDT. Preserve the requested time zone explicitly. Do not
schedule same-firm recipients at the same timestamp.

Require every creation response to show:

- `status: approved`.
- `policy.allowed: true` and `policy.reason: allowed`.
- The intended contact email.
- `transport: resend`.
- The expected `scheduled_for` value.

If one action fails, stop creating additional actions until the failure is
understood. Do not weaken duplicate-send, suppression, contact-match, PHI, or
transport policy checks to force the send.

## 5. Audit the Queue

After all actions are created, verify the live queue again:

```bash
./bin/possibleos actions scheduler-status --json
./bin/possibleos actions list --scheduled --limit 200 --json
```

Match each action ID to its recipient, subject, Resend transport, approved
status, and UTC/Pacific slot. Confirm the scheduler's pending count increased by
the expected number and `due_count` is zero for future sends.

Report the recipients, Pacific times, subject, batch ID, action IDs, scheduler
state, and any caveat. Say `scheduled` or `queued`, not `sent`, until execution
has occurred. After the send window, verify the succeeded action and email log
before claiming delivery-provider acceptance.

Use these commands for changes requested before execution:

```bash
./bin/possibleos actions reschedule <ACTION_ID> --at "10:30 PDT" --actor operator
./bin/possibleos actions cancel <ACTION_ID> --reason "<REASON>" --actor operator
```

## Failure Handling

- Treat Yelp CAPTCHA or 403 as a source limitation, not permission to guess.
- Treat missing leadership email as missing; do not synthesize an address.
- Treat a policy refusal as a blocker for that action.
- Treat a stopped scheduler or non-null `last_error` as an operational issue and
  report the queue as created but not healthy.
- Preserve already-created approved actions if a later step fails; list them so
  the user can cancel or resume deliberately.
- Never send or schedule live email while validating or forward-testing this
  skill.
