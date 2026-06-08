"""ffmpeg/ffprobe resolution and the small probing helpers.

The resolved binaries are kept as module attributes (FFMPEG / FFPROBE) and set
once by resolve(). Import the module and reference ffmpeg.FFMPEG so callers
always see the resolved value (do not `from .ffmpeg import FFMPEG`).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .console import fail

# Resolved at startup by resolve(): an ffmpeg built with libass.
FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


def _has_subtitles_filter(ffmpeg_bin: str) -> bool:
    try:
        out = subprocess.run([ffmpeg_bin, "-hide_banner", "-filters"],
                             capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    return any(len(p) >= 2 and p[1] == "subtitles"
               for p in (line.split() for line in out.stdout.splitlines()))


def resolve() -> tuple[str, str]:
    """Find an ffmpeg with libass and its matching ffprobe, and remember them.

    Preference order: FFMPEG env var, Homebrew's ffmpeg-full (which ships
    libass), then ffmpeg on PATH.
    """
    global FFMPEG, FFPROBE
    candidates: list[str] = []
    if os.environ.get("FFMPEG"):
        candidates.append(os.environ["FFMPEG"])
    candidates += [
        "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",  # Apple Silicon
        "/usr/local/opt/ffmpeg-full/bin/ffmpeg",     # Intel
    ]
    if shutil.which("ffmpeg"):
        candidates.append(shutil.which("ffmpeg"))

    for bin_path in candidates:
        if bin_path and Path(bin_path).exists() and _has_subtitles_filter(bin_path):
            ffprobe = Path(bin_path).with_name("ffprobe")
            probe = str(ffprobe) if ffprobe.exists() else (shutil.which("ffprobe") or "ffprobe")
            FFMPEG, FFPROBE = bin_path, probe
            return bin_path, probe

    fail("No ffmpeg with the 'subtitles' filter (libass) was found.\n"
         "   Homebrew's default ffmpeg does not include libass.\n"
         "   Fix it with: brew install ffmpeg-full")


def probe_video(path: Path) -> tuple[int, int, float, str]:
    """Return (width, height, fps, fps_fraction) of the video stream."""
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    w, h, rate = out.stdout.split()
    num, den = rate.split("/")
    fps = float(num) / float(den) if float(den) else 25.0
    return int(w), int(h), fps, rate


def video_duration(path: Path) -> float:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def has_audio(path: Path) -> bool:
    """True if the file has at least one audio stream."""
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    return bool(out.stdout.strip())


def filter_escape(path: Path) -> str:
    s = str(path)
    return s.replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")
