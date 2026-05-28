# Lead Gen Cybernetic Loop Implementation Sequence

Possible Minds lead generation should operate as a daily learning system, not
just an email sender. The target metric is booked qualified conversations.
Outbound email is the action surface; Resend, Zoho, Front, calendar events, and
operator labels are the feedback sensors; explicit policy is the controller.

## Current State

The codebase already has the core loop skeleton:

- lead-gen policy versions, batches, batch items, observations, and proposals
- strategy/composer template selection and batch approval
- dynamic `possible_minds_dynamic` strategy steps that call the
  `possible-minds-lead-email-composer` skill at send time
- manual approval modals for every generated outbound email, with editable
  subject/body and rationale before send
- staggered sequence starts over a configurable send window
- Resend send logging and webhook ingestion
- Zoho IMAP inbound reply ingestion
- inbound email storage and reply observations
- sequence pausing on replies and delivery risk
- operator notification modal with editable/sendable threaded reply drafts
- `/lead-gen` operator UI

The system is not complete yet because the loop is still mostly
operator-triggered, suppression is not first-class, Front is not ingested, and
learning proposals do not yet update the composer skill or become approved
policy versions.

## Implementation Order

1. **Dynamic email composer skill**
   - Treat sequence steps as objectives, not fixed copy.
   - Compose each email from firm/contact context, prior emails, replies,
     booked consult learnings, Front/Precise relationship signals, inferred
     pain points, optional blog links, and active policy.
   - Always include `https://getpossibleminds.com/consult` in the signature.
   - Every generated email must become a modal for operator approval before it
     is sent.
   - Keep deterministic software in charge of fetching context, enforcing
     gates, logging, and sending.

2. **Daily runner**
   - Add one orchestrator that can run the daily loop.
   - It should read the active policy, recommend a batch, enforce send caps,
     skip suppressions, optionally approve/start sequences, poll inbox
     feedback, and summarize the run.

3. **First-class suppression**
   - Add durable suppression records for email, contact, firm, and domain.
   - Store reason, source observation, creator, timestamps, and optional expiry.
   - Recommendation and execution must respect these records before sending.

4. **Production Resend webhook**
   - Ensure deployed webhook URL and `RESEND_WEBHOOK_SECRET` are configured.
   - Convert delivery, bounce, complaint, open, and click events into
     observations.
   - Automatically suppress bounced/complained addresses.

5. **Automated inbox polling**
   - Run Zoho polling unattended.
   - Scan unread messages frequently and recent read messages periodically.
   - Keep the ingestion idempotent and avoid marking messages seen by default.

6. **Front read-only enrichment**
   - Read only from Front; never modify, delete, archive, tag, assign, or send.
   - Ingest metadata from the highest-signal inboxes first: Records & Images,
     Scheduling & Orders, AR - Liens, AR - Case Updates, AR - Negotiations.
   - Store derived firm signals, not raw sensitive message bodies, for
     top-of-funnel scoring.

7. **Improved matching**
   - Match replies using message ids, `In-Reply-To`, `References`, quoted
     original recipient, greeting, firm domain, Front contact history, and LLM
     reasoning only when deterministic confidence is low.

8. **Observation normalizer**
   - Normalize Resend, Zoho, Front, booking, CRM, and manual feedback into one
     append-only observation shape.
   - Every observation should carry source, evidence, confidence, outcome, and
     proposed next action.

9. **Booking feedback**
   - Use existing autocaller consult bookings as a learning source immediately.
   - Then ingest Cal.com booking, cancellation, reschedule, no-show, attended,
     and qualified/not-qualified outcomes.
   - Treat booked qualified conversations as the primary success signal.

10. **Experiment assignment**
   - Assign explicit variants for subject, first line, offer angle, CTA,
     persona, sender, send time, blog-link inclusion, and composer skill
     version.
   - Every send should be attributable to a variant before learning from it.

11. **Policy and skill proposals**
    - Upgrade proposals from summaries into concrete changes: scoring weights,
      suppressions, copy doctrine, composer examples, wait times, daily caps,
      and persona targeting.

12. **Policy and skill apply flow**
    - Add review/apply APIs and UI.
    - Applying a proposal should create a new explicit policy version with
      reviewer, evidence, and diff from the previous active policy.

13. **Control dashboard**
    - Show today’s planned sends, sent/scheduled/failed counts, active batches,
      reply tasks, suppressions, booked conversations, current policy, pending
      proposals, and sensor health.

14. **Safety gates**
    - Add daily caps per sender/domain, bounce and complaint thresholds, max
      touches per firm, cooldown after replies, and no-send behavior when
      sensors are unhealthy.

15. **Gradual automation**
    - Auto-select batches and variants only after the loop is observable.
    - Keep copy, scoring, and policy changes human-approved until enough
      evidence supports low-risk automation.

## Target Architecture

```text
Front/Firm DB/Policy -> Recommend -> Approve/Auto-Approve -> Send
-> Resend/Zoho/Front/Calendar Observe -> Normalize -> Classify
-> Act Safely -> Notify Human -> Aggregate Learning
-> Propose Policy Change -> Approve -> New Policy -> Next Day
```

## Immediate Implementation Slice

Start with the two foundations that make scaling safer:

1. a skill-driven dynamic composer that replaces fixed email copy; and
2. a daily runner that can execute the existing recommend/approve/start path
   while honoring suppression, explicit gates, and composer review flags.
