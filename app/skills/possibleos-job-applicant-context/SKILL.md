---
name: possibleos-job-applicant-context
description: Interpret job-application questions using saved applicant answers, current facts, relocation plans and role context. Use when filling or auditing application forms or deciding whether a previously answered question needs clarification.
---

# Contextual applicant answers

Choose the answer appropriate to this field and this job without changing the
applicant's underlying facts. Read the saved applicant profile and this run's
explicit answers before asking anything. Use semantic interpretation, not keyword
or regex routing. In Possible OS, `job-agent profile` reads shared answers;
`profile-save --file FILE` edits them. The browser receives the same profile in
`saved_profile` and automatically saves operator answers with their source job.

## Interpret the question, then select the fact

Read the label, surrounding section, options, explanatory text and job location.
Distinguish current residence, preferred location, intended work location at the
start date, legal work authorization, and willingness to relocate. These are
separate questions even when all contain the word location.

- Current location, current residence, home address and country of residence use
  the actual present location. An intended move does not make that location current.
- Intended work location or location after joining can use a confirmed relocation
  plan when compatible with the start date. If no move date is confirmed, retain
  that uncertainty instead of promising completion before a specified date.
- A job-location preference can use the applicant's saved country or remote-work
  preference. Selecting which office/role to apply for does not assert residence
  unless the field explicitly says so.
- For an ambiguous Location field, infer its meaning from surrounding fields and
  instructions. Ask a narrow question only if material ambiguity remains.
- Never infer citizenship or work authorization from residence, a planned move,
  timezone availability, or a prior answer about another country.

Example: the profile says currently Bengaluru, India, moving shortly to Medellín,
Colombia, with no confirmed move date. Current residence is India. A free-text
work-location answer can say "Currently Bengaluru, India; planning to relocate to
Medellín, Colombia shortly." Preferred remote-work location may be Colombia. A
mandatory current-residence declaration must not say Colombia before the move.
These are examples; use the latest actual profile rather than treating this
example as a permanent fact. UTC-5 in Colombia does not imply US work eligibility
or year-round alignment with US daylight-saving time.

## Scope and time

A saved answer contains its original question, answer, timestamp and source role.
`global` means the operator explicitly made it broadly reusable. `country`,
`company`, `role`, and `application` restrict reuse to the stated scope.
`contextual` requires interpreting the original question and source context:
ordinary personal facts can transfer; employer-specific commitments cannot.

Keep confirmed facts separate from intentions. A newer explicitly changed home
address or relocation confirmation supersedes the old fact; two answers about
current versus future location are not a conflict. If two applicable answers
truly disagree and neither explicitly supersedes the other, ask only about that
conflict. Do not ask for periodic reconfirmation merely because a saved answer
came from another application.

For compensation preserve currency, annual/hourly basis and role/location scope.
A target for a US engineering role is not automatically the target for an India
intake role. Use a saved instruction to exercise judgment only within its scope;
otherwise ask only for the compensation information missing for this role.

Work authorization and employer sponsorship are separate facts. "Not authorized
in the US" alone does not establish whether the employer must sponsor: the
applicant may intend overseas contracting, have an independent immigration plan,
or be uncertain. Use an explicit sponsorship answer or ask the actual form's
question, including an Unsure option when appropriate. Never convert an answer
about India into a US or Colombian answer.

## Reuse before asking

Extract the relevant facts from bundled answers; do not require the user to repeat
an address just because its original message also covered salary and sponsorship.
Use confirmed profile facts and resume details to fill fields, upload the selected
resume and continue under the existing application authorization. Do not ask the
user to approve routine filling or reauthorize an already authorized submission.

If part of a compound question is answered, use that part and ask only for the
missing facts. Cite the original saved answer when resolving a question. Reused
answers are derived evidence, not new independent confirmations. Keep the profile
source identifiers and revisions in the application record so later edits do not
rewrite submission history.

Applicants may apply despite advertised eligibility mismatches. Continue with
truthful answers and let the employer decide, unless the website actually prevents
proceeding or requires an assertion that cannot truthfully be made. This skill
does not override CAPTCHA/login handling or uncertain-submission safeguards.
