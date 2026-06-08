"""Download VODs and/or clips from a Twitch channel.

A channel is identified by its login, a channel URL, or a name (Twitch logins
are effectively the channel name). Pick VODs, clips, or both, most recent first.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from ..console import fail
from . import common

KINDS = ("vods", "clips", "all")


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


def _channel_url(login: str, kind: str) -> str:
    base = f"https://www.twitch.tv/{login}"
    return f"{base}/clips" if kind == "clips" else f"{base}/videos"


def select_videos(query: str, kind: str = "vods",
                  latest: int | None = None) -> list[tuple[str, dict]]:
    """Choose (kind, entry) pairs to download for a Twitch channel query."""
    if kind not in KINDS:
        fail(f"Twitch kind must be one of {KINDS}, got '{kind}'.")
    login = _login(query)
    kinds = ("videos", "clips") if kind == "all" else \
            ("clips",) if kind == "clips" else ("videos",)

    chosen: list[tuple[str, dict]] = []
    for k in kinds:
        entries = common.list_videos(_channel_url(login, k), limit=latest or 1)
        chosen += [(k, e) for e in entries]
    if not chosen:
        fail(f"No Twitch {kind} found for '{query}'.\n"
             "   Twitch VODs expire (often 7-60 days), and channel clip listing\n"
             "   via yt-dlp can return nothing when Twitch throttles its API.\n"
             "   Pass a direct VOD/clip URL instead "
             "(e.g. https://www.twitch.tv/videos/123456789),\n"
             "   or update yt-dlp: pip install -U yt-dlp")
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
