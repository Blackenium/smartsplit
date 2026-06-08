"""Download VODs and/or clips from a Twitch channel.

Channel listing is done through Twitch's public GraphQL API (yt-dlp's own
channel listing currently returns nothing), then each VOD/clip is downloaded by
yt-dlp via its single-item extractor. A direct VOD/clip URL is downloaded as-is.

A channel is identified by its login, a channel URL, or a name (Twitch logins
are effectively the channel name).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from ..console import fail
from . import common

KINDS = ("vods", "clips", "all")

# Twitch's public web Client-ID (the one the website itself uses for gql.twitch.tv).
_GQL_URL = "https://gql.twitch.tv/gql"
_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"


def _is_single_item(query: str) -> bool:
    """A specific VOD or clip URL (downloaded directly, no channel listing)."""
    q = query.strip().lower()
    return ("twitch.tv/videos/" in q or "/clip/" in q or "clips.twitch.tv/" in q)


def _login(query: str) -> str:
    """Extract the channel login from a name or any twitch.tv URL."""
    q = query.strip()
    if "twitch.tv" in q or q.startswith(("http://", "https://")):
        parts = [p for p in urlparse(q).path.split("/") if p]
        if not parts:
            fail(f"Could not read a Twitch channel login from '{query}'.")
        return parts[0]
    return q.lstrip("@")


def _gql(query: str) -> dict:
    """Run a GraphQL query against Twitch's public endpoint."""
    req = urllib.request.Request(
        _GQL_URL, data=json.dumps({"query": query}).encode(),
        headers={"Client-ID": _CLIENT_ID, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.load(resp)
    except (urllib.error.URLError, ValueError) as e:
        fail(f"Twitch API request failed: {e}")


def _user_edges(login: str, field: str, query: str):
    """Return the edge nodes of user.<field>, or None if the channel is unknown."""
    user = (_gql(query) or {}).get("data", {}).get("user")
    if user is None:
        return None
    return [edge["node"] for edge in (user.get(field) or {}).get("edges", [])]


def _list_vods(login: str, n: int):
    nodes = _user_edges(
        login, "videos",
        f'query{{user(login:"{login}"){{videos(first:{n},sort:TIME)'
        f'{{edges{{node{{id title}}}}}}}}}}')
    if nodes is None:
        return None
    return [{"id": v["id"], "title": v["title"],
             "url": f"https://www.twitch.tv/videos/{v['id']}"} for v in nodes]


def _list_clips(login: str, n: int):
    nodes = _user_edges(
        login, "clips",
        f'query{{user(login:"{login}"){{clips(first:{n},'
        f'criteria:{{period:ALL_TIME,sort:VIEWS_DESC}})'
        f'{{edges{{node{{slug title}}}}}}}}}}')
    if nodes is None:
        return None
    return [{"id": c["slug"], "title": c["title"],
             "url": f"https://clips.twitch.tv/{c['slug']}"} for c in nodes]


def select_videos(query: str, kind: str = "vods",
                  latest: int | None = None) -> list[tuple[str, dict]]:
    """Choose (kind, entry) pairs to download for a Twitch channel query.

    VODs are the most recent broadcasts; clips are the most viewed of all time.
    """
    if kind not in KINDS:
        fail(f"Twitch kind must be one of {KINDS}, got '{kind}'.")
    login = _login(query)
    n = latest or 1

    chosen: list[tuple[str, dict]] = []
    if kind in ("vods", "all"):
        vods = _list_vods(login, n)
        if vods is None:
            fail(f"Twitch channel not found: '{login}'.")
        chosen += [("vod", e) for e in vods]
    if kind in ("clips", "all"):
        clips = _list_clips(login, n)
        if clips is None:
            fail(f"Twitch channel not found: '{login}'.")
        chosen += [("clip", e) for e in clips]

    if not chosen:
        fail(f"No Twitch {kind} found for '{login}'.\n"
             "   The channel may have none right now (VODs expire after 7-60 days).\n"
             "   Try --kind clips, or pass a direct VOD/clip URL.")
    return chosen


def download(query: str, out_dir: Path, kind: str = "vods",
             latest: int | None = None) -> list[Path]:
    if _is_single_item(query):
        print(f"\nTwitch item to download -> {out_dir}/\n   - {query}")
        return common.download([query], out_dir)
    pairs = select_videos(query, kind=kind, latest=latest)
    print(f"\n{len(pairs)} Twitch item(s) to download -> {out_dir}/")
    for k, e in pairs:
        print(f"   - [{k}] {e.get('title') or e.get('id')}")
    return common.download([common.entry_url(e) for _, e in pairs], out_dir)
