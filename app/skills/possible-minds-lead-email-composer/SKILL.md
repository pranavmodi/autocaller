---
name: possible-minds-lead-email-composer
description: Compose policy-controlled Possible Minds lead-generation emails for PI firms, healthcare providers, and adjacent operational buyers using firm context, prior emails, replies, Front/Precise relationship signals, booked consult learnings, inferred pain points, optional blog links, and a required consult signature link.
---

# Possible Minds Lead Email Composer

Compose one outbound lead-generation email at a time. The email is part of a
cybernetic lead-gen loop whose target metric is booked qualified conversations.

The sequence step is a strategy objective, not fixed copy. Use the supplied
context to decide the angle, subject, CTA, and whether a blog link helps.

## Output Contract

Return only JSON:

```json
{
  "subject": "Short subject",
  "body": "Plaintext email body",
  "angle": "records_status_workflow",
  "cta": "ask_what_they_are_trying_to_improve",
  "blog_link_used": "https://getpossibleminds.com/blog/example",
  "reasoning": "Why this email fits this firm and step.",
  "risk_flags": [],
  "requires_human_review": false
}
```

Required fields: `subject`, `body`, `angle`, `cta`, `reasoning`,
`requires_human_review`.

## Inputs To Use

Use the payload fields when present:

- `firm`: name, domain, size, practice/domain, known relationship signals.
- `contact`: name, title, email, inferred persona.
- `sequence`: step number, step objective, prior send/reply state.
- `history.previous_emails`: subjects, excerpts, timestamps, outcomes.
- `history.replies`: inbound reply excerpts and classifications.
- `history.booked_consults`: patterns from booked consults and known winning
  pain points.
- `front_signals`: read-only derived signals from Precise/Front inboxes.
- `inferred_pain_points`: ranked operational pains.
- `blog_posts`: allowed getpossibleminds.com blog links.
- `policy`: send rules, target metric, safety constraints, allowed CTA style.
- `sender`: sender name, title, company, consult URL.

## Strategy

Pick one clear job for the email:

- open a relevant operational conversation
- answer a reply and ask what they are trying to improve
- reframe after no response
- ask for the right owner/referral
- close the loop respectfully

Do not repeat prior copy. Use prior emails and replies to change the frame.

## Angle Selection

- Records/images or reports signal: records request, image/report status, or
  missing-doc workflow.
- Scheduling/orders signal: order intake, scheduling handoff, status updates.
- Liens/negotiation/AR signal: lien reduction, collections, negotiation ops.
- Founder/managing partner: leverage, revenue leakage, speed to signed cases,
  operational bottlenecks.
- COO/operations: staff workload, queue visibility, handoffs, exception
  handling, tracking.
- Healthcare operator: inbox triage, document validation, patient/provider
  support, status automation.

If a reply asks "how does it work?", answer directly in one short paragraph:
Possible Minds maps the current workflow, identifies the highest-leverage
automation opportunity, builds the first useful system, and measures whether it
reduces workload or improves throughput. Then ask what they are trying to
improve now.

## Blog Links

Use at most one blog link, only when it strengthens the email. Prefer a link
whose topic matches the inferred pain or buyer persona. Do not force a blog
link into a reply where a direct answer is better.

Only use links provided in `blog_posts` or links on `https://getpossibleminds.com`.

## Required Signature

Every email body must end with a signature that includes the consult page link:

```text
-- {sender.name}
{sender.title}, Possible Minds
https://getpossibleminds.com/consult
```

If the sender title is missing, use `Founder`.

## Safety Rules

- Never mention private patient, case, billing, or message details from Front.
- Never imply Precise Imaging endorsed the outreach unless the payload
  explicitly says so.
- Do not claim certainty about internal pain; say "often", "looks like", or
  ask.
- Keep the email short: normally 80-160 words.
- Plaintext only.
- No fake familiarity.
- No hard calendar ask unless policy explicitly requests it.
- If the context is sensitive, ambiguous, or there was a negative reply, set
  `requires_human_review` to true.

