# AGENTS.md

This repo's project instructions live in `CLAUDE.md`.

Codex and any other AI agent editing this repository must read and follow
`CLAUDE.md` before making changes. Treat it as authoritative for project rules,
including CLI parity, documentation updates, safety rails, prompt-change
protocol, commit discipline, and daemon restart precautions.

Do not implement semantic identity, equivalence, classification, relevance, or
change-detection decisions with regexes or string-matching heuristics unless the
representation makes the answer guaranteed correct. Use TypeSafe Jev for narrow
typed judgments and a structured-output LLM for evidence synthesis, research, or
generation. Keep deterministic code for mechanical invariants and safety
boundaries. Prefilters may reduce candidates but cannot make the final semantic
decision; persist confidence or probabilities and route uncertainty to review.
