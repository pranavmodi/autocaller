# Review Alerts

`/review-alerts` monitors enrolled PI firms and prepares an email to one leader:
founder/owner, then managing partner, then COO. Enrollment reuses the established
contact-selection policy only as a fast candidate prefilter and requires a named
email on the canonical firm domain. Final role eligibility is a structured LLM
decision with at least 90% confidence and exact title evidence. Common titles
share cached decisions; the worker processes up to 50 distinct titles per cycle.
The enrollment request persists while classification proceeds, and qualified
firms enroll incrementally. No firm enrolls a lower-ranked leader while another
potential leader's title remains unclassified.
Personal mailboxes, generic inboxes, merged records, duplicate domains and
existing opt-outs/negative replies/bounces are excluded. Re-enrollment never
changes an existing subscription or moves to another leader to evade an opt-out.

## Operations

```bash
bin/possibleos review-alerts enroll            # read-only candidate preview
bin/possibleos review-alerts enroll --execute  # enroll, does not send
bin/possibleos review-alerts config --enabled --no-auto-send
bin/possibleos review-alerts config --auto-schedule --auto-schedule-time 09:15 --auto-schedule-limit 20
bin/possibleos review-alerts run
bin/possibleos review-alerts status
bin/possibleos review-alerts config --postal-address 'REAL BUSINESS ADDRESS' --auto-send
bin/possibleos review-alerts subscription FIRM_ID --status paused
bin/possibleos review-alerts subscription FIRM_ID --status unsubscribed
```

Defaults: monitoring off and sending off, with a 25-email daily limit.
All configuration lives in `system_settings.agent_config.review_alerts`.
Review collection is part of nightly firm maintenance. When a law firm is
selected for profile maintenance, the same nightly run queues one Google review
check for it. The Review Alerts loop never queues its own research. It only
turns stored, newly eligible reviews into alert drafts and handles scheduling,
sending and replies. Platform accessibility can limit coverage. No EmailTag
research is used.

`auto_schedule` is separate from the legacy direct `auto_send` path. When
enabled, the five-minute monitor creates one normal lead-gen wave per Pacific
day after `auto_schedule_time` (default 09:15), with at most
`auto_schedule_limit` firms (default/max 20). It drafts the exact body, creates
the curated batch, approves and policy-checks each action, and gives eligible
messages five-minute slots. The normal Send Queue then executes them. A restart
before the configured time waits; a restart after it schedules at least 15
minutes in the future. A failure is saved in status and retried after 30 minutes.
After one successful daily attempt, including a legitimate zero-eligible run,
the monitor does not create a second wave that day. Manual scheduling remains
available for an operator-authorized exception.

Only stored Google/Yelp reviews with an exact publication date in today's UTC date and
the preceding 13 dates qualify. Unknown dates and old reviews discovered today do
not qualify. A maximum of ten new reviews are grouped per digest. Each email
quotes the full stored review verbatim, including original line breaks, with the
reviewer name when available, rating, publication date and source link. No LLM
summary, invented text or truncation is substituted. Missing/blank review text
does not qualify; legacy metadata-only deliveries must have their evidence
refreshed before composing, rather than silently sending only a link. Existing
outbound safety checks remain in force. Sent records are never rewritten or
automatically resent when the format changes.

### Review Response Advice

Newly composed emails include one short note after the review excerpts: replies
are also read by prospective clients; thank reviewers personally, address
criticism professionally, invite private discussion instead of arguing, and do
not disclose client/case details. The note says "If you haven't replied yet"
because this workflow does not establish whether the firm has already replied.
It makes no promise of improved rankings, revenue or review removal.

Evidence checked against the raw timestamped Mission Control transcripts on
2026-09-21 (not only generated episode summaries):

- [PIM 453: How Do I Get More Google Reviews for My Personal Injury Firm?](https://mission.getpossibleminds.com/podcasts/4262), 03:43-04:35: responses are for other readers too; professionalism and accountability, not excuses or humor.
- [PIM 350: Local AI SEO](https://mission.getpossibleminds.com/podcasts/2934), 34:17-34:45: thank positive reviewers and address negative experiences.
- [PIM 356: AI-Power Your Law Firm's Reputation](https://mission.getpossibleminds.com/podcasts/2928), 25:04-25:37: respond authentically and invite a phone conversation rather than attacking the reviewer.
- [Google Business Profile reply guidance](https://support.google.com/business/answer/3474122), checked 2026-09-21: concise, personal, professional replies, privacy protection and private resolution of complex concerns. The client/case privacy wording is our application of this guidance, not a podcast quote or legal opinion.

This is email template copy, not an LLM prompt. It does not send replies to Google
or Yelp or resend historical emails.

## Delivery And Replies

`review_alert_deliveries` is a durable outbox, `review_alert_items` is a per-firm
deduplication ledger. Native review IDs are used where available; otherwise
platform, reviewer and original publication date form the identity. Text edits
do not create another alert. One digest per firm per 24 hours, plus a global UTC
daily limit, is checked again at send time. The recipient, canonical identity,
publication window, opt-out status and configuration are also rechecked.

The sender must be an allowed sender matching the configured Zoho IMAP mailbox;
Zoho API is the only supported transport for this workflow. A real business
mailing address is required before enabling automatic sends. The email asks
whether the alert is useful and explicitly offers opt-out by replying.

Before sending, a bounded Zoho inbox scan must succeed. A saturated scan or inbox
failure holds sending. Every incoming message from an enrolled recipient pauses
their alerts and cancels queued messages immediately, before the existing
structured feedback classifier runs via `openclaw/main`. Classified opt-outs or
negative replies unsubscribe the firm; ambiguity/errors remain paused. Positive
replies also remain paused for operator follow-up. No automatic reply is sent.
Unsubscribed firms cannot be automatically resumed or re-enrolled. The common
email transport also blocks unsubscribed recipients/firms, including other
outbound email workflows.

Every provider attempt has a full-body `email_logs` record before sending and is
visible in `/comms` as `review_alert`, linked to its firm and selected recipient.
The deterministic source identity updates the same Comms row. `sent` means
provider accepted, not delivered. A transport error or interrupted send becomes
`uncertain`; it is never retried automatically. Inspect the real Sent mailbox
before any manual action. Collection retries on later daily cycles; a collection
error does not erase prior reviews.

## Deployment

### Standard Lead-Gen Queue

For an operator-authorized wave, run `bin/possibleos review-alerts schedule
--start '2026-09-20T12:15:00-07:00' --limit 20 --dry-run`, then repeat without
`--dry-run`. Choose a future time today in Pacific time. The command schedules
at most 20 firms for the day, oldest qualifying reviews first, five minutes apart.
It creates editable drafts in a curated `Recent review alerts - DATE` batch and
normal Send Queue actions. Existing provider strategy, caps and policy checks
remain in force. Successful runs are idempotent; existing linked deliveries count
toward the day's ceiling. Fewer eligible firms means fewer scheduled emails.

This mode uses the existing lead-gen sender/signature and monitored reply-to,
without an invented postal address or placeholder. It disables the separate
direct-send path (`delivery_mode=lead_gen`, `auto_send=false`). It does not
automatically create additional daily waves. A configured real postal address
is included when available. Before sending, the linked review, recipient,
subscription, mailbox freshness and same-day contact checks run again. New review
events may notify an already-contacted recipient; the ordinary first-touch-only
duplicate rule is replaced by these review-specific checks, not other policies.
Uncertain provider attempts never fall back to a second transport. Comms keeps
the full body under the same review source identity.

Apply revision `f2060920a001` after the base review-alert migration for action,
draft and schedule linkage. Only a safe backend restart is needed for this bridge.

Apply Alembic revision `e2060920a001` after `d9e0f1g2h3i4`, then safely restart the
backend (check active calls first). Build/deploy the frontend. No new cron or
systemd timer is needed. The existing 01:00 IST nightly maintenance schedule owns
review collection; career schedules are unchanged.
The title-selection prompt is `app/skills/review-alert-leader-titles/SKILL.md`,
traced by prompt version v1.73. Other research/reply instructions are reused.

## Limits

Date-only publication data has day precision, not exact 336-hour precision.
Without a platform review ID, a corrected reviewer name/date can change identity;
the fallback deliberately favors suppressing possible duplicates. The research
worker cannot promise exhaustive Google/Yelp coverage. A reply arriving after
the final mailbox check cannot recall an email already submitted to the provider.
Inbox overflow fails closed instead of silently dropping opt-outs. Only the
first 20 new replies per cycle are automatically classified; all are paused,
and any remaining replies require operator review.
