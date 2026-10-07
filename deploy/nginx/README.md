# Possible OS crawler policy

`autocaller.conf` mirrors the nginx virtual host for the internal operations app
on autocaller.getpossibleminds.com and possibleos.getpossibleminds.com. Frontend
responses carry `X-Robots-Tag: noindex, nofollow`; robots.txt permits crawling so
search engines can observe that exclusion on previously indexed login variants.
API, webhook, audio, WebSocket, and tracking locations are unchanged.

This is search hygiene, not security. Authentication remains necessary.

Before installing, compare the tracked file against the current host config and
preserve any later changes. Back up the live file, install the reviewed config,
run `nginx -t`, then use a graceful reload, never a service stop. If validation
fails, restore the backup. A reload does not require restarting the application
or deploying unrelated frontend work.

Verification (no login credentials or campaign links needed):

```bash
curl -I 'https://autocaller.getpossibleminds.com/login?next=/todos'
curl -I 'https://possibleos.getpossibleminds.com/login'
curl -fsS 'https://autocaller.getpossibleminds.com/robots.txt'
```

Expect a 200 login page with the noindex header, and a 200 text/plain robots file
containing `Allow: /`. Do not replace that allow rule with `Disallow: /` while
existing URLs still need to be recrawled and removed from search.
