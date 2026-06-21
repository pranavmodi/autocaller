# Competitor Graph Validation Report

Generated: 2026-06-16 10:20 UTC

## Scope

This audit validates the current `firm_competitive_features` and
`competitor_edges` tables in the local Possible OS Postgres database. It is an
automated/local evidence audit, not a full external-web verification pass.

Artifacts:

- `feature_audit_20260616.csv` - one row per graph feature firm with hygiene flags.
- `edge_audit_20260616.csv` - one row per edge with endpoint, evidence, and audit-bucket flags.

## Current Graph

- Total feature firms: 1,711
- Firms with at least one edge: 1,210
- Total edges: 5,858
- Last feature computation timestamp: 2026-06-12 05:56:03 UTC

## Feature Quality Findings

- Missing metro: 495 / 1,711
- Missing domain: 242 / 1,711
- Missing value tier: 1,132 / 1,711
- Zero matched conversation threads: 1,094 / 1,711
- Mostly `other` case mix: 1,683 / 1,711
- Likely law-firm name/domain by keyword: 1,450 / 1,711
- Suspected non-law endpoint by refined keyword screen: 69 / 1,711
- Unknown name type after keyword screen: 193 / 1,711

Main issue: the feature table is not a clean PI-law-firm universe. It includes
medical providers, imaging groups, chiropractic groups, funders, discovery
vendors, and other legal-adjacent entities. These can become graph nodes.

## Edge Quality Findings

- Total edges: 5,858
- Same-metro edges: 5,849
- Adjacent-metro edges: 9
- Client-switching evidence edges: 0
- Both endpoints have zero matched threads: 3,130
- Both endpoints missing value tier: 3,324
- Sparse case-only edges: 1,497
- Edges with suspected non-law endpoint: 430

Automated edge buckets:

- `likely_usable`: 2,049
- `manual_review`: 584
- `weak_no_thread_evidence`: 1,482
- `weak_sparse_case_only`: 1,313
- `bad_endpoint_review`: 430

The biggest accuracy risk is that many edges are formed because both firms have
`case_mix = {"other": 1.0}` and share the same metro. That can make sparse rows
look artificially similar.

## Concrete Bad-Endpoint Examples

The audit found high-scoring edges involving non-law entities such as:

- `precisemri.com`
- SimonMed Imaging
- MLC Health Group
- Rezolut
- In View Imaging
- Nationwide Med MRI
- OrthoPain Institute

These are not PI-firm competitors and should not appear as peer law-firm nodes.

## Interpretation

The graph is directionally useful for law-firm-to-law-firm proximity when both
endpoints are real law firms and have real evidence. However, it is not accurate
enough yet to trust blindly for outreach targeting or competitor intelligence.

The current graph over-connects sparse records because:

1. `other` case mix creates false similarity.
2. Missing value tier is common.
3. Zero-thread records can still get edges through shared metro and generic case mix.
4. The source universe includes non-law entities.
5. No current edges use client-switching evidence, so the graph is mostly
   inferred similarity rather than observed substitution.

## Recommended Fixes

1. Filter graph nodes to real PI law firms before edge generation.
   Use entity type, source tags, firm-name/domain classifier, and explicit
   denylist patterns for medical/imaging/chiro/funding/discovery vendors.

2. Treat `case_mix = {"other": 1.0}` as low-information.
   It should not produce a full case-mix similarity of `1.0` unless there is
   additional evidence.

3. Require at least one stronger signal for an edge:
   matched thread evidence, value tier, recent Front activity, or validated
   law-firm classification.

4. Add graph confidence tiers:
   `high_confidence`, `medium_confidence`, `weak_inferred`, `excluded`.

5. Rebuild after applying filters, then rerun this audit.

## Bottom Line

Current graph size is healthy, but accuracy is mixed. A conservative read is:
roughly 2,049 of 5,858 edges look likely usable by automated checks, 584 need
manual review, and 3,225 should be treated as weak or bad until the node filter
and sparse-case scoring are fixed.
