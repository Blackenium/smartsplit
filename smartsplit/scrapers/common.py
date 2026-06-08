"""Thin yt-dlp wrapper shared by the YouTube and Twitch scrapers.

Listing uses a flat extraction (fast, metadata only); downloading fetches the
selected entries and reports the files that landed on disk.
"""

from __future__ import annotations

from pathlib import Path

from .. import ffmpeg
from ..console import fail


def _import_ytdlp():
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        fail("yt-dlp is not installed. Activate the venv then: "
             "pip install -r requirements.txt")
    return YoutubeDL


def _ffmpeg_location():
    """Directory of a usable ffmpeg for yt-dlp's muxing, if we resolved one."""
    bin_path = Path(ffmpeg.FFMPEG)
    return str(bin_path.parent) if bin_path.is_absolute() and bin_path.exists() else None


def list_videos(url: str, limit: int | None = None) -> list[dict]:
    """Flat list of entries (metadata only) for a channel/playlist/search URL."""
    YoutubeDL = _import_ytdlp()
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
    }
    if limit:
        opts["playlistend"] = limit
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    entries = (info or {}).get("entries") or []
    return [e for e in entries if e]


def extract(url: str) -> dict:
    """Full (non-flat) extraction for a single URL or search query."""
    YoutubeDL = _import_ytdlp()
    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False) or {}


def entry_url(entry: dict) -> str:
    """Best downloadable URL for a flat entry."""
    if entry.get("url") and str(entry["url"]).startswith("http"):
        return entry["url"]
    if entry.get("webpage_url"):
        return entry["webpage_url"]
    ie = (entry.get("ie_key") or "").lower()
    vid = entry.get("id", "")
    if "twitch" in ie:
        return f"https://www.twitch.tv/videos/{vid}"
    return f"https://www.youtube.com/watch?v={vid}"


def download(urls: list[str], out_dir: Path) -> list[Path]:
    """Download each URL into out_dir, returning the resulting file paths.

    yt-dlp shows its own progress bar; failures on one URL are reported and
    skipped so the rest of the batch still downloads.
    """
    YoutubeDL = _import_ytdlp()
    out_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "outtmpl": str(out_dir / "%(title)s.%(ext)s"),
        "format": "bv*+ba/b",
        "merge_output_format": "mp4",
        "no_warnings": True,
        "ignoreerrors": True,
        "windowsfilenames": True,   # keep file names tame across platforms
    }
    loc = _ffmpeg_location()
    if loc:
        opts["ffmpeg_location"] = loc

    paths: list[Path] = []
    with YoutubeDL(opts) as ydl:
        for url in urls:
            info = ydl.extract_info(url, download=True)
            if not info:
                print(f"   download failed (skipped): {url}")
                continue
            requested = info.get("requested_downloads") or []
            if requested and requested[0].get("filepath"):
                paths.append(Path(requested[0]["filepath"]))
            else:
                paths.append(Path(ydl.prepare_filename(info)))
    return paths
