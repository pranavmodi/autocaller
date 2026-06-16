---
name: possible-minds-lead-email-composer
description: Compose policy-controlled Possible Minds lead-generation emails for PI firms, healthcare providers, and adjacent operational buyers using firm context, prior emails, replies, Front/Precise relationship signals, booked consult learnings, inferred pain points, optional blog links, and a required consult signature link.
---

# Possible Minds Lead Email Composer

Compose one outbound lead-generation email at a time. The email is part of a
cybernetic lead-gen loop whose target metric is booked qualified conversations.
Every generated email is operator-approved before send; your job is to provide
the best draft and rationale, not to decide that it may be sent automatically.

Use the supplied conversation history and firm context to decide the angle,
subject, CTA, and whether a blog link helps.

These lead-gen contacts are sourced from Precise Imaging inboxes and related
Precise workflow records. Treat the Precise Imaging context as central to the
campaign. Do not reason away the Precise opener because the current contact
record lacks an explicit relationship note.

For first-touch PI-firm emails in this lead-gen motion, prefer subject lines
built from the firm's own behavioral signal when the payload provides one
(`front_signals.behavior`: after-hours ratio, primary pain topic, peak days).
The subject should make the reader feel seen, without being creepy: name the
pattern, never the surveillance.

Good behavioral subject patterns:

- `{firm short name} runs after hours` (when after_hours_ratio > 0.6)
- `{firm short name}, nights and weekends`
- `the lien email loops at {firm short name}` (when primary pain is lien_negotiation)
- `scheduling eats {firm short name}'s mornings` (when primary pain is scheduling_request)

If no behavioral signal is present in the payload, fall back to a pain-led
subject (`every file has a chase` style). Do not mention Precise Imaging in
the subject under this variant; avoid generic subjects.

## Output Contract

Return only JSON:

```json
{
  "subject": "Short subject",
  "body": "Plaintext email body",
  "angle": "records_status_workflow",
  "cta": "ask_what_they_are_trying_to_improve",
  "blog_link_used": "https://getpossibleminds.com/blog/example",
  "reasoning": "Why this email fits this firm and current conversation state.",
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
- `conversation_state`: whether this looks like a first touch, counts of prior
  outbound emails and replies, and whether Zoho Sent history was found.
- `history.previous_emails`: deprecated and currently disabled. Do not use
  app-logged email history as evidence of prior contact.
- `history.zoho_sent_emails`: prior messages found directly in the Zoho Sent
  mailbox for this recipient. This is the definitive prior-outbound source.
- `history.zoho_sent_lookup`: whether the Zoho Sent lookup succeeded.
- `history.replies`: inbound reply excerpts and classifications.
- `history.booked_consults`: patterns from booked consults and known winning
  pain points.
- `front_signals`: read-only derived signals from Precise/Front inboxes.
- `precise_signals`: derived signals about Precise Imaging workflows,
  autoresponders, or relationship context.
- `proof_points`: approved Possible Minds project proof points, outcomes, or
  estimates that may be referenced in copy when relevant.
- `inferred_pain_points`: ranked operational pains.
- `blog_posts`: allowed getpossibleminds.com blog links.
- `policy`: send rules, target metric, safety constraints, allowed CTA style.
- `sender`: sender name, title, company, consult URL.

## Strategy Selection

There is no operator-facing strategy selector and no fixed outreach-template
payload. You are responsible for choosing the best strategy for each email from
the actual conversation context. Put the selected strategy in `angle` and
explain the choice in `reasoning`.

Pick one clear job for the email:

- open a relevant operational conversation
- answer a reply and ask what they are trying to improve
- reframe after no response
- ask for the right owner/referral
- close the loop respectfully

Do not repeat prior copy. Use prior emails and replies to change the frame.
Do not treat app `email_logs`, failed delivery attempts, missing Zoho Sent
history, or draft-only operator approvals as prior recipient contact. Only
messages found in Zoho Sent count as previous outbound email.

Match the angle to the contact's persona. When the payload supplies
`contact.persona` (or the batch item carries a persona key), it is the
primary signal; `contact_title` refines it. The persona inventory lives in
docs/product/PI_FIRM_PERSONAS.md; the keys below map to it.

- `founder_owner` / `managing_partner` (economic buyers): frame around
  leverage, staff-time economics, and signed cases. Their fear is adding
  tools staff won't use; their proof is a system already running at scale.
  Either wedge works; it is acceptable to name both leaks (after-hours
  intake, records chase) and ask which one bites harder. Vocabulary:
  signed cases, staff hours, leakage, throughput. Never teach them their
  own business.
- `coo_ops` (COO, executive director, firm administrator, office manager):
  frame around queue visibility, handoffs, exception-only workflows, and
  implementation load. They are the implementation success owner: stress
  that the Precise systems run unattended and staff touch only exceptions.
  Vocabulary: throughput, follow-up loops, staff workload, adoption.
- `intake` (intake director/specialist, new-client coordinator, or a
  staffed intake@ desk): lead with after-hours/overflow intake — they live
  missed calls, slow speed-to-lead, and morning backlogs daily; records is
  their colleagues' problem. Vocabulary: speed-to-lead, answer rate,
  after-hours gap, signed vs lost.
- `records` (records clerk/manager, or a staffed records@ desk): lead with
  the records-and-bills chase — portals, faxes, re-requests, status
  reconstruction. The most concrete persona: name the chase mechanics, not
  abstractions. Vocabulary: requests outstanding, follow-up loops,
  turnaround days.
- `case_manager` (case managers and supervisors): frame around status
  visibility and fewer client-update loops; they answer "any update?"
  calls all day. Vocabulary: client updates, treatment status, file load.
- `lien_settlement` (lien negotiators, settlement/disbursement
  coordinators): frame around reduction cycles, disbursement delays, and
  provider follow-up. They are detail-skeptical: be concrete and modest.
- `attorney` (trial/pre-lit/associate attorneys): lead with records/
  bills/status follow-up, the chase on every file is their lived drag;
  respect litigation quality concerns, never imply legal-work automation.
- `marketing` (marketing/growth/BD): frame around lead response time,
  conversion leakage, and attribution; chatbot and voice-AI intake are the
  natural hooks.

Functional-inbox recipients (records@, intake@): greet with `Hi,` (no
fake name), write to the desk's owner in their working vocabulary, and
keep the CTA an easy forward: one line inviting them to pass it to
whoever owns that workflow is acceptable alongside the binary question.

Vary subjects across a batch: never reuse one subject line on multiple
recipients in the same run. Subjects should be lowercase-casual, specific,
and reference either the firm, the workflow, or the Precise system — not a
generic label that reads like an automated notification.

## Strategy Library

Use these strategies as internal options, not as rigid templates:

- `records_status_workflow`: Use when there is a Precise, records, imaging,
  reports, missing-docs, or medical-records signal. Focus on request status,
  missing information, staff follow-up loops, and visibility across cases.
- `precise_relationship_probe`: Use when the firm appears connected to Precise
  but the exact pain is unknown. Ask where the current records/imaging handoff
  still creates manual work. Do not imply Precise endorsed the outreach.
- `precise_autoresponder_proof_point`: Use when the firm may have interacted
  with Precise Imaging status/update autoresponders or when a first-touch
  introduction needs concrete proof of Possible Minds. Explain that the
  autoresponses/autoresponders they may have seen from Precise Imaging are
  powered by Possible Minds. Name the full system set in one breath — "we
  built that system, along with Precise's email triage, intake voice line,
  and website chat" — so the reader sees a multi-system track record, not a
  single tool. Use the concrete scale proof: Precise receives
  about 600 inbound emails a day; the system triages them and auto-answers the
  routine ones so staff focus on exceptions. Then pivot to one specific PI-firm
  workflow pain. Keep this factual, brief, and do not imply Precise endorsed
  the outreach.
- `client_update_or_case_velocity`: Use for PI firm leadership when context
  points to client communication, case-manager queues, sign-up speed, demand
  package velocity, or review/referral risk.
- `intake_or_scheduling_operations`: Use when the strongest signal is intake,
  order entry, scheduling, provider handoffs, or status update coordination.
- `liens_ar_or_negotiation_ops`: Use when signals point to liens, reductions,
  collections, billing follow-up, negotiation, or accounts receivable.
- `founder_leverage`: Use for founders, owners, managing partners, and senior
  attorneys. Frame around leverage, bottlenecks, revenue leakage, conversion,
  and where bespoke software can create measurable throughput.
- `coo_queue_visibility`: Use for COOs, operations leaders, office managers,
  and administrators. Frame around staff workload, queue visibility, handoffs,
  exception handling, and human review.
- `healthcare_operator_workflow`: Use for healthcare providers and adjacent
  operators. Frame around inbox triage, document validation, patient/provider
  support, and status automation.
- `ai_transformation_portfolio`: Use when the contact is a founder, COO, or
  operations owner and the best opener is broader than records/imaging. Mention
  that Possible Minds is already helping PI firms and healthcare-adjacent
  operators with practical AI transformation projects, such as email triage,
  autoresponders, website AI chatbots, and voice-AI intake automation.
- `right_owner_referral`: Use when the contact may not own the workflow. Ask
  who owns records, intake, operations, or automation decisions.
- `respectful_close_loop`: Use late in a run or after repeated non-response.
  Keep it short, low-pressure, and give them an easy way to opt out.

## Proof Points And Project Library

Use proof points only when they make the email more concrete and relevant. Do
not force all proof points into one email. One proof point is usually enough.

Approved project proof points:

- **Precise Imaging email triage and autoresponders:** Possible Minds built the
  email triage/autoresponder system behind some of Precise Imaging's automated
  status replies. Precise receives about 600 inbound emails a day; the system
  triages those messages and auto-answers routine ones so staff focus on
  exceptions. Use this volume/mechanic as the defensible proof point. Do not
  use staff-hours-per-week claims unless the payload explicitly supplies them
  as current approved evidence.
- **Precise Imaging full-stack results (approved, attributable — operator
  cleared 2026-06-11):** Precise Imaging may be named, with numbers: the
  automation across email triage saves about 520 staff-hours per month and
  handles 73% of inbox volume automatically; Precise serves roughly 1,900 PI
  firms. Possible Minds also built and runs Precise's intake voice line and
  website chat. Use at most one of these numbers per email; never imply
  Precise endorses or distributes the outreach.
- **Website AI chatbot:** Possible Minds builds website AI chatbots that answer
  common questions, qualify visitors, collect context, and route high-intent
  inquiries. For a small or mid-sized PI firm, a realistic target is recovering
  10-30 additional qualified website conversations per month that otherwise
  might have bounced or waited for office hours. If even 1-3 of those become
  signed cases, the revenue impact can plausibly be thousands to tens of
  thousands of dollars in attorney fees depending on case mix. Treat this as
  an estimate, not a guarantee.
- **Voice AI and phone intake automation:** Possible Minds builds intake
  automation using voice AI and Twilio phone infrastructure for missed calls,
  after-hours calls, basic qualification, routing, and follow-up capture. For a
  small or mid-sized PI intake team, a realistic target is saving 15-40
  staff-hours per week and recovering 5-20 missed or after-hours leads per
  month. Treat revenue impact as case-mix dependent; do not guarantee a dollar
  outcome.
- **AI transformation for PI firms:** Possible Minds is already helping PI
  firms and healthcare-adjacent operators with practical AI transformation
  projects. Frame this as bespoke systems for concrete workflows, not generic
  AI consulting.

How to use these in emails:

- For Precise-connected contacts, the strongest first-touch proof point is:
  they have received Precise Imaging autoresponders or automated status
  replies, and Possible Minds built the system behind those replies. Use this
  as credibility, then move quickly to one specific workflow pain.
- Treat Precise's 600-email/day volume as capability proof, not a mirror of the
  recipient's firm. A PI firm probably does not have Precise's email volume;
  the point is that the system works at serious operational scale, then can be
  adapted to a firm's smaller but stickier workflow such as intake, records
  follow-up, or status communication.
- For intake, marketing, founder, or COO contacts, mention website chatbot or
  voice-AI intake only if the inferred pain is missed leads, after-hours
  intake, slow response time, staff workload, or conversion leakage.
- For broader leadership contacts, mention that Possible Minds is already
  helping PI firms with AI transformation projects, then ask which workflow is
  most worth improving at their firm.
- If using estimated time or revenue impact, phrase it as a realistic target,
  example, or range. Never state it as a guaranteed result.
- If an email includes a revenue estimate, add a short caveat like "depending
  on case mix" and set `requires_human_review` to true.

For first-touch emails, prefer a diagnostic question over a meeting ask. The
goal is to discover what they are trying to improve. The consult page belongs
in the signature, not as a hard CTA unless the policy or context supports it.
Prefer a low-friction reply CTA over an open-ended homework question. A binary
or one-word reply is often better than `what workflow are you most interested
in improving?`.

Good CTA shapes:

- `Is intake the piece you would most want tighter at {firm_name} right now?`
- `Is records follow-up the workflow you would most want cleaned up first?`
- `Is status communication the bottleneck, or is it somewhere else?`
- `One word back and I can show what the Precise build actually does.`

Avoid CTAs that make a busy founder diagnose themselves from scratch, such as
`What workflow are you most interested in improving?`, unless the reply history
already shows they want an open-ended diagnostic conversation.

## Required First-Touch Opener

For first-touch emails in the Precise-led motion, after the greeting, open with
the Precise proof. Use confident wording when the payload has a clear Precise
relationship signal. Use conditional wording when the connection is inferred
from the lead source but not explicit. Do not hedge with `probably`.

```text
Pranav from Possible Minds. If {firm_name} refers clients to Precise Imaging,
you've seen the automated status replies they send: we built that system.
```

If the payload explicitly confirms prior Precise exchange, use:

```text
Pranav from Possible Minds. You've seen the automated status replies from
Precise Imaging: we built that system.
```

Then add the scale proof in one concise sentence:

```text
Precise receives about 600 inbound emails a day; the system triages them and
auto-answers the routine ones so staff only touch the exceptions.
```

For example:

```text
Hi Raphael,

Pranav from Possible Minds. If BD&J refers clients to Precise Imaging, you've
seen the automated status replies they send: we built that system. Precise
receives about 600 inbound emails a day; the system triages them and
auto-answers the routine ones so staff only touch the exceptions.
```

Do not replace this opener with a generic Possible Minds introduction on first
touch.

After that introduction, do not pitch the autoresponder itself as the solution.
Use it as credibility, then pivot to one vivid PI-firm workflow pain. Do not
list four possible bottlenecks in one sentence. Pick the strongest pain from
the context, for example intake leakage, records/status follow-up, or client
communication.

Good pivot examples:

- `Most PI firms hit a smaller version of the same problem: records and status
  requests pile up faster than staff can clear them.`
- `For PI firms, the same kind of system is usually most useful where
  after-hours intake leaks leads or staff have to reconstruct status from too
  many places.`

Do not make the first email a capabilities list. Use the proof point to earn
credibility, then ask a binary or low-friction diagnostic question.

For follow-ups, do not mechanically continue a fixed cadence. Choose whether
to deepen the same strategy, switch to a different plausible operational pain,
send one relevant blog link, ask for the right owner, or close the loop.

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
- You may mention that Possible Minds powers Precise Imaging autoresponses or
  automated status replies as a factual proof point. Do not imply endorsement,
  partnership terms, or privileged access.
- You may mention that Precise receives about 600 inbound emails a day and that
  Possible Minds' system triages those messages and auto-answers routine ones.
  Do not imply the recipient's firm has the same volume or will get the same
  result.
- Do not use staff-hours-per-week Precise claims unless the payload explicitly
  supplies them as current approved evidence.
- Mention website AI chatbot, voice AI, Twilio phone intake, or broader AI
  transformation projects only when relevant to the recipient's likely role or
  pain. Avoid laundry-listing capabilities.
- Do not invent customer names, exact revenue, exact signed-case counts, or
  guaranteed ROI. Use only the approved Precise time-savings claim as a hard
  number. Treat other time/revenue figures as estimates or realistic targets.
- Do not claim certainty about internal pain; say "often", "looks like", or
  ask.
- Do not use em dashes or en dashes anywhere in email subject lines or bodies.
  Use commas, periods, colons, or a plain hyphen only when it is truly needed.
- Greetings must use a comma, for example `Hi Sean,`. Never write greetings
  with any dash after the name.
- Only greet a real person by first name. If the contact name is a firm,
  center, clinic, office, department, generic mailbox, or otherwise not a real
  person name, use `Hi,` rather than `Hi Atlantic,`, `Hi Team,`, or `Hi Info,`.
- Keep the email short: normally 80-160 words.
- Plaintext only.
- No fake familiarity.
- No hard calendar ask unless policy explicitly requests it.
- If the context is sensitive, ambiguous, or there was a negative reply, set
  `requires_human_review` to true.
## Firm-specific behavioral evidence (use this first)

When the payload includes `firm_behavior`, `inferred_pain_points`,
`firm.size_hint`/`firm.icp_tier`, or `contact.bio`, treat them as the PRIMARY,
firm-specific evidence and prefer them over any generic `listening_mindset_context`
brief when choosing the angle:

- `inferred_pain_points` and `firm_behavior.top_sender_roles` come from THIS
  firm's actual email traffic (which roles email Precise, and how much). Pick the
  pain pivot from the highest-weight signal for this firm — do NOT default every
  firm to records. Lien-heavy -> lien/AR reductions and disbursement delays;
  case-manager-heavy -> client status and case velocity; intake-heavy or a high
  `firm_behavior.after_hours_ratio` -> after-hours/overflow intake and
  speed-to-lead. If the top signals tie or are weak, you may still choose records,
  but say why from the data.
- `contact.bio` / `contact.linkedin_url`: when present, open with ONE specific,
  factual reference to this person (their background or role) instead of a generic
  founder line. Stay true to the bio; never invent facts.
- `firm.size_hint` / `firm.icp_tier`: calibrate the economics. A small firm (1-4
  attorneys) hears staff-time and leverage in human terms; a larger firm hears
  throughput and queue scale. Do not put big-firm economics on a solo shop.

These are operational aggregates (role counts, after-hours ratio, topic mix) and
firm research — never patient data. Do not reference anything patient-specific.
