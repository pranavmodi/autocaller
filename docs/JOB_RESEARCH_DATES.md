# Firm job research dates

`pif research-job-postings <firm_id> --poll` researches dated openings in the
last 30 days and verified active undated roles. The researcher follows official
careers links to employer ATS listings and records its active-status evidence.

Unknown publication is stored as `posted_date: null` and
`recency_label: date_unknown`. The Job Listings view already displays
Publication unknown; date filters and newest-posted ordering do not substitute
discovery time. Malformed dates, known out-of-window dates, expired roles and
undated listings lacking active evidence are rejected. This is a firm-research
policy change, not a change to the separate daily career-search agent.

## Worker pause observed October 25, 2026

The production environment explicitly sets `PIF_JOB_RESEARCH_WORKERS=0`,
`FIRM_REVIEW_RESEARCH_WORKERS=0`, and `PIF_LOCAL_ENRICHMENT_WORKERS=0` to reserve
the shared OpenClaw lane for interactive requests and explicitly triggered
work. Both batch and interactive lane settings point to `main`.
The date-policy change does not re-enable these workers or drain the backlog.
The standard queue API still accepts tasks when workers are disabled; a queued
task is not evidence of running research. Worker-count changes require a safe
backend restart and an explicit decision about accumulated work.
