# PIF firm CRUD

Possible OS accepts complete operator-researched firm profiles as JSON. Writes
are keyed by canonical domain, maintain `firm_intel_aliases`, and preserve an
explicit `possibleos_manual` provenance block.

Operator-created records persist `manually_added=true`. Sync-origin records use
`manually_added=false`; filter them with `pif firms --source manual|synced` or
the API's `manually_added=true|false` query parameter.

## CLI

```bash
bin/possibleos pif create --file firm.json --dry-run
bin/possibleos pif create --file firm.json
bin/possibleos pif upsert --file firm.json
bin/possibleos pif update example.com --file firm-patch.json
bin/possibleos pif delete example.com --dry-run
bin/possibleos pif delete example.com --yes
```

`create` returns a conflict when the ID or canonical domain already exists.
`upsert` is idempotent by ID or canonical domain. `update` is a partial patch.
`delete` removes the directory row and aliases but deliberately preserves
contacts, communications, reviews, and other operational history. Deleting an
upstream-synced record requires `--force` because the next sync may recreate it.

## Profile shape

Only `firm_name` and `website` (or `canonical_website`) are required when
creating a firm. All other fields are optional.

```json
{
  "firm_name": "Example Law Firm, P.C.",
  "website": "https://example.com/",
  "entity_type": "law_firm",
  "metro": "philadelphia",
  "emails": ["intake@example.com"],
  "phones": ["215-555-0100"],
  "addresses": [
    {"city": "Philadelphia", "state": "PA"}
  ],
  "contacts": [
    {
      "name": "Alex Example",
      "title": "Managing Partner",
      "email": "alex@example.com",
      "is_decision_maker": true
    }
  ],
  "vendor_stack": {
    "other": {
      "intaker": {
        "category": "intake",
        "confidence": 0.99,
        "grade": "A",
        "evidence": [
          {
            "type": "website_script",
            "url": "https://example.com/",
            "observed_at": "2026-07-22T00:00:00Z"
          }
        ]
      }
    }
  },
  "research_data": {
    "sources": ["https://example.com/"]
  },
  "aliases": {
    "domains": ["example.com"],
    "vanity_domains": [],
    "legacy_pif_ids": []
  },
  "provenance": {
    "method": "public_technographic_research",
    "observed_at": "2026-07-22T00:00:00Z"
  }
}
```

When `contacts` changes and `emails`, `phones`, `leadership`, or `staff` are
omitted, those fields are derived from the contact records.

## REST

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/pif/firms/{id-or-domain}` | Read the complete firm profile. |
| `POST` | `/api/pif/firms` | Create a manual firm. |
| `POST` | `/api/pif/firms/upsert` | Create or update by ID/domain. |
| `PATCH` | `/api/pif/firms/{id-or-domain}` | Partially update a firm. |
| `DELETE` | `/api/pif/firms/{id-or-domain}` | Delete the directory row and aliases. |

Write endpoints accept `?dry_run=true`; delete additionally accepts
`?force=true`.
