# Lead-Gen Email Agent Goal

Objective:
Build the next horizontal slice of the Possible OS lead-generation email agent.

The slice should prove this loop:
select qualified contacts from the contacts database
-> research missing founder/leader email or context
-> compose outreach with the existing Possible Minds email composer skill
-> create approval-ready drafts
-> send only approved outreach through durable send_email mode=lead_gen
-> record actions/traces so heartbeat can observe outcomes

Context:
Possible OS already has contacts, lead-gen workflows, email composer skills, Zoho sending, durable actions, heartbeat context, traces, and capability registry. The next milestone is to make the agent able to use these pieces together reliably for lead generation.

Scope:
Build the smallest complete end-to-end slice.

V1 should:
- select 3 qualified contacts only;
- only target founders, managing partners, partners, COO, operations leaders, or equivalent senior operators;
- research missing or weak email/context only when needed;
- compose drafts through the existing email composer skill;
- show drafts for operator approval;
- add durable send_email mode=lead_gen policy/execution support;
- policy-check at least one lead_gen action without sending;
- ensure heartbeat can observe the created actions/outcomes.

Out of scope:
- Do not build a fully autonomous daily sender yet.
- Do not auto-send outreach without explicit operator approval.
- Do not rewrite the entire lead-gen system.
- Do not edit soul.md.
- Do not use arbitrary shell commands to send email.

Implementation requirements:
1. Inspect existing lead-gen, contacts, composer, action execution, heartbeat, and traces code.
2. Reuse existing DB models/API/UI patterns where possible.
3. Add or adapt contact selection for this agent-driven slice.
4. Add bounded research output for weak contacts:
   - person
   - role
   - email if found
   - email confidence
   - source URLs
   - evidence summary
   - remaining uncertainty
5. Build a composer context packet containing:
   - firm/contact data
   - role/persona
   - lead source
   - prior Zoho sent history
   - inbound replies if any
   - research evidence
   - inferred pain points
   - relevant Possible Minds proof points
   - relevant getpossibleminds.com links if useful
   - required consult signature/link
   - no em dash rule
   - composer skill path/version/hash if available
6. Use the existing Possible Minds email composer skill to generate:
   - subject
   - body
   - rationale
   - selected angle
   - CTA
   - risks/assumptions
   - why this contact was selected
7. Extend durable action execution with send_email mode=lead_gen.
8. Add CLI/API parity for any new backend capability.
9. Keep the operator able to inspect selected contacts, research evidence, drafts, approvals, policy checks, and action results.

Safety and approval:
No outreach email may be sent without explicit operator approval.

send_email mode=lead_gen policy must verify:
- exact approved recipient;
- exact approved subject/body hashes;
- valid recipient;
- not suppressed;
- no recent duplicate outreach;
- daily/send-window constraints where available;
- configured email transport;
- required consult link/signature.

Use typed durable actions, policy checks, and narrow executors. Do not let an LLM execute arbitrary shell commands for sending.

Validation:
Run relevant backend tests.
Run frontend type/build checks if UI changes.
Run a no-send dry run that selects 3 contacts and creates approval-ready drafts.
Policy-check at least one send_email mode=lead_gen action without sending.
Verify heartbeat context can see the resulting lead-gen actions/outcomes.

Docs:
Update docs/cli.md for new commands.
Update relevant design docs.
Update the autocaller skill docs.
Keep soul.md protected.

Done when:
- 3 qualified decision-maker contacts can be selected from the DB.
- Missing/weak contact context can be researched with evidence.
- Drafts are generated through the composer skill with rationale.
- Drafts are visible for operator approval.
- send_email mode=lead_gen exists and policy-checks approved content.
- No unapproved email is sent.
- CLI/API can inspect created actions.
- Heartbeat can observe recent lead-gen actions/outcomes.
- Docs and skills are updated.
- Tests/build checks pass.
- Changes are left uncommitted for operator review.

Pause if:
- A real email would be sent without explicit operator approval.
- Required credentials are missing.
- Existing lead-gen architecture contradicts this design.
- A schema migration is needed and cannot be safely validated.
- The smallest working slice starts expanding into a large autonomous rebuild.
