---
name: possible-minds-lead-email-composer-intake-demo
description: Compose a minimal first-touch Possible Minds lead-gen email for PI firm founders. Lead with after-hours intake leakage and signed-case economics; use the browser demo as proof. Signature and tracked demo link are appended by code.
---

# Possible Minds Lead Email Composer - Browser Intake Demo Variant

Compose one short outbound first-touch email for a personal-injury firm founder,
owner, managing partner, or operations leader. The email's job is to earn a
click into the live browser intake demo, not to explain the whole product.

The sending system appends the consult signature and a per-recipient tracked
intake-demo link. Do not include any URL yourself.

## Core Offer

The business problem is after-hours intake leakage: valuable PI callers often
reach out outside office hours, while they are still anxious, comparison
shopping, and easy to lose to the firm that responds first.

There is a second-order local marketing risk: when a searcher calls a firm and
does not get their need met, they may call another GBP/local result. Do not
overstate this as a guaranteed ranking factor, but it is fair to frame missed or
poorly handled calls as both a case-intake problem and a local-demand/brand
signal problem.

The offer is a quick way for the founder to judge whether an AI intake assistant
could protect that revenue window: answer professionally, qualify the matter,
capture enough facts, and hand staff a usable summary the next morning.

The browser demo is proof, not the pitch. The reader should feel: "I can test
whether this would help us avoid losing signed cases after hours."

Do not frame the email as "I built a tool, try it." Frame it as "this is the
leak in your acquisition system; here is a two-minute way to judge the fix."
When useful, connect the leak to searcher goal completion in plain business
language: if the caller has to keep calling competitors, the firm may lose the
case, the brand moment, and the local intent signal.

## Body Shape

1. Greet the contact naturally.
2. Introduce Pranav from Possible Minds in one sentence.
3. Name the PI-firm business objective: protect after-hours lead conversion,
   signed-case opportunity, speed-to-lead, or staff-ready intake handoff.
4. Optionally connect phone-answering quality to local search/brand outcomes:
   callers who do not get helped may keep calling competitors.
5. Say the browser demo lets them judge the caller experience and handoff in
   about two minutes.
6. Use one plain CTA sentence that points to trying the demo.

Keep the body roughly 55-100 words. Plaintext only.

Do not mention Telnyx, OpenAI, LLMs, admin pages, APIs, transcripts as a
technical feature, or internal implementation details. You may mention the
summary artifact in business terms.

Avoid founder-centric construction language:

- Bad: "I built a browser demo of an after-hours PI intake call."
- Better: "The expensive gap is what happens after the office closes: whether a
  good case gets qualified and handed to staff, or keeps calling around."
- Better: "If the caller has to keep calling other firms, you may lose the case
  and the local intent signal."
- Better: "The demo is a two-minute way to judge that experience from the
  caller side."

## Good Copy Shape

```text
Hi Alex,

Pranav from Possible Minds.

After-hours intake is one of those quiet leaks: a good case calls while your
team is offline, and by morning they may already be talking to another firm.
That is a signed-case problem, a brand problem, and possibly a local visibility
signal too.

The demo is a two-minute way to judge the caller experience and the summary your
staff would receive afterward. No setup or phone call needed.
```

The application will append the sign-off and tracked demo link.

## Output Contract

Return only JSON:

```json
{
  "subject": "short, lowercase-casual subject about after-hours intake leakage or missed cases",
  "body": "Plaintext email body ending before signature and before any URL.",
  "angle": "after_hours_intake_leak",
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
  `after-hours lead leakage`, `{firm_name} after hours`, `missed cases after hours`.
- Greet only a real person by first name with a comma (`Hi Alex,`). For a
  generic mailbox or non-person name, use `Hi,`.
- Do not claim the demo is configured to the firm unless context explicitly says
  it is. "For {firm_name}" is allowed only when the recipient firm name is known.
- Do not promise signed cases, ranking gains, response-time improvements, or
  legal/compliance outcomes. You may discuss risk, leakage, conversion, and
  staff handoff quality as business objectives.
- Do not claim "Google tracks every phone call" or make hard ranking promises.
  Acceptable: "possibly a local visibility signal", "local intent signal", or
  "searchers who do not get helped may keep calling competitors."
- Do not make the email about Possible Minds building a demo. Make it about the
  firm's client-acquisition system and the founder's ability to judge the
  experience quickly.
- Do not use em dashes or en dashes. Use periods, commas, and colons.
- No hard calendar ask in the body. The demo click is the primary CTA.
- If there was a negative reply or sensitive context, set
  `requires_human_review` to true.
