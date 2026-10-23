#!/usr/bin/env python3
"""
Adds an approved "Remove me" request to removals.json.

Reads the issue body (from the GitHub issue form) in ISSUE_BODY and prints a one-line
summary for the bot's reply. Exits with code 2 if the form couldn't be read.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "removals.json")
NAME = re.compile(r"^[A-Za-z0-9_-]{2,40}$")


def field(body, label):
    m = re.search(r"###\s*" + re.escape(label) + r"\s*\n+(.*?)(?=\n###|\Z)", body, re.S)
    value = (m.group(1).strip() if m else "")
    return "" if value in ("_No response_", "None") else value


def clean(name):
    name = name.strip().lstrip("@")
    name = re.sub(r"^https?://(www\.)?(twitch\.tv|ch\.tetr\.io/u|tetr\.io/u)/", "", name, flags=re.I)
    name = name.strip("/ ").lower()
    return name if NAME.match(name) else ""


def main():
    body = os.environ.get("ISSUE_BODY", "")
    who = field(body, "I am a").lower()
    user = clean(field(body, "TETR.IO username"))
    twitch = clean(field(body, "Twitch channel (streamers only)"))
    if not user:
        print("Couldn't read a valid username from the form.")
        sys.exit(2)

    with open(PATH, encoding="utf-8") as f:
        data = json.load(f)
    added = []
    if user not in data["players"]:
        data["players"].append(user)
        added.append(user)
    if who.startswith("streamer"):
        for n in filter(None, (user, twitch)):
            if n not in data["streamers"]:
                data["streamers"].append(n)
                added.append(n)
    data["players"].sort()
    data["streamers"].sort()
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

    kind = "streamer" if who.startswith("streamer") else "player"
    names = ", ".join(sorted(set(filter(None, (user, twitch if kind == "streamer" else "")))))
    print(f"Removed {kind} {names}." if added else f"{names} was already on the removal list.")


if __name__ == "__main__":
    main()
