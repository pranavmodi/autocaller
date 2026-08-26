# Possible OS project constraints

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
