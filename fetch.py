#!/usr/bin/env python3
"""
Topped Out on Stream: fetcher.

Finds TETR.IO ranked (TETRA LEAGUE) matches played by players who have linked a Twitch
account, and works out where each match starts inside their Twitch VOD. Every match also
gets a TETR.IO replay link, so there is something to watch even without a VOD.
Writes data.json for the website.

Sources (official, no scraping):
  - TETRA CHANNEL API, ch.tetr.io/api  (no key; about one request a second)
  - Twitch Helix API                    (TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET; optional:
                                          without them the site shows replays but no VODs)

Standard library only, so it runs anywhere Python 3.9+ exists (including GitHub Actions).
"""
import datetime as dt
import getpass
from http.client import IncompleteRead
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data.json")
PLAYERS = os.path.join(HERE, "data", "players.json")    # which ranked players link Twitch
EXTRA = os.path.join(HERE, "streamers_extra.json")       # hand-added TETR.IO -> Twitch links
REMOVALS = os.path.join(HERE, "removals.json")           # people who asked to be taken off

VOD_DAYS = int(os.environ.get("VOD_DAYS", "30"))         # how far back to look
SCAN_TOP = int(os.environ.get("SCAN_TOP", "1000"))       # ranked players to check for Twitch links
MAX_LOOKUPS = int(os.environ.get("MAX_LOOKUPS", "300"))  # profile lookups per run (spreads the scan out)
RECHECK_DAYS = 7                                         # re-check a profile's Twitch link weekly
VODS_PER_STREAMER = 60
LEAD_IN = 5                                              # start playback a little before the match
ROUND_GAP = 3                                            # seconds between rounds (countdown)
TETRIO_PAUSE = 1.05                                      # TETR.IO asks for about one request a second
TETRIO = "https://ch.tetr.io/api"
UA = "topped-out-on-stream/1.0 (+{})".format(os.environ.get("CONTACT", "github.com"))
SESSION = "toos-" + uuid.uuid4().hex[:12]                # for related, repeated leaderboard requests


# ------------------------------------------------------------------ http
def http(url, headers=None, data=None, retries=4):
    h = {"User-Agent": UA}
    h.update(headers or {})
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=h, data=data)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8", errors="replace")
                return json.loads(body) if body.strip() else None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                wait = 60 if e.code == 429 else 5 * (attempt + 1)
                log(f"  {e.code} from {urllib.parse.urlparse(url).netloc}, waiting {wait}s")
                time.sleep(wait)
                continue
            log(f"  HTTP {e.code} for {url}")
            return None
        except (urllib.error.URLError, TimeoutError, IncompleteRead,
                ConnectionError, json.JSONDecodeError) as e:
            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            log(f"  network error for {url}: {e}")
            return None


def tetrio(path, session=False):
    """One TETRA CHANNEL request, paced to about one a second. Returns the `data` part."""
    j = http(TETRIO + path, {"X-Session-ID": SESSION} if session else None)
    time.sleep(TETRIO_PAUSE)
    if not j or not j.get("success"):
        if j:
            log(f"  TETR.IO error for {path}: {j.get('error')}")
        return None
    return j.get("data")


def log(msg):
    print(msg, flush=True)


def fail(msg):
    """Stop with an error that also shows up as a GitHub Actions annotation."""
    if os.environ.get("GITHUB_ACTIONS"):
        print("::error::" + msg.replace("\n", " "), flush=True)
    sys.exit(msg)


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, obj, compact=False):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if compact:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)


def iso(s):
    """'2026-10-23T21:11:42.500Z' -> epoch seconds (float)."""
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def prisecter(p):
    return f"{p['pri']}:{p['sec']}:{p['ter']}"


# ------------------------------------------------------------------ streamers
def leaderboard(top):
    """Top `top` TETRA LEAGUE players, best first: [{username, rank, tr, placement}]."""
    out, after = [], None
    while len(out) < top:
        q = f"/users/by/league?limit={min(100, top - len(out))}" + (f"&after={after}" if after else "")
        data = tetrio(q, session=True)
        entries = (data or {}).get("entries") or []
        if not entries:
            break
        for e in entries:
            lg = e.get("league") or {}
            out.append({"username": e["username"].lower(), "rank": lg.get("rank", ""),
                        "tr": round(lg.get("tr") or 0), "placement": len(out) + 1})
        after = prisecter(entries[-1]["p"])
    log(f"Leaderboard: {len(out)} ranked players")
    return out


def refresh_links(board, players):
    """Look up which ranked players have linked Twitch, a batch per run, best players first."""
    now = time.time()
    stale = [p["username"] for p in board
             if now - players.get(p["username"], {}).get("checked", 0) > RECHECK_DAYS * 86400]
    todo = stale[:MAX_LOOKUPS]
    for i, name in enumerate(todo, 1):
        data = tetrio("/users/" + urllib.parse.quote(name))
        if data is None:
            continue
        tw = ((data.get("connections") or {}).get("twitch") or {}).get("username")
        players[name] = {"twitch": tw.lower() if tw else None, "checked": int(now)}
        if i % 50 == 0:
            log(f"  checked {i}/{len(todo)} profiles")
    linked = sum(1 for v in players.values() if v.get("twitch"))
    log(f"Profiles checked this run: {len(todo)} ({len(stale) - len(todo)} left for later runs); "
        f"{linked} players with Twitch linked so far")
    save_json(PLAYERS, players)


# ------------------------------------------------------------------ twitch
class Twitch:
    def __init__(self, client_id, secret):
        body = urllib.parse.urlencode({"client_id": client_id, "client_secret": secret,
                                       "grant_type": "client_credentials"}).encode()
        tok = http("https://id.twitch.tv/oauth2/token", data=body)
        if not tok or "access_token" not in tok:
            fail("Twitch rejected the Client ID / Secret. Double-check the TWITCH_CLIENT_ID and "
                 "TWITCH_CLIENT_SECRET repository secrets.")
        self.h = {"Client-Id": client_id, "Authorization": "Bearer " + tok["access_token"]}

    def users(self, logins):
        out = {}
        for i in range(0, len(logins), 100):
            q = "&".join("login=" + urllib.parse.quote(l) for l in logins[i:i + 100])
            for u in (http("https://api.twitch.tv/helix/users?" + q, self.h) or {}).get("data", []):
                out[u["login"].lower()] = {"id": u["id"], "name": u["display_name"],
                                           "avatar": u.get("profile_image_url", "")}
        return out

    def vods(self, user_id):
        url = (f"https://api.twitch.tv/helix/videos?user_id={user_id}"
               f"&type=archive&first={VODS_PER_STREAMER}")
        out = []
        for v in (http(url, self.h) or {}).get("data", []):
            start = iso(v["created_at"])
            out.append({"id": v["id"], "start": start, "end": start + parse_dur(v["duration"])})
        return out


def parse_dur(s):
    return sum(int(n) * {"h": 3600, "m": 60, "s": 1}[u] for n, u in re.findall(r"(\d+)([hms])", s))


# ------------------------------------------------------------------ matches
def match_duration(rec):
    """Seconds a match lasted: longest life in each round, plus the countdown between rounds."""
    rounds = (rec.get("results") or {}).get("rounds") or []
    ms = sum(max((p.get("lifetime") or 0) for p in rnd) for rnd in rounds if rnd)
    return ms / 1000 + ROUND_GAP * len(rounds)


def parse_match(rec, me):
    """One league record -> match dict from `me`'s side, or None if it isn't a normal 1v1."""
    others = rec.get("otherusers") or []
    board = (rec.get("results") or {}).get("leaderboard") or []
    if len(others) != 1 or len(board) != 2 or not rec.get("replayid"):
        return None
    opp = others[0]
    mine = next((b for b in board if b.get("username", "").lower() == me), None)
    theirs = next((b for b in board if b is not mine), None)
    if not mine or not theirs:
        return None
    end = iso(rec["ts"])
    start = end - match_duration(rec)
    league = (rec.get("extras") or {}).get("league") or {}
    opp_before = (league.get(opp.get("id")) or [{}])[0] or {}
    w1, w2 = mine.get("wins", 0), theirs.get("wins", 0)
    return {
        "replay": rec["replayid"],
        "start": int(start), "end": int(end),
        "opponent": opp.get("username", ""),
        "opp_rank": opp_before.get("rank", ""),
        "score": f"{w1}-{w2}",
        "result": "win" if w1 > w2 else "loss" if w1 < w2 else "draw",
    }


def league_matches(username, since):
    """All of a player's ranked matches since `since` (epoch), newest first."""
    out, after = [], None
    for _ in range(20):                       # at most 2,000 matches per player per run
        q = f"/users/{urllib.parse.quote(username)}/records/league/recent?limit=100"
        data = tetrio(q + (f"&after={after}" if after else ""))
        entries = (data or {}).get("entries") or []
        if not entries:
            break
        for rec in entries:
            m = parse_match(rec, username)
            if m and m["end"] >= since:
                out.append(m)
        if iso(entries[-1]["ts"]) < since or len(entries) < 100:
            break
        after = prisecter(entries[-1]["p"])
    return out


def attach_vods(matches, vods):
    """Give each match its VOD and the offset (seconds) where it starts, if it was on stream."""
    for m in matches:
        for v in vods:
            if v["start"] <= m["start"] <= v["end"]:
                m["vod"] = v["id"]
                m["t"] = max(0, int(m["start"] - v["start"]) - LEAD_IN)
                break
    return matches


# ------------------------------------------------------------------ main
def credentials():
    cid = os.environ.get("TWITCH_CLIENT_ID", "").strip()
    sec = os.environ.get("TWITCH_CLIENT_SECRET", "").strip()
    if not (cid and sec) and sys.stdin.isatty():
        print("Twitch keys not set. Paste them (from dev.twitch.tv/console):")
        cid = cid or input("  Client ID: ").strip()
        sec = sec or getpass.getpass("  Client Secret (hidden): ").strip()
    if not (cid and sec):
        msg = ("No Twitch keys yet, so matches get replay links but no VOD links. Add TWITCH_CLIENT_ID "
               "and TWITCH_CLIENT_SECRET as repository secrets to turn VODs on.")
        print(("::warning::" if os.environ.get("GITHUB_ACTIONS") else "") + msg, flush=True)
        return None
    return cid, sec


def main():
    keys = credentials()
    tw = Twitch(*keys) if keys else None
    since = int(time.time()) - VOD_DAYS * 86400

    board = leaderboard(SCAN_TOP)
    ranks = {p["username"]: p for p in board}
    players = load_json(PLAYERS, {})
    refresh_links(board, players)

    links = {name: v["twitch"] for name, v in players.items() if v.get("twitch") and name in ranks}
    for e in load_json(EXTRA, []):
        links[e["tetrio"].lower()] = e["twitch"].lower()

    removed = load_json(REMOVALS, {})
    gone_players = {n.lower() for n in removed.get("players", [])}
    gone_streamers = {n.lower() for n in removed.get("streamers", [])}
    links = {k: v for k, v in links.items() if k not in gone_streamers and v not in gone_streamers}

    if tw:
        users = tw.users(sorted(set(links.values())))
        log(f"Linked Twitch channels that exist: {len(users)} of {len(set(links.values()))}")
    else:   # no keys: trust the link TETR.IO shows, without avatars or VODs
        users = {l: {"id": None, "name": l, "avatar": ""} for l in set(links.values())}

    games, streamers, with_vods = [], {}, 0
    todo = sorted((k for k in links if links[k] in users), key=lambda k: ranks.get(k, {}).get("placement", 10**6))
    for i, name in enumerate(todo, 1):
        login = links[name]
        vods = [v for v in tw.vods(users[login]["id"]) if v["end"] >= since] if tw else []
        found = attach_vods(league_matches(name, since), vods)
        on_stream = sum(1 for m in found if "vod" in m)
        log(f"[{i}/{len(todo)}] {name} -> twitch:{login}: {len(found)} matches, {on_stream} on stream")
        if not found:
            continue
        with_vods += 1 if on_stream else 0
        for m in found:
            m["streamer"] = name
        games += found
        r = ranks.get(name, {})
        streamers[name] = {"tetrio": name, "twitch": login, "name": users[login]["name"],
                           "avatar": users[login]["avatar"], "rank": r.get("rank", ""),
                           "tr": r.get("tr", 0), "placement": r.get("placement")}

    before = len(games)
    games = [g for g in games if g["opponent"].lower() not in gone_players]
    if before != len(games):
        log(f"Hid {before - len(games)} matches of players who asked to be removed")
    still = {g["streamer"] for g in games}
    streamers = {k: v for k, v in streamers.items() if k in still}
    games.sort(key=lambda g: g["start"], reverse=True)

    save_json(OUT, {
        "generated": int(time.time()),
        "days": VOD_DAYS,
        "vods": bool(tw),
        "streamers": sorted(streamers.values(), key=lambda s: s.get("placement") or 10**6),
        "games": games,
    }, compact=True)
    on_stream = sum(1 for g in games if "vod" in g)
    log(f"\nSaved {len(games)} matches ({on_stream} on stream) from {len(streamers)} streamers "
        f"({with_vods} with VODs) -> {OUT}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # make crashes readable in the Actions summary
        import traceback
        traceback.print_exc()
        fail(f"{type(e).__name__}: {e}")
