---
name: possible-minds-lead-email-composer-gatekeeper-routing
description: Compose short Possible Minds lead-gen emails for non-decision-maker and gatekeeper contacts. Use Precise Imaging proof, ask for the right owner, and request a direct email and phone number instead of pitching a demo.
---

# Possible Minds Lead Email Composer - Gatekeeper Routing Variant

Compose one short outbound first-touch email for a non-founder,
non-decision-maker, or gatekeeper contact at a PI firm, medical provider, lien
operation, records team, intake team, or adjacent workflow partner.

The email's job is not to sell the product. The job is to get routed to the
right person with a direct email and phone number.

## Core Strategy

Open with the same concrete credibility used in the founder variants:

```text
Pranav from Possible Minds. We work with Precise Imaging on the tech side: the
automated imaging-status replies your team may have seen are ours, along with
Precise's email triage, intake voice line, and website chat.
```

Then make a clean routing ask:

- Ask who owns after-hours intake, intake follow-up, records/status follow-up,
  website chat, or vendor coordination.
- Ask for the right person's direct email and phone number.
- Keep the note polite, specific, and easy to forward.
- Do not include a demo link, calendar link, consult CTA, or product pitch in
  the body.
- Do not ask a gatekeeper to evaluate the browser demo.

For contacts with intake, records, case management, liens, scheduling,
front-desk, coordinator, assistant, or office-administration titles, assume
they may know the right owner but may not be the buyer.

## Body Shape

1. Greet the contact naturally.
2. Introduce Pranav and Possible Minds with the Precise Imaging proof.
3. Say you are trying to reach the person who owns the relevant workflow.
4. Ask whether they can point you to the right person, including direct email
   and phone number if they have it.
5. Sign off simply.

Keep the body roughly 70-110 words. Plaintext only.

## Good Copy Shape

```text
Hi Maria,

Pranav from Possible Minds. We work with Precise Imaging on the tech side: the
automated imaging-status replies your team may have seen are ours, along with
Precise's email triage, intake voice line, and website chat.

I am trying to reach the person at Acme Law who owns after-hours intake and
client follow-up.

Is that you, or someone else? If there is a better person, could you send me
their direct email and phone number?

Thanks,
Pranav
```

## Subject Guidance

Use a low-friction routing subject. Prefer:

- `who owns intake?`
- `right person for intake?`
- `Precise Imaging workflow question`
- `routing question`
- `quick routing question`

Do not use hype, pain-heavy, or founder-style subjects such as `missed cases
after hours`.

## Output Contract

Return only JSON:

```json
{
  "subject": "short routing subject",
  "body": "Plaintext email body",
  "angle": "gatekeeper_routing",
  "cta": "ask_for_right_owner_email_and_phone",
  "reasoning": "Why this routing email fits the contact and firm.",
  "risk_flags": [],
  "requires_human_review": false
}
```

Required fields: `subject`, `body`, `angle`, `cta`, `reasoning`,
`requires_human_review`.

## Inputs To Use

Use payload fields when present:

- `firm`: name, domain, practice/domain, known relationship signals.
- `contact`: name, title, email, inferred persona.
- `conversation_state`: prior outbound and reply context.
- `precise_signals`, `front_signals`, and `inferred_pain_points`.
- `sender`: sender name, title, company, consult URL.

If the contact name appears to be a firm name, department name, generic mailbox,
or non-person, use `Hi,` instead of a first-name greeting.

## Safety Rules

- Do not imply Precise Imaging endorsed the outreach.
- Do not claim a confirmed relationship unless the payload explicitly supports
  it. Use "may have seen" when relationship evidence is weak.
- Do not include URLs in the body.
- Do not mention Telnyx, OpenAI, LLMs, admin pages, APIs, transcripts, or
  internal implementation details.
- Do not ask for a meeting.
- Do not use em dashes or en dashes. Use periods, commas, and colons.
- If there was a negative reply, opt-out signal, or sensitive context, set
  `requires_human_review` to true.
