---
name: pif-local-enrichment
description: Source-backed web enrichment for one firm extracted by EmailTag. Returns strict JSON for Possible OS.
---

# Local firm enrichment

Research exactly one organization using web search. Return only JSON without
markdown or commentary. Confirm identity using the supplied observed website,
email domains, phone numbers, and addresses. Do not blend similarly named firms.

Find the official canonical registrable domain, organization summary, practice
areas, offices, firm size, founding year, leadership, staff, and evidenced legal
technology vendors. Also capture notable cases, awards, bar associations, and
useful firm context when directly sourced. For leaders, retain public biography,
education, experience, certifications, publications, representative cases, and
bar admissions when available. Search the official website first, then reputable public
profiles, current job postings, and vendor customer pages. Never infer a vendor
from a generic integration or infer a person, title, date, or domain without a
supporting source.

## Output

```json
{
  "canonical_website": "examplefirm.com",
  "website_confidence": 0.95,
  "website_sources": ["https://examplefirm.com/about"],
  "summary": "Personal injury law firm serving Southern California.",
  "practice_areas": ["Personal injury"],
  "founded_year": 2012,
  "firm_size": "15-50",
  "office_locations": ["Los Angeles, CA"],
  "notable_cases": [],
  "awards_recognition": [],
  "bar_associations": [],
  "social_media": {"linkedin": "https://www.linkedin.com/company/example"},
  "additional_info": null,
  "sources": ["https://examplefirm.com/about"],
  "leadership": [
    {
      "name": "Avery Owner",
      "title": "Managing Partner",
      "email": null,
      "phone": null,
      "linkedin": "https://www.linkedin.com/in/avery-owner",
      "source_url": "https://examplefirm.com/team/avery-owner",
      "bio": null,
      "education": [],
      "experience": [],
      "skills": [],
      "certifications": [],
      "publications": [],
      "cases_handled": [],
      "bar_admissions": []
    }
  ],
  "staff": [],
  "vendor_stack": {
    "case_mgmt": "filevine",
    "other": {},
    "evidence": [
      {
        "vendor": "filevine",
        "source": "job_posting",
        "source_url": "https://examplefirm.com/jobs/case-manager",
        "confidence": 0.9
      }
    ]
  }
}
```

Use JSON `null` for unknown scalar values and empty arrays or objects for
unknown collections. `canonical_website` must be a domain, not a social profile,
directory, or URL path. Every person must have a `source_url`. Return no more
than 15 leadership and 30 staff records. Vendor evidence must name a direct
source URL. Required top-level keys are `canonical_website`, `website_confidence`,
`website_sources`, `summary`, `practice_areas`, `founded_year`, `firm_size`,
`office_locations`, `notable_cases`, `awards_recognition`, `bar_associations`,
`social_media`, `additional_info`, `sources`, `leadership`, `staff`, and `vendor_stack`.
