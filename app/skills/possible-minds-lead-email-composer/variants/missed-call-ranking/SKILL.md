---
name: possible-minds-lead-email-composer
description: Compose a first-touch Possible Minds lead-gen email for PI firms built on one insight, that a missed call both loses the case and decays the firm's Google map-pack ranking, leading to our voice-AI intake solution. Plaintext, operator-approved before send.
---

# Possible Minds Lead Email Composer — Missed-Call Ranking variant

Compose one outbound first-touch email at a time for a personal-injury firm
decision maker (founder, managing partner, owner, operations leader). The email
is part of a cybernetic lead-gen loop whose target metric is booked qualified
conversations. Every email is operator-approved before send.

## The one idea this variant sells

A missed call is a double loss. Beyond losing that caller's case, Google reads an
unanswered call as a failed result for the listing and quietly lowers the firm's
local map-pack ranking, so it costs the firm the next callers too. The decline
compounds: fewer answered calls, lower ranking, fewer calls. One business in a
recent local-search breakdown saw its rankings drop after about two weeks of
spotty phone coverage.

Possible Minds builds voice-AI phone intake that answers every call, including
after-hours and overflow, so both the lead and the ranking signal survive. Do
not pitch a feature list in the email; the linked solution page covers that. Earn
the click and the reply with the insight.

## Required first-touch opener

After the greeting, open with the Precise proof. Use confident wording when the
payload has a clear Precise relationship signal; conditional wording when it is
inferred from the lead source.

```text
Pranav from Possible Minds. If {firm_name} refers clients to Precise Imaging,
you've seen the automated status replies they send: we built that system.
```

You may add the scale proof in one short sentence: Precise receives about 600
inbound emails a day and the system triages them so staff only touch exceptions.
Keep it to one sentence; this email's real subject is the phone, not email.

## Body shape

1. Precise opener (above).
2. The missed-call -> ranking-decay insight, in plain language, framed as a leak
   that compounds. Make it concrete and a little surprising; most founders know
   missed calls lose cases but not that they also drag the Google ranking.
3. One sentence on what we build: voice-AI intake that answers every call,
   after-hours and overflow included, so the lead and the ranking both survive.
4. A primary CTA that is a low-friction binary reply question, for example:
   `Is after-hours intake the leak you'd most want closed at {firm_name}, or is
   the bigger drag somewhere else?`

Do NOT add a product link, a solution-page URL, or a "P.S." yourself, and do NOT
write the consult signature. The sending system appends the consult signature and
a tracked solution-page link automatically. Your job is the greeting, the opener,
the insight, the one-sentence solution, and the binary question.

Keep the body roughly 90-150 words. Plaintext only.

## Output Contract

Return only JSON:

```json
{
  "subject": "short, lowercase-casual subject about missed calls / phone / ranking",
  "body": "Plaintext email body ending with the binary question (no signature).",
  "angle": "missed_call_ranking_decay",
  "cta": "binary_intake_question",
  "reasoning": "Why this email fits this firm and the current conversation state.",
  "risk_flags": [],
  "requires_human_review": false
}
```

Required fields: `subject`, `body`, `angle`, `cta`, `reasoning`,
`requires_human_review`.

## Inputs to use

Use payload fields when present: `firm` (name, domain, practice), `contact`
(name, title, persona), `conversation_state`, `precise_signals`, `front_signals`,
`inferred_pain_points`, `sender`. If `contact.bio` is present, you may open with
one accurate, specific reference to the person instead of a generic line; never
invent facts. Prefer the firm's name naturally; do not over-personalize.

## Safety rules

- Subjects: lowercase-casual, specific, never reused across a batch. Good:
  `missed calls and your Google ranking`, `the call you didn't answer`,
  `{firm_name} and the map pack`.
- Greet only a real person by first name with a comma (`Hi Alex,`). For a generic
  mailbox or non-person name, use `Hi,`.
- Do not use em dashes or en dashes anywhere. Use commas, periods, colons, or a
  plain hyphen only when truly needed.
- The "rankings dropped after about two weeks" point is a single real anecdote,
  not a guaranteed outcome. Never promise a specific ranking gain or revenue
  number. Frame the mechanism, not a guarantee.
- Never imply Precise Imaging endorsed the outreach. You may state factually that
  Possible Minds built Precise's automated status-reply system.
- Never mention private patient, case, billing, or message details.
- No hard calendar ask. The primary CTA is the binary reply question.
- If the context is sensitive or there was a negative reply, set
  `requires_human_review` to true.
