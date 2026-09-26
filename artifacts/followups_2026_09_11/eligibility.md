# Follow-up Eligibility Handoff

**Evidence timestamp:** 2026-09-11T07:50:00Z  
**Scope:** broader Possible Minds outreach  
**Mode:** read-only; no drafts, actions, approvals, or schedules created

## Top five provisional candidates

| Rank | Contact | Firm / role | Last outbound | Prior touch | Hook | RFC state |
|---:|---|---|---|---:|---|---|
| 1 | Khail A. Parris, `khail@parris.com` | PARRIS / Partner | 2026-07-23 | 1 delivered | Yelp complaint: ignored after signing | Pending Zoho lookup; Resend provider `43f0b66a-6c7a-42c5-9a37-7bd51e62405a` returned 404 |
| 2 | Matthew M. Taylor, `matt.taylor@dklaw.com` | DK Law / Senior Partner, Director of Litigation | 2026-08-10 | 1 delivered | Yelp complaint: callback delay for weeks | Pending Zoho lookup; Resend provider `8b221b79-bef9-4be6-a7f8-d3001f09f21f` returned 404 |
| 3 | Brandi Kurlander, `bkurlander@bkhclaw.com` | Bender Kurlander Hernandez & Campbell / Founding Member & Partner | 2026-08-10 | 1 delivered | Yelp complaint: response taking three months | Pending Zoho lookup; Resend provider `504cc8c4-c0d2-40c9-a165-4a74c86ff837` returned 404 |
| 4 | Brisa Andrade, `brisaa@lyfe.com` | Lyfe Law / Partner, Pre-Litigation Manager | 2026-08-13 | 1 delivered | Lead Docket to Filevine attribution gap | Pending Zoho lookup; Resend provider `7b9c36e4-c059-41da-9d5a-91c6e162eb50` returned 404 |
| 5 | Christopher V. Bulone, `christopher@dordicklaw.com` | Dordick Law Corporation / Partner | 2026-08-13 | 1 delivered | Lead-to-signed-case attribution gap | Pending Zoho lookup; Resend provider `5ea51cc2-5f9c-48dd-9f40-f60a4b130392` returned 404 |

All five have no stored inbound message from the exact recipient address, no recorded bounce/failure, and no approved, waiting, queued, running, or scheduled action matching the recipient in the live CLI checks. The first prior touch for each was delivered; this is eligibility evidence, not proof the message was read.

## Original message context

- **Khail Parris:** subject `Jonathan L. submitted a Yelp review about PARRIS`; cited a review saying the writer was ignored after signing an offer, then described Precise Imaging's triage of unowned messages and aging follow-ups.
- **Matthew Taylor:** subject `Ariel W. submitted a Yelp review about DK Law`; cited a weeks-long callback complaint, then described routing routine messages and flagging unresolved requests.
- **Brandi Kurlander:** subject `Edward G. submitted a Yelp review about BKHC Law`; cited a three-month response-time complaint, then described the same communication-triage workflow.
- **Brisa Andrade:** subject `Is Lead Docket at Lyfe Law tying marketing spend to signed cases?`; opened on Lead Docket-to-Filevine attribution after signing, mentioned the Precise system processing about 600 emails/day, and asked whether Lyfe could get more from Lead Docket.
- **Christopher Bulone:** subject `Is Lead Docket at Dordick Law Corporation tying marketing spend to signed cases?`; used the same Lead Docket/Filevine attribution and approximately 600-email/day Precise proof point.

Recommended follow-up goals are in `eligibility.json`. They are hooks for the Zoho task to compose against, not drafts.

## Alternates

- Babak Kheiri, `babak@bdinjury.com`, B&D Injury Law Group APLC, one prior touch on 2026-08-12; verify live reply, conflict, and RFC state before use.
- Lourdes De Armas, `lda@omegalaw.com`, Omega Law Group, one prior touch on 2026-08-13; verify live reply, conflict, and RFC state before use.
- Amir Nayebdadash, `amir@protectionlawgroup.com`, Protection Law Group, two prior touches on 2026-08-14; lower priority because of overcontact risk.

## Contextual replies, not unanswered nudges

- `drmichellelim@gmail.com`, 2026-08-20, `Re: Precise imaging - quick question`: classified inbound; needs contextual handling.
- `michael@beverlylaw.org`, 2026-08-19, `Re: Precise Imaging — quick check`: inbound reply in the mirror but unmatched to a contact; resolve and handle contextually.

## Exclusions and threading blocker

The five Sep 10 application recipients (`recruitment@topdoglaw.com`, `info@jacobyandmeyers.com`, `info@ciglaw.com`, `gtopp@stikeman.com`, `hernandezk@gtlaw.com`) were excluded because they are recent job-application threads and outside this outreach scope. `ocampo@centurylawgroup.com` for 10x Law was held for an email/domain mismatch.

The original Resend provider IDs are lookup identifiers only. The Resend email endpoint returned HTTP 404 for all five, so no RFC `Message-ID` or `References` values are available from the provider lookup. Zoho must retrieve the original MIME with `BODY.PEEK[]` from the Sent or configured BCC/audit folder, matching recipient, subject, and sent date, then copy the real RFC headers. Do not use a provider UUID as `In-Reply-To` and do not invent a header.

The current live transport is `resend_first_then_zoho` with a Resend cap of 50 and Zoho cap of 0; the final owner should recheck policy and mailbox immediately before any mutation.
