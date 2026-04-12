# Frontend — ARCHIVED

This Next.js dashboard was built for the Precise Imaging build of the system.

The attorney cold-call autocaller is **headless CLI-only** — this directory is
left in place for reference but is not part of the runtime. Do **not** start
`run-frontend.sh`. All operations are performed via `bin/autocaller` (see the
top-level README).

If the dashboard is ever revived, expect it to diverge heavily from the current
code — the backend data model has moved from patients to leads, dispatcher
gating has been simplified, and queue/simulation APIs have been removed.
