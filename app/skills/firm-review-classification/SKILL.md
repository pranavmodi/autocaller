---
name: firm-review-classification
description: Classify PI client reviews into controlled operational and client-journey labels for aggregate analysis.
---

# PI review classifier

Classify the supplied public client reviews. Do not browse the web. Use only the
review text and metadata in the payload. Return only one JSON object with no
markdown or commentary.

## Rules

- Return exactly one classification for every supplied `review_id`.
- Reviews can be mixed: classify themes independently instead of forcing one
  sentiment across the whole review.
- Mark a fact `explicit` only when the review states it. Do not infer a case
  outcome, staff role, journey stage, or cause from the rating alone.
- Preserve short evidence spans verbatim, but do not include more text than is
  needed to support a label.
- Treat allegations as the reviewer's account, not verified facts.
- Firm-owned testimonials are `firm_curated_testimonial`; independent listing
  reviews are `independent_review`; copied aggregations are
  `aggregator_republication`; otherwise use `unknown`.
- Do not call a review fake. Use cautious quality flags such as
  `low_information`, `promotional_or_spam_signal`, `duplicate_like_language`,
  `unclear_firsthand`, or `source_selection_bias`.

## Controlled vocabulary

- `overall_sentiment`: `positive`, `negative`, `mixed`, `neutral`
- `journey_stages`: `initial_contact`, `intake`, `case_evaluation`,
  `signing_and_handoff`, `medical_treatment`, `case_management`, `negotiation`,
  `litigation`, `settlement`, `disbursement`, `post_case`, `unknown`
- Theme names: `response_speed`, `returned_calls`, `proactive_updates`,
  `attorney_accessibility`, `case_manager_accessibility`, `explanation`,
  `expectation_setting`, `empathy_and_respect`, `professionalism`,
  `staff_ownership`, `internal_handoffs`, `staff_continuity`,
  `medical_coordination`, `paperwork`, `case_duration`, `settlement_process`,
  `settlement_amount`, `fees_and_deductions`, `payment_delivery`,
  `language_accessibility`, `technology_experience`, `referral_willingness`
- Theme sentiment: `positive`, `negative`, `mixed`, `neutral`
- `praise_drivers`: `fast_initial_response`, `frequent_updates`,
  `easy_to_reach`, `clear_explanations`, `felt_cared_for`,
  `staff_went_beyond_role`, `smooth_process`, `strong_outcome`,
  `faster_than_expected`, `transparent_fees`,
  `effective_medical_coordination`, `specific_employee_excellence`
- `failure_modes`: `no_callback`, `status_silence`, `attorney_unreachable`,
  `unclear_case_owner`, `poor_handoff_after_signing`,
  `repeated_document_requests`, `staff_turnover`, `unexpected_delay`,
  `unexpected_fee_or_deduction`, `settlement_expectation_mismatch`,
  `medical_coordination_failure`, `case_dropped_or_rejected`, `payment_delay`,
  `rude_or_dismissive_treatment`, `promised_action_not_completed`,
  `client_did_not_understand_process`
- `staff_roles_mentioned`: `attorney`, `case_manager`, `paralegal`,
  `intake_specialist`, `receptionist`, `medical_coordinator`, `settlement_team`,
  `firm_generally`, `unknown`
- Satisfaction: `positive`, `negative`, `mixed`, `neutral`, `unknown`
- `outcome_status`: `positive_outcome`, `negative_outcome`, `case_declined`,
  `case_withdrawn`, `settled`, `went_to_trial`, `still_open`,
  `outcome_not_mentioned`
- `actionability`: `directly_controllable`, `partially_controllable`,
  `mostly_external`, `outcome_dependent`, `unclear`
- `operational_owners`: `intake`, `case_management`, `legal`,
  `medical_coordination`, `settlement`, `finance`, `leadership`,
  `marketing_reputation`
- `referral_intent`: `positive`, `negative`, `none`, `unclear`
- `information_density`: `high`, `medium`, `low`
- `firsthand_signal`: `firsthand`, `third_party`, `unclear`
- `explicit_or_inferred`: `explicit`, `inferred`

## Output

```json
{
  "classifications": [
    {
      "review_id": "review_abc",
      "overall_sentiment": "mixed",
      "sentiment_score": -0.25,
      "language": "en",
      "source_quality": "independent_review",
      "journey_stages": ["intake", "case_management"],
      "case_types": ["auto_accident"],
      "themes": [
        {
          "theme": "proactive_updates",
          "sentiment": "negative",
          "intensity": 3,
          "evidence": "I had to call repeatedly",
          "explicit_or_inferred": "explicit"
        }
      ],
      "praise_drivers": ["fast_initial_response"],
      "failure_modes": ["status_silence"],
      "staff_roles_mentioned": ["case_manager"],
      "named_people": [],
      "process_satisfaction": "negative",
      "outcome_status": "still_open",
      "outcome_satisfaction": "unknown",
      "actionability": ["directly_controllable"],
      "operational_owners": ["case_management"],
      "referral_intent": "negative",
      "information_density": "high",
      "firsthand_signal": "firsthand",
      "quality_flags": [],
      "summary": "Positive intake followed by insufficient case updates.",
      "confidence": 0.91
    }
  ]
}
```
