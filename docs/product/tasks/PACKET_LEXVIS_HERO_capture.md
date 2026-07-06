# PACKET LEXVIS HERO — capture the authentic ChatGPT hero screenshot

Workdir: `/home/pranav/lexvisibility`.

You are Codex. Use your built-in browser tool for this entire task. If your
environment has no working browser tool, STOP immediately and report
"NO BROWSER TOOL" — do not simulate, fabricate, or substitute anything.

## Mission

Produce evidence-grade screenshot(s) of the real consumer ChatGPT surface
answering one question. This image goes in front of a trial lawyer as
evidence about his own firm; it must be authentic, unedited, and complete.

## Integrity rules (absolute)

- The screenshot must be a real capture of chatgpt.com rendering a real
  answer generated during this session. NEVER edit, compose, mock, or
  synthesize an image. NEVER use a cached/stock image.
- If ChatGPT is unreachable, demands login you cannot pass, shows a
  CAPTCHA/bot wall, or errors: capture THAT state once for diagnostics,
  save it clearly named `blocked-*.png`, and report BLOCKED with details.
  A blocked report is a success; a faked screenshot is catastrophic.
- Do not log into any account. Use the logged-out experience, or if the
  surface offers it without login, a temporary chat.

## Steps

1. Open a fresh browser session (no prior cookies if your tool supports it)
   and navigate to `https://chatgpt.com`.
2. Dismiss any consent/intro overlays (decline non-essential where offered).
3. In the message box, enter EXACTLY this query (verbatim, single line):
   `Who are the best car accident lawyers in Los Angeles? Please name specific firms.`
4. Submit and WAIT for the answer to finish generating completely (no
   streaming cursor; give it up to 90s).
5. Capture:
   - a full-page screenshot including the question and the ENTIRE answer
     (scroll and stitch or use full-page capture if the answer exceeds the
     viewport; if you cannot full-page capture, take sequential viewport
     screenshots top-to-bottom with slight overlap and save all of them);
   - save under `data/hero/` (create the dir) as
     `chatgpt-hero-run1-full.png` (and `-part2.png` etc. if sequential).
6. Repeat the whole flow (fresh chat) two more times → `run2`, `run3`.
   Three runs let the operator pick the clearest capture and demonstrates
   the result is stable, not cherry-picked.
7. For every PNG saved, compute `sha256sum` and record it.
8. Write `data/hero/NOTES.md`: per run — timestamp (UTC), the exact query,
   which firms the answer named (list them), whether "Block LLP" appeared
   (expect: it does not — but REPORT WHAT YOU SEE, whatever it is), the
   screenshot filenames + SHA-256 hashes, and any anomalies (login wall,
   region notice, refusal, etc.).

## Guardrails

- Do NOT `git commit`/`git push`. Do NOT touch anything outside `data/hero/`.
- Do not run any other repo code; this is a capture-only task.
- If the answer names Block LLP (unexpected), that is a critical finding —
  record it prominently in NOTES.md; do not re-roll until it disappears.

## Report (end of run)

Files saved with hashes, per-run firm lists, Block LLP presence per run,
and any blocks/anomalies. STOP.
