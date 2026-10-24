# Topped Out on Stream

**Live site: [toppedout.chessedonstream.com](https://toppedout.chessedonstream.com/)**

Find the TETRA LEAGUE matches you played against TETR.IO players who stream on Twitch, then watch the match from their stream, or the replay.

Built the same way as [Chessed on Stream](https://chessedonstream.com). Unofficial fan site, not affiliated with TETR.IO or Twitch.

## How it works

- `fetch.py` runs every 2 hours on GitHub Actions (`.github/workflows/update.yml`). It:
  1. Reads the top 1,000 of the TETRA LEAGUE leaderboard from the official TETRA CHANNEL API (`ch.tetr.io/api`, no key).
  2. Checks which of those players link a Twitch account on their profile. Up to 300 profiles are checked per run, best players first, and each is re-checked weekly, so the full scan builds up over the first day (`data/players.json`).
  3. Gets each linked player's ranked matches from the last 30 days (opponent, score, replay ID).
  4. With Twitch keys set, gets their VODs and works out where each match starts in the video (match end time minus round lengths).
  5. Saves `data.json`; `build_pages.py` then makes a page per streamer (e.g. `/wumbo/`), `sitemap.xml` and `robots.txt`.
- GitHub Pages serves the repo's top folder. Search runs in the browser.
- Every match links to its replay at `https://tetr.io/#R:<replay id>`, so it's watchable even without a VOD.

TETR.IO asks API users to make about one request a second and to respect its cache; `fetch.py` pauses 1.05 seconds between requests. Only the public TETRA CHANNEL API is used (the main game API needs written permission).

## Setup

1. **Twitch keys (optional, turns on VOD links):** repo Settings → Secrets and variables → Actions → New repository secret: `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET` (the same Twitch app as Chessed on Stream; if you make a new secret, update both repos). Without them the site shows replays only.
2. **Website:** Settings → Pages → Deploy from a branch → `main` → `/ (root)`. Custom domain `toppedout.chessedonstream.com` (a `CNAME` record named `toppedout` → `alexmannnnnnnnn.github.io` in Cloudflare, DNS only).
3. **First update:** Actions → "Update matches" → Run workflow.

## Adding streamers by hand

For players outside the top 1,000 or who haven't linked Twitch on TETR.IO, add them to `streamers_extra.json`:

```json
[ {"tetrio": "their_tetrio_name", "twitch": "their_twitch_login"} ]
```

## Removal requests

The footer's **Remove me** link opens a GitHub issue form. Add the label **approved** to a request and the "Process removal request" job adds the name to `removals.json`, reruns the update, replies and closes it. Players lose the matches they played against streamers; streamers lose their page and all their matches.

## Settings

- `VOD_DAYS` (default 30), `SCAN_TOP` (default 1000), `MAX_LOOKUPS` (default 300): environment variables for `fetch.py`.
- Donation buttons: the `SUPPORT` line in `index.html`.

## Running it on your own computer

```
python fetch.py          # Twitch keys optional
python build_pages.py
python -m http.server 8000
```
