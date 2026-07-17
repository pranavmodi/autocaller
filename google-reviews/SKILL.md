---
name: google-reviews
description: Retrieve and verify Google Maps / Google Business Profile reviews for a firm or local business. Use when Codex needs latest reviews, latest one-star or low-star reviews, reviewer names, ratings, dates, owner responses, or evidence from a Google Business Profile using Chromium/Playwright, especially when Google Maps serves a limited headless UI.
---

# Google Reviews

## Goal

Use a real Chromium browser session to open a firm's Google Business Profile, sort/filter reviews, and extract verified review metadata and review text. Prefer the rendered Google Maps UI over search snippets.

## Preconditions

Start with live environment checks:

```bash
df -h /
python3 - <<'PY'
try:
    import playwright
    print("python playwright yes")
except Exception as e:
    print("python playwright no", e)
PY
which xvfb-run || true
```

If Chromium is missing, install the smallest working browser first:

```bash
python3 -m playwright install --only-shell chromium
```

If Google Maps gives a limited or stale review UI in headless mode, install full Chromium and use a headed browser under a virtual display:

```bash
python3 -m playwright install --no-shell chromium
xvfb-run -a python3 your_script.py
```

If disk is tight, only clear low-risk caches/temp files before installing: failed Playwright downloads, `/tmp/playwright-*`, package lists, npm cache, and old journals. Do not delete app databases, logs, backups, or service state unless the user explicitly asks.

## Find the Business Profile

Prefer a stable Google Maps URL:

```text
https://www.google.com/maps/place/?q=place_id:<PLACE_ID>
```

If no `place_id` is known, search the web for the exact firm name, city/state, and "Google Maps". Confirm the profile by checking name, address, phone, and review count.

## Browser Workflow

Use headed Chromium when review sorting matters:

```bash
xvfb-run -a python3 - <<'PY'
from playwright.sync_api import sync_playwright

url = "https://www.google.com/maps/place/?q=place_id:PLACE_ID_HERE"

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ],
    )
    page = browser.new_page(
        locale="en-US",
        viewport={"width": 1366, "height": 900},
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
        ),
    )
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(10000)

    print(page.title())
    print(page.locator("body").inner_text(timeout=10000)[:2000])
    browser.close()
PY
```

In the rendered page:

1. Open the `Reviews` tab.
2. Click the `Sort reviews` button.
3. Select the desired sort: `Newest`, `Lowest rating`, `Highest rating`, or `Most relevant`.
4. Scroll the review list to load more cards.
5. Use review card selectors to extract data.

Useful selectors:

```python
cards = page.locator("div.jftiEf")
name = card.locator(".d4r55").first.inner_text()
date = card.locator(".rsqaWe").first.inner_text()
rating = card.locator(".kvMYJc").first.get_attribute("aria-label")
body = card.locator(".wiI7pd").first.inner_text()
```

Expand truncated reviews before extracting:

```python
try:
    card.locator('button[aria-label="See more"]').first.click(timeout=1000)
    page.wait_for_timeout(500)
except Exception:
    pass
```

## Latest Reviews

To get the latest reviews:

1. Sort by `Newest`.
2. Read review cards from top to bottom.
3. Extract reviewer name, relative date, star rating, and body text.
4. If exact ordering is disputed, inspect embedded timestamps from the Google Maps profile payload or compare visible relative dates.

## Latest One-Star Review

To find the latest one-star review:

1. Sort by `Newest`.
2. Scan cards from the top down.
3. Stop at the first card whose rating is `1 star`.
4. Expand `See more`.
5. Extract name, date, rating, and body.

Do not use `Lowest rating` alone when the user asks for latest one-star review. `Lowest rating` finds one-star reviews, but it may not order them by recency. Use `Newest` and scan until the first `1 star`.

## Network Fallbacks

If the UI does not update:

- Capture requests containing `batchexecute` and `rpcids=qv9Egd`.
- Google Maps review sorting uses `/MapsUgcPostService.ListUgcPosts`.
- Observed sort codes: `Newest` uses `[2]`, `Highest rating` uses `[3]`, and `Lowest rating` uses `[4]`.
- Treat Google Search review-dialog routes as less reliable; they may trigger bot checks faster than Maps.

## Reporting

Report the evidence compactly:

- Business profile name and address.
- Overall rating and review count if visible.
- For each review: reviewer, rating, date, and concise summary.
- Include the Google Maps profile link.

When the user asks for exact text, quote only a short compliant excerpt in chat and summarize the rest unless the source text is user-provided or otherwise permitted. You may read long review text in the browser to answer questions, but do not reproduce a long third-party review verbatim in the final response.

## Common Failure Modes

- Headless Chromium may show a limited Google Maps UI where sorting appears accepted but cards do not refresh.
- Google Search may return a bot-check page for review modal URLs.
- Infinite scroll may not load more cards unless the full headed UI is used.
- Low disk can break browser installation; check disk before installing full Chromium.
- Review text can be truncated; always click `See more` on the target card before extraction.
