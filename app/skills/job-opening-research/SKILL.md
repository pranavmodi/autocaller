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

Include active postings with a source-supported publication date inside the
inclusive input date window. Also include active openings whose publication date
is unavailable, with `posted_date: null`; never substitute today's date, first
discovery, an ATS update, or a search-engine crawl date for publication.
Follow the official careers page's job links to the employer's ATS. Verify the
specific role is still offered using the current employer listing or application
page, not just a cached search snippet. Return `status: "active"` and a short
`active_evidence` explanation identifying what the source actually establishes.
An official careers listing may establish active status even if its ATS is
inaccessible; explain that limitation without inventing the job description.
Exclude closed/expired roles, known publication dates outside the window,
generic careers pages without an identifiable role, aggregator search-result
pages, and openings at similarly named firms. Prefer a direct posting URL.

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
      "status": "active",
      "active_evidence": "The employer's current careers page lists this role and links to its application page.",
      "description_summary": "Handles prospective-client intake and follow-up.",
      "responsibilities": ["Answer prospective-client calls"],
      "qualifications": ["One year of intake experience"],
      "source_name": "Example Injury Law careers",
      "source_url": "https://example.com/careers/intake-specialist"
    }
  ]
}
```

`posted_date` must be `YYYY-MM-DD` or JSON `null` when unavailable. Undated
openings are not evidence of a newly published job. `status` and
`active_evidence` are required for every posting. `remote_eligibility` must reproduce the
shortest source-backed phrase that describes remote eligibility or its location
restriction. Use JSON `null` when location, employment type, or remote
eligibility is unknown. All other fields are required. Return
`{"postings":[]}` when no qualifying posting is found. Do not pad a negative
result with unsupported openings.
