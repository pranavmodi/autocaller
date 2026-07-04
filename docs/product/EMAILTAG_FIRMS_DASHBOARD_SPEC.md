# EmailTag Firms Dashboard — functional spec (possibleos tab)

A new possibleos frontend tab (parallel to `/firms`) that is a full client of the
**EmailTag** FastAPI backend's PIFStats firm-intelligence API. This doc is the
functional contract; `docs/product/tasks/PACKET_EMAILTAG_FIRMS_TAB.md` carries the
possibleos-specific integration + guardrails. Verified against the live deployment
and the `firmintel-vendor-stack` branch on 2026-07-01.

## Backend facts (verified)

- Deployment: `https://emailprocessing.mediflow360.com`, API prefix `/api/v1`.
- **Auth = signed cookie**, not a bearer token. `POST /api/v1/pifstats-auth/login`
  with `{username,password}` sets an HttpOnly `pifstats_session` cookie
  (`SameSite=Lax; Secure`, 24h). Every `/pif-info/*` request needs that cookie or
  returns `401 {"detail":"PIFStats authentication required"}`.
  - `GET /pifstats-auth/check` → 200 if authed, 401 otherwise.
  - `POST /pifstats-auth/logout` clears it.
- **Cross-site gotcha (the reason for the proxy):** emailtag is on `mediflow360.com`,
  possibleos is a different registrable domain. `SameSite=Lax` means a direct
  cross-site browser `fetch` will NOT send the cookie → auth fails. The packet
  solves this by proxying emailtag under the possibleos origin via a Next.js
  rewrite (`/emailtag/:path*`), so all calls are same-origin and the cookie flows.
  **The client base URL is therefore `/emailtag` (same-origin), never the absolute
  mediflow360 URL.**

## Endpoints (all under the proxied base `/emailtag`)

Auth:
- `POST /pifstats-auth/login` `{username,password}` → `{authenticated,username}` (sets cookie)
- `GET  /pifstats-auth/check` → 200/401
- `POST /pifstats-auth/logout`

Firms:
- `GET  /pif-info/` — list. Query params (all optional): `search`, `page` (≥1),
  `page_size` (1–100, use 25), `sort_by` (`conversation_count|firm_name|updated_at`),
  `research_status`, `icp_tier` (`A|B|C|D`), `entity_type`, `recently_researched` (int days),
  `website_presence` (`any|has|missing|resolved|unresolved`), `research_presence`
  (`any|completed|missing|queued_or_running|failed`), `staff_presence` (same set),
  `behavior_presence` (`any|has|missing`), `icp_presence` (`any|has|missing`),
  `vendor_presence` (`any|has|missing`), `active_only` (bool, default true).
  Returns `{items, total, page, page_size, total_pages}`.
- `GET  /pif-info/{id}` — one firm.
- `GET  /pif-info/people` — `title`,`name`,`role_category`,`source`(`leadership|staff|all`),`page`,`page_size`.
- `GET  /pif-info/export?format=json|csv&include_merged=false` — streamed, all firms.
- `GET  /pif-info/{id}/export?format=json|csv` — streamed, one firm.

Per-firm actions (POST, async Celery — dispatch then poll):
- `POST /pif-info/{id}/enrich-all` → `{task_id,...}`; poll `GET /pif-info/enrich-all/status/{task_id}`.
- `POST /pif-info/{id}/research` / `/research-staff` → `{task_id,...}`; poll `GET /pif-info/research-status/{task_id}`.
- `POST /pif-info/{id}/detect-vendors` → `{task_id,...}`; **no status endpoint** — poll `GET /pif-info/{id}` and watch `updated_at` change.
- `POST /pif-info/{id}/analyze-behavior` → behavior result.

## Data shapes (TypeScript — authoritative, includes vendor_stack)

```ts
export interface PifContact { name: string; title: string; email: string; phone: string; extension: string; }
export interface LeadershipMember {
  name: string; title: string; email: string | null; phone: string | null; linkedin: string | null;
  bio: string | null; image_url: string | null;
  education?: string[]; experience?: string[]; skills?: string[]; certifications?: string[];
  publications?: string[]; cases_handled?: string[]; bar_admissions?: string[];
}
export interface StaffMember {
  name: string; title: string; role_category: string;
  email: string | null; phone: string | null; linkedin: string | null; bio: string | null;
}
export interface ResearchData {
  practice_areas: string[]; founded_year: string | null; firm_size: string | null;
  office_locations: string[]; notable_cases: string[]; awards_recognition: string[];
  bar_associations: string[]; social_media: Record<string, string>;
  additional_info: string | null; sources: string[];
  leadership_email_history?: unknown[];
}
export interface BehavioralData {
  total_email_count: number; monthly_email_volume: number[]; last_contact_date: string | null;
  days_since_last_contact: number | null; topic_distribution: Record<string, number>;
  primary_pain_point: string | null; sender_roles: Record<string, number>;
  peak_contact_days: string[]; after_hours_ratio: number; analyzed_at: string;
}
export interface ScoreBreakdown {
  email_volume_score: number; email_volume_reason: string; recency_score: number; recency_reason: string;
  pain_signals_score: number; pain_signals_reason: string; firm_size_score: number; firm_size_reason: string;
  completeness_score: number; completeness_reason: string; total: number; scored_at: string | null;
}
export interface VendorStackEntry {
  vendor: string; source: string; confidence?: string; known?: boolean; evidence?: string;
}
export interface PifInfoResponse {
  id: string; firm_name: string; entity_type: string;
  website: string | null; canonical_website: string | null;
  website_status: string | null; website_source: string | null; website_confidence: number | null;
  emails: string[]; phones: string[]; fax: string | null; addresses: string[];
  contacts: PifContact[]; conversation_ids: string[]; extraction_notes: string | null;
  leadership: LeadershipMember[] | null; research_data: ResearchData | null;
  research_status: string | null; last_researched_at: string | null;
  staff: StaffMember[] | null; staff_research_status: string | null;
  behavioral_data: BehavioralData | null;
  icp_score: number | null; icp_tier: string | null;
  score_breakdown: ScoreBreakdown | null; icp_scored_at: string | null;
  vendor_stack: VendorStackEntry[] | null; // null = no vendors detected (treated as "missing")
  created_at: string; updated_at: string;
}
export interface PifInfoListResponse { items: PifInfoResponse[]; total: number; page: number; page_size: number; total_pages: number; }
export interface ResearchStartResponse { pif_id: string; firm_name: string; task_id: string; status: string; message: string; }
export interface FullEnrichmentStatusResponse { task_id: string; status: string; message: string; pif_id?: string | null; firm_name?: string | null; result?: Record<string, unknown> | null; }
```

Entity labels:
```ts
export const ENTITY_TYPE_LABELS: Record<string, string> = {
  pi_law_firm: "PI Law Firm", medical_referring: "Medical Referring",
  medical_facility: "Medical Facility", insurance: "Insurance", funding: "Funding",
  collections: "Collections", legal_other: "Legal (Other)",
  administrative: "Administrative", patient_adjacent: "Patient Adjacent",
};
```

ICP: `icp_score` 0–100; tiers A ≥75, B 50–74, C 25–49, D <25. Guard every nullable
field (`leadership|staff|research_data|behavioral_data|vendor_stack|score_breakdown`).

## UI behaviour

- **Login gate:** on mount call `/pifstats-auth/check`; on 401 show a login form
  (POST `/pifstats-auth/login`), then re-check. Global 401 handling → back to login.
- **Filter bar:** one control per list query param above; changing any filter resets
  to page 1 and refetches; "Active only" toggle; "Clear filters".
- **Table:** paginated (page_size 25), columns firm name, entity type, website,
  conversation count, ICP tier/score, research status; Prev/Next via `total_pages`.
- **Expandable detail row:** header actions Run full enrichment (`enrich-all` +
  poll), Export JSON/CSV (per-firm), Open website; contact data; research-status
  grid (research/staff/last-researched/ICP); Front conversation IDs; **Vendor Stack**
  (chips of vendor+source+confidence, amber "new" badge when `known===false`) with a
  Detect vendors button (`detect-vendors`, then poll `GET /{id}` on `updated_at`);
  Leadership / Staff / Extracted Contacts; raw-JSON viewers for research_data and
  behavioral_data.
- **Bulk export:** header buttons Export all → JSON / CSV hitting `/pif-info/export`,
  downloaded as a blob (streamed, can be ~2,400 firms — do not buffer as text state).
