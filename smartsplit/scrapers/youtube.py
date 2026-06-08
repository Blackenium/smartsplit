"""Download videos from a YouTube channel.

A channel is identified by @handle / URL, or by a free-text name (resolved to
the channel of the top search result). Pick the most recent upload, the latest
N uploads, or filter recent uploads by a title substring.
"""

from __future__ import annotations

from pathlib import Path

from ..console import fail
from . import common

# How many recent uploads to scan when filtering by title.
MATCH_SCAN_WINDOW = 100


def _is_url_or_handle(query: str) -> bool:
    q = query.strip()
    return (q.startswith(("http://", "https://", "@"))
            or "youtube.com" in q or "youtu.be" in q)


def _is_single_video(query: str) -> bool:
    """A specific video URL (downloaded directly, no channel listing)."""
    q = query.strip()
    return ("watch?v=" in q or "youtu.be/" in q or "/shorts/" in q)


def _resolve_channel_by_name(name: str) -> str:
    """Resolve a free-text name to a channel /videos URL via the top hit."""
    info = common.extract(f"ytsearch1:{name}")
    for entry in (info.get("entries") or [info]):
        channel = entry.get("channel_url") or entry.get("uploader_url")
        if channel:
            print(f"Channel match: {entry.get('channel') or entry.get('uploader')} "
                  f"({channel})")
            return channel.rstrip("/") + "/videos"
    fail(f"No YouTube channel found for '{name}'.")


def channel_videos_url(query: str) -> str:
    """Normalise a handle / URL / name into a channel uploads (/videos) URL."""
    q = query.strip()
    if not _is_url_or_handle(q):
        return _resolve_channel_by_name(q)
    if q.startswith("@"):
        return f"https://www.youtube.com/{q}/videos"
    # A watch/playlist URL is downloaded as-is; a channel root gets /videos.
    if "youtube.com" in q and "/watch" not in q and "list=" not in q:
        if not q.rstrip("/").endswith(("/videos", "/streams", "/shorts")):
            return q.rstrip("/") + "/videos"
    return q


def select_videos(query: str, latest: int | None = None,
                  match: str | None = None) -> list[dict]:
    """Choose the entries to download for a channel query."""
    url = channel_videos_url(query)
    if match:
        window = common.list_videos(url, limit=MATCH_SCAN_WINDOW)
        hits = [e for e in window if match.lower() in (e.get("title") or "").lower()]
        if not hits:
            fail(f"No video matching '{match}' in the latest "
                 f"{MATCH_SCAN_WINDOW} uploads of '{query}'.")
        chosen = hits[:latest] if latest else hits[:1]
    else:
        chosen = common.list_videos(url, limit=latest or 1)
    if not chosen:
        fail(f"No videos found for '{query}'.")
    return chosen


def download(query: str, out_dir: Path, latest: int | None = None,
             match: str | None = None) -> list[Path]:
    if _is_single_video(query):
        print(f"\nYouTube video to download -> {out_dir}/\n   - {query}")
        return common.download([query], out_dir)
    entries = select_videos(query, latest=latest, match=match)
    print(f"\n{len(entries)} YouTube video(s) to download -> {out_dir}/")
    for e in entries:
        print(f"   - {e.get('title') or e.get('id')}")
    return common.download([common.entry_url(e) for e in entries], out_dir)
