# Possible OS project constraints

## Semantic decisions require semantic models

Do not use regexes, token overlap, substring checks, edit distance, or other
string-matching heuristics to make a semantic decision unless the representation
and invariants make the result guaranteed correct. Exact code remains appropriate
for mechanical facts such as protocol constants, normalized identifiers, hashes,
schema validation, delimiters, and exact allowlists.

Use TypeSafe Jev for narrow, typed judgments such as classification, equivalence,
identity matching, relevance, and change detection when the required state can be
supplied directly. Use a structured-output LLM when the task requires evidence
synthesis, research, extraction across varied documents, or generation. Preserve
the returned model, probabilities or confidence, evidence, and threshold. Route
uncertain results to review. A regex or string check may narrow candidates for
performance, but it must not produce the final semantic accept/reject decision.

## Web research ownership

EmailTag web search is disabled and must not be treated as an available
research backend. Any Possible OS feature that depends on web research must run
locally in Possible OS, normally through the loopback OpenClaw gateway using
`openclaw/main`, and persist its results in the local Possible OS database.

When changing an older feature, check whether it still queues or polls an
EmailTag research endpoint. If it does, move that research workflow into
Possible OS before relying on it. Existing local migrations, such as job-opening
research, should remain local. EmailTag data-sync APIs may still be used for
data that EmailTag already stores; this constraint specifically covers web
search and web-research execution.

See `CLAUDE.md` for the complete project rules.


### Job Agent website application channel (2026-09-25)

Job Agent can run explicitly authorized employer-form applications through a
durable Playwright/structured-LLM worker. The shared modal shows browser progress,
screenshots and answer/resume controls. Website and Zoho email statuses remain
separate. CLI commands and recovery limitations are documented in
[Website applications](docs/JOB_BROWSER_APPLICATIONS.md).
