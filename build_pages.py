#!/usr/bin/env python3
"""
Builds the shareable / searchable pages from data.json and index.html:

  - index.html          : refreshes the home page's title + link-preview tags
  - <tetrio_username>/  : one page per streamer (e.g. /wumbo/), so Google can find them
  - sitemap.xml, robots.txt

Each streamer page is a copy of index.html with its own title, description and preview
tags, set to open on that streamer's matches. Run after fetch.py.
"""
import html
import json
import os
import re
import shutil
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SITE_NAME = "Topped Out on Stream"


def site_url():
    """Public address of the site. Set SITE_URL when a custom domain is added."""
    url = os.environ.get("SITE_URL", "").strip()
    if not url:
        # GitHub writes the custom domain into a CNAME file when one is set in Settings → Pages
        try:
            with open(os.path.join(HERE, "CNAME"), encoding="utf-8") as f:
                domain = f.read().strip()
            if domain:
                url = "https://" + domain
        except OSError:
            pass
    if not url:
        repo = os.environ.get("GITHUB_REPOSITORY", "alexmannnnnnnnn/ToppedOut-vods")
        owner, name = repo.split("/")
        url = f"https://{owner.lower()}.github.io/{name}"
    return url.rstrip("/") + "/"


PAGES_LIST = os.path.join(HERE, "data", "streamer_pages.json")
SAFE = re.compile(r"^[a-z0-9_-]{3,16}$")   # TETR.IO username rules


def meta_block(title, desc, url, image):
    e = lambda s: html.escape(s, quote=True)
    return f"""<!--META-->
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{e(url)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{SITE_NAME}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{e(url)}">
<meta property="og:image" content="{e(image)}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(title)}">
<meta name="twitter:description" content="{e(desc)}">
<meta name="twitter:image" content="{e(image)}">
<meta name="theme-color" content="#6a35d6">
<!--/META-->"""


def swap(doc, tag, new):
    pat = re.compile(rf"<!--{tag}-->.*?<!--/{tag}-->", re.S)
    if not pat.search(doc):
        raise SystemExit(f"index.html is missing the <!--{tag}--> markers")
    return pat.sub(lambda _: new, doc, count=1)


def main():
    root = site_url()
    image = root + "og.png"
    with open(os.path.join(HERE, "data.json"), encoding="utf-8") as f:
        data = json.load(f)
    index_path = os.path.join(HERE, "index.html")
    with open(index_path, encoding="utf-8") as f:
        template = f.read()

    counts = {}
    for g in data["games"]:
        counts[g["streamer"]] = counts.get(g["streamer"], 0) + 1
    days = data.get("days", 30)

    # ---- home page
    home = swap(template, "META", meta_block(
        f"{SITE_NAME}: find your TETRA LEAGUE matches against TETR.IO streamers",
        "Did you play a TETR.IO streamer in TETRA LEAGUE? Search your username and watch the match "
        "from their Twitch stream, or the replay.",
        root, image))
    home = swap(home, "BOOT", '<!--BOOT--><script>window.BASE = ""; window.PRESET = "";</script><!--/BOOT-->')
    home = swap(home, "ABOUT", "<!--ABOUT--><!--/ABOUT-->")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(home)

    # ---- streamer pages
    try:
        with open(PAGES_LIST, encoding="utf-8") as f:
            previous = set(json.load(f))
    except (OSError, ValueError):
        previous = set()

    made = []
    for s in data["streamers"]:
        login = s["tetrio"].lower()
        if not SAFE.match(login):
            continue
        folder = os.path.join(HERE, login)
        # never write into a folder that this script didn't create (code, data, .github...)
        if os.path.exists(folder) and login not in previous:
            continue
        n, name = counts.get(login, 0), s["name"]
        live = sum(1 for g in data["games"] if g["streamer"] == login and g.get("vod"))
        rank = (s.get("rank") or "").upper()
        url = root + login + "/"
        page = swap(template, "META", meta_block(
            f"{name} TETR.IO matches on stream | {SITE_NAME}",
            (f"{n:,} TETRA LEAGUE matches {name} played in the last {days} days, {live:,} of them on stream "
             f"and linked to the moment in the VOD. Did you play {name}? Search your username.") if data.get("vods") else
            (f"{n:,} TETRA LEAGUE matches {name} played in the last {days} days, each with a replay link. "
             f"Did you play {name}? Search your username."),
            url, image))
        page = swap(page, "BOOT",
                    f'<!--BOOT--><script>window.BASE = "../"; window.PRESET = {json.dumps(login)};</script><!--/BOOT-->')
        e = html.escape
        place = f", ranked #{s['placement']:,}" if s.get("placement") else ""
        page = swap(page, "ABOUT", (
            f'<!--ABOUT--><p class="about">{e(name)} streams TETR.IO on '
            f'<a href="https://www.twitch.tv/{e(s["twitch"])}" rel="noopener">Twitch</a> and plays as '
            f'<a href="https://ch.tetr.io/u/{e(login)}" rel="noopener">{e(login)}</a>'
            f'{" (" + e(rank) + place + ")" if rank else ""}. '
            f'We found {n:,} of their ranked matches in the last {days} days'
            f'{f", {live:,} on stream" if data.get("vods") else ""}. '
            f'Played {e(name)}? Search your username above.</p><!--/ABOUT-->'))
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "index.html"), "w", encoding="utf-8") as f:
            f.write(page)
        made.append(login)

    # remove pages for streamers who dropped out of the data
    for old in previous - set(made):
        folder = os.path.join(HERE, old)
        if SAFE.match(old) and os.path.isfile(os.path.join(folder, "index.html")):
            shutil.rmtree(folder)

    os.makedirs(os.path.dirname(PAGES_LIST), exist_ok=True)
    with open(PAGES_LIST, "w", encoding="utf-8") as f:
        json.dump(sorted(made), f, indent=0)

    # ---- sitemap + robots
    today = time.strftime("%Y-%m-%d", time.gmtime(data.get("generated", time.time())))
    urls = [root] + [root + l + "/" for l in sorted(made)]
    with open(os.path.join(HERE, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for u in urls:
            f.write(f"  <url><loc>{html.escape(u)}</loc><lastmod>{today}</lastmod></url>\n")
        f.write("</urlset>\n")
    with open(os.path.join(HERE, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(f"User-agent: *\nAllow: /\nSitemap: {root}sitemap.xml\n")

    print(f"Built home + {len(made)} streamer pages for {root}")


if __name__ == "__main__":
    main()
