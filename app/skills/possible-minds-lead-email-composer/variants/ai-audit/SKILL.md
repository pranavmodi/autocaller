---
name: possible-minds-lead-email-composer-ai-audit
description: Compose a policy-controlled Possible Minds lead-generation email that offers the AI-readiness audit as the primary CTA. Signature and audit URLs are appended by code.
---

# Possible Minds Lead Email Composer - AI Audit Variant

Compose one outbound lead-generation email. The email is part of a cybernetic
lead-gen loop whose target metric is booked qualified conversations. Every draft
is operator-approved before send.

## Variant Goal

Lead with a concrete observation about the firm, then offer the AI-readiness
audit as the single primary CTA. The email should feel like a diagnostic, not a
demo pitch.

Use this outbound angle from the AI Audit UX spec:

Most firms that buy AI tools never see results because the firm was not set up
to benefit. Offer a quick read on where the firm stands and the three things
that would have to be true first. No demo, just the diagnosis.

## Required First-Touch Opener (Precise proof)

These contacts are sourced from Precise Imaging inboxes and related Precise
workflow records, so the AI-audit email is part of the Precise-led motion. On a
first touch, after the greeting, open with the Precise proof for credibility,
then pivot to the AI-readiness audit. Do not replace this with a generic
Possible Minds introduction, and do not reason the opener away because the
contact record lacks an explicit relationship note.

Use confident wording when the payload has a clear Precise relationship signal;
use conditional wording when the connection is inferred from the lead source but
not explicit. Do not hedge with "probably".

Inferred connection:

```text
Pranav from Possible Minds. If {firm_name} refers clients to Precise Imaging,
you've seen the automated status replies they send: we built that system.
```

Explicitly confirmed prior Precise exchange:

```text
Pranav from Possible Minds. You've seen the automated status replies from
Precise Imaging: we built that system.
```

Then add the scale proof in one concise sentence:

```text
Precise receives about 600 inbound emails a day; the system triages them and
auto-answers the routine ones so staff only touch the exceptions.
```

Do not pitch the autoresponder as the solution. Use it only as credibility, then
pivot in the next line to the AI-readiness framing (most firms that buy AI never
see results because the firm was not set up to benefit; you put together a quick
read on where a firm like theirs stands and the three things that would have to
be true first), and close with the audit as the single CTA. The code injects the
audit link; do not write any URL.

For follow-ups (not first touch), you may skip the full Precise opener if prior
emails already established it; keep the audit as the primary CTA.

Example first-touch shape:

```text
Hi Marcus,

Pranav from Possible Minds. If Harbor & Vance refers clients to Precise Imaging,
you've seen the automated status replies they send: we built that system. Precise
receives about 600 inbound emails a day; the system triages them and auto-answers
the routine ones so staff only touch the exceptions.

Most firms that buy AI never see results because the firm was not set up to
benefit. I put together a quick read on where a firm like yours stands and the
three things that would have to be true first. No demo, just the diagnosis.
```

## Output Contract

Return only JSON:

```json
{
  "subject": "Short subject",
  "body": "Plaintext email body",
  "angle": "ai_readiness_audit",
  "cta": "take_ai_readiness_audit",
  "blog_link_used": null,
  "reasoning": "Why this email fits this firm and current conversation state.",
  "risk_flags": [],
  "requires_human_review": false
}
```

Required fields: `subject`, `body`, `angle`, `cta`, `reasoning`,
`requires_human_review`.

## Inputs To Use

- `firm`: name, domain, size, practice/domain, known relationship signals.
- `contact`: name, title, email, inferred persona.
- `conversation_state`: whether this is a first touch or follow-up context.
- `front_signals`, `firm_behavior`, `review_evidence`, `inferred_pain_points`,
  `competitive_context`, and `selection_evidence`: use these only as safe,
  high-level operational context. Never mention private message details.
- `sender`: sender name, title, and company.

## Email Shape

- Plaintext only.
- On first touch, lead with the Precise proof opener above, then pivot.
- One concrete observation about the firm's likely operating reality.
- End the body on the diagnosis framing (the "quick read / three things that
  would have to be true first" line). Do NOT write your own audit
  call-to-action, closing question, or link prompt such as "Worth taking the
  AI-readiness audit?", "Want the quick read?", or "Take the audit here" — the
  application appends the audit CTA and link as the final line, so any audit
  CTA you write just duplicates it.
- Do not ask for a meeting in the body.
- Do not include the consult URL, audit URL, or any other signature URL. The
  application injects the audit link and signature in code.
- Keep the body concise enough for a cold first touch.

## Safety Rules

- Never mention private patient, case, billing, or message details from Front.
- Never imply Precise Imaging endorsed the outreach, partnered on terms, or gave
  privileged access. The Precise proof is factual credibility only.
- You may state that Possible Minds built the system behind Precise Imaging's
  automated status replies and that Precise receives about 600 inbound emails a
  day that the system triages. Do not imply the recipient's firm has the same
  volume or will get the same result.
- Do not use staff-hours-per-week Precise claims unless the payload explicitly
  supplies them as current approved evidence.
- Never state that the audit is complete if the user still needs to answer the
  questionnaire. Use "quick read" or "AI-readiness audit," not a fabricated final
  score.
- Owner-facing copy avoids "LLM", "pipeline", "MLOps", and similar jargon.

