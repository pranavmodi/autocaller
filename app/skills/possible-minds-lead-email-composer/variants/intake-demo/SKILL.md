---
name: possible-minds-lead-email-composer-intake-demo
description: Compose a minimal first-touch Possible Minds lead-gen email for PI firm founders offering the browser after-hours intake demo as the primary artifact. Signature and tracked demo link are appended by code.
---

# Possible Minds Lead Email Composer - Browser Intake Demo Variant

Compose one short outbound first-touch email for a personal-injury firm founder,
owner, managing partner, or operations leader. The email's job is to earn a
click into the live browser intake demo, not to explain the whole product.

The sending system appends the consult signature and a per-recipient tracked
intake-demo link. Do not include any URL yourself.

## Core Offer

The reader can hear a sample after-hours PI intake call in the browser and see
the intake summary their team would receive afterward.

This is stronger than a generic "AI receptionist" pitch. The artifact is the
demo itself: press the button, play the caller, judge the professionalism.

## Body Shape

1. Greet the contact naturally.
2. Introduce Pranav from Possible Minds in one sentence.
3. Say you built a browser demo of after-hours PI intake.
4. Make the time cost tiny: about two minutes.
5. Use one plain CTA sentence that points to trying the demo.

Keep the body roughly 55-100 words. Plaintext only.

Do not mention Telnyx, OpenAI, LLMs, admin pages, APIs, transcripts as a
technical feature, or internal implementation details. You may mention the
summary artifact in business terms.

## Good Copy Shape

```text
Hi Alex,

Pranav from Possible Minds.

I built a browser demo of an after-hours PI intake call. No setup or phone call:
you can play the potential client and see the review summary your team would
receive afterward.

It takes about two minutes.
```

The application will append the sign-off and tracked demo link.

## Output Contract

Return only JSON:

```json
{
  "subject": "short, lowercase-casual subject about after-hours intake",
  "body": "Plaintext email body ending before signature and before any URL.",
  "angle": "browser_intake_demo",
  "cta": "try_demo_click",
  "reasoning": "Why this email fits this firm and the current conversation state.",
  "risk_flags": [],
  "requires_human_review": false
}
```

Required fields: `subject`, `body`, `angle`, `cta`, `reasoning`,
`requires_human_review`.

## Inputs To Use

Use payload fields when present: `firm` (name, domain, practice), `contact`
(name, title, persona), `conversation_state`, `precise_signals`,
`front_signals`, `inferred_pain_points`, and `sender`.

Use the firm name sparingly. Do not over-personalize. If the payload does not
support a specific claim, leave it out.

## Safety Rules

- Subjects: lowercase-casual, specific, never hypey. Good: `after-hours intake`,
  `sample intake call`, `{firm_name} after hours`.
- Greet only a real person by first name with a comma (`Hi Alex,`). For a
  generic mailbox or non-person name, use `Hi,`.
- Do not claim the demo is configured to the firm unless context explicitly says
  it is. "For {firm_name}" is allowed only when the recipient firm name is known.
- Do not promise signed cases, ranking gains, response-time improvements, or
  legal/compliance outcomes.
- Do not use em dashes or en dashes. Use periods, commas, and colons.
- No hard calendar ask in the body. The demo click is the primary CTA.
- If there was a negative reply or sensitive context, set
  `requires_human_review` to true.
