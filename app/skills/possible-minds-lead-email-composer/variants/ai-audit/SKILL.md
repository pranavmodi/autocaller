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
- One concrete observation about the firm's likely operating reality.
- One question or offer.
- Primary CTA: invite them to open the AI-readiness audit.
- Do not ask for a meeting in the body.
- Do not include the consult URL, audit URL, or any other signature URL. The
  application injects the audit link and signature in code.
- Keep the body concise enough for a cold first touch.

## Safety Rules

- Never mention private patient, case, billing, or message details from Front.
- Never imply Precise Imaging endorsed the outreach.
- Never state that the audit is complete if the user still needs to answer the
  questionnaire. Use "quick read" or "AI-readiness audit," not a fabricated final
  score.
- Owner-facing copy avoids "LLM", "pipeline", "MLOps", and similar jargon.

