---
name: job-opening-research
description: Source-backed web research for recent job openings at one exact law firm. Returns strict JSON for Possible OS.
---

# Recent job-opening researcher

Research job openings for exactly one law firm using web search. Return only a
JSON object, with no markdown fences or commentary.

## Input

```json
{
  "firm_name": "Example Injury Law",
  "official_website": "example.com",
  "window_start": "2026-07-28",
  "window_end": "2026-08-26"
}
```

## Required research

Search the firm's official careers page and reputable sources such as LinkedIn,
Indeed, Glassdoor, ZipRecruiter, and legal-industry job boards. Confirm that each
opening belongs to the exact firm. Use the official domain, location, and firm
identity to reject similarly named employers.

Specifically look for remote roles that accept applicants worldwide. Search for
phrases such as "work from anywhere", "anywhere in the world", "worldwide",
"globally remote", and "international applicants". Also capture explicit
country, state, region, residency, and time-zone restrictions. Do not treat the
word "remote" by itself as evidence that a role is open globally.

Include only postings with a publication date visibly supported by a source and
inside the inclusive input date window. Exclude undated listings, inferred
dates, expired listings without an in-window publication date, generic careers
pages, aggregator search-result pages, and openings at similarly named firms.
Never infer missing facts. Prefer a direct posting URL over a search-results URL.

## Output

```json
{
  "postings": [
    {
      "title": "Intake Specialist",
      "location": "Los Angeles, CA",
      "employment_type": "Full-time",
      "remote_eligibility": "Remote within the United States only",
      "posted_date": "2026-08-15",
      "description_summary": "Handles prospective-client intake and follow-up.",
      "responsibilities": ["Answer prospective-client calls"],
      "qualifications": ["One year of intake experience"],
      "source_name": "Example Injury Law careers",
      "source_url": "https://example.com/careers/intake-specialist"
    }
  ]
}
```

`posted_date` must be `YYYY-MM-DD`. `remote_eligibility` must reproduce the
shortest source-backed phrase that describes remote eligibility or its location
restriction. Use JSON `null` when location, employment type, or remote
eligibility is unknown. All other fields are required. Return
`{"postings":[]}` when no qualifying posting is found. Do not pad a negative
result with unsupported openings.
