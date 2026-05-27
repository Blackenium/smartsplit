#!/usr/bin/env python3
"""SmartSplit - turn a long landscape video into short vertical (9:16) clips with
dynamic face tracking and burned-in subtitles (faster-whisper).

Outputs are organised per platform: TikTok (clips longer than 60s) and/or
YouTube Shorts (clips of 59s or less). Each platform gets its own subfolder
(tiktok/, youtube/) and clips named "<video title>_01.mp4", "<title>_02.mp4", ...

Per video and per platform:
  1. Split into clips up to the platform's max length (stream copy, one pass).
  2. Transcribe each clip with faster-whisper into short captions.
  3. Reframe to 9:16:
       - "track"  : detect the main face on sampled frames, smooth the path,
                    and crop following the face (falls back to center crop).
       - "center" : fixed center crop.
       - "none"   : keep the original aspect ratio.
  4. Burn subtitles and remux audio (single re-encode through a pipe).

The Whisper model is loaded once and reused for every clip.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

# Keep output clean: silence numpy (matmul) and Hugging Face Hub warnings.
warnings.filterwarnings("ignore")
for _name in ("faster_whisper", "huggingface_hub"):
    logging.getLogger(_name).setLevel(logging.ERROR)

import numpy as np
np.seterr(all="ignore")

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

DEFAULT_TIKTOK_DURATION = 90    # TikTok clips: should be longer than 60s
YOUTUBE_MAX_DURATION = 59       # YouTube Shorts: platform limit (59s or less)
DEFAULT_MODEL = "base"          # tiny | base | small | medium | large-v3
DEFAULT_LANGUAGE = "fr"         # ISO code (e.g. "fr", "en") or "auto"

PLATFORMS = ("tiktok", "youtube")

OUT_W, OUT_H = 1080, 1920       # vertical 9:16
DET_WIDTH = 640                 # face-detection width (downscale = faster)
SAMPLE_FPS = 5                  # face detections per second
SMOOTH_SECONDS = 0.6            # smoothing window for the face path

YUNET_MODEL = Path(__file__).resolve().parent / "models" / "face_detection_yunet_2023mar.onnx"

# Vertical subtitles: karaoke ASS (the spoken word turns red), rendered on an
# explicit 1080x1920 canvas, so font size and margins are in output pixels.
ASS_FONT = "Arial"
ASS_FONTSIZE = 74           # font size on a PlayResY=1920 canvas
ASS_OUTLINE = 3             # black outline thickness
ASS_MARGIN_LR = 90          # left/right margins (px)
ASS_MARGIN_V = 350          # distance from the bottom (px)
HIGHLIGHT_COLOUR = "&H0000FF&"   # red - ASS \1c format is Blue,Green,Red
LANDSCAPE_STYLE = "FontName=Arial,FontSize=24,Outline=1,Shadow=0,MarginV=20"

# Subtitles are re-chunked into short captions so no more than two lines are
# ever shown on screen at once.
MAX_CAPTION_CHARS = 30      # max length of a caption (about two lines)
MAX_CAPTION_WORDS = 6
MAX_CAPTION_SECONDS = 3.5
LINE_MAX_CHARS = 15         # target length of a single line (two-line balancing)

# Resolved at startup: an ffmpeg built with libass.
FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


def fail(msg: str):
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


# --------------------------------------------------------------------------- #
#  ffmpeg detection (libass)
# --------------------------------------------------------------------------- #
def _has_subtitles_filter(ffmpeg_bin: str) -> bool:
    try:
        out = subprocess.run([ffmpeg_bin, "-hide_banner", "-filters"],
                             capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    return any(len(p) >= 2 and p[1] == "subtitles"
               for p in (line.split() for line in out.stdout.splitlines()))


def resolve_ffmpeg() -> tuple[str, str]:
    """Find an ffmpeg with libass and its matching ffprobe.

    Preference order: FFMPEG env var, Homebrew's ffmpeg-full (which ships
    libass), then ffmpeg on PATH.
    """
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
            return bin_path, probe

    fail("No ffmpeg with the 'subtitles' filter (libass) was found.\n"
         "   Homebrew's default ffmpeg does not include libass.\n"
         "   Fix it with: brew install ffmpeg-full")


# --------------------------------------------------------------------------- #
#  Terminal progress bar
# --------------------------------------------------------------------------- #
def _bar(frac: float, width: int = 22) -> str:
    frac = max(0.0, min(1.0, frac))
    filled = int(frac * width)
    return "#" * filled + "-" * (width - filled)


def step_progress(label: str, frac: float):
    sys.stdout.write(f"\r   {label:<24} [{_bar(frac)}] {min(frac, 1.0) * 100:3.0f}%")
    sys.stdout.flush()


def step_done(label: str):
    sys.stdout.write(f"\r   {label:<24} [{_bar(1.0)}] 100% done\n")
    sys.stdout.flush()


# --------------------------------------------------------------------------- #
#  Probing / splitting
# --------------------------------------------------------------------------- #
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


def split_video(video: Path, clips_dir: Path, max_duration: int,
                limit=None, start: float = 0.0) -> list[Path]:
    """Split into clips up to max_duration seconds (stream copy, cut at keyframes).

    start  : second to start reading the source from (useful to skip an intro).
    limit  : only read limit*max_duration seconds from start and keep the first N
             clips - handy for a quick test.
    """
    clips_dir.mkdir(parents=True, exist_ok=True)
    duration = video_duration(video)
    if start >= duration:
        fail(f"--start {start:.0f}s is past the end of the video ({duration:.0f}s).")
    avail = duration - start
    process_dur = min(avail, limit * max_duration) if limit else avail
    estimate = int(process_dur // max_duration) + (1 if process_dur % max_duration else 0)
    if limit:
        estimate = min(estimate, limit)
    note = (f"  (quick test: {process_dur:.0f}s"
            + (f" from {start:.0f}s" if start else "") + ")") if limit else ""
    print(f"Total duration: {duration:.0f}s{note}  ->  ~{estimate} clip(s) of <= {max_duration}s")

    pattern = str(clips_dir / "clip_%03d.mp4")
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
           "-progress", "pipe:1", "-nostats"]
    if start:
        cmd += ["-ss", str(start)]
    cmd += ["-i", str(video)]
    if limit:
        cmd += ["-t", str(limit * max_duration)]
    cmd += ["-map", "0", "-c", "copy",
            "-f", "segment", "-segment_time", str(max_duration),
            "-reset_timestamps", "1", pattern]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in proc.stdout:
        line = line.strip()
        if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
            try:
                sec = int(line.split("=", 1)[1]) / 1_000_000
                step_progress("splitting", sec / process_dur)
            except ValueError:
                pass
    if proc.wait() != 0:
        fail("ffmpeg split failed:\n" + proc.stderr.read())
    step_done("splitting")

    clips = sorted(clips_dir.glob("clip_*.mp4"))
    if limit:
        clips = clips[:limit]
    if not clips:
        fail("ffmpeg produced no clips.")
    print(f"{len(clips)} clip(s) created\n")
    return clips


# --------------------------------------------------------------------------- #
#  Transcription and caption building
# --------------------------------------------------------------------------- #
def srt_timestamp(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _split_two_lines(tokens: list[str]) -> int:
    """Index where to break a caption into two balanced lines. 0 = single line."""
    if len(tokens) < 2 or len(" ".join(tokens)) <= LINE_MAX_CHARS:
        return 0
    best_i, best_diff = 1, None
    for i in range(1, len(tokens)):
        diff = abs(len(" ".join(tokens[:i])) - len(" ".join(tokens[i:])))
        if best_diff is None or diff < best_diff:
            best_diff, best_i = diff, i
    return best_i


def _merge_words(words):
    """faster-whisper words -> (start, end, text), re-gluing elisions and attached
    punctuation (t + 'es -> t'es ; l' + eau -> l'eau ; word + , -> word,)."""
    out: list[tuple[float, float, str]] = []
    for w in words:
        txt = w.word.strip()
        if not txt:
            continue
        glue_to_prev = out and (
            txt[0] in "'’,.!?;:…)»"      # starts with apostrophe/punctuation
            or out[-1][2][-1] in "'’("            # or previous ends with an apostrophe
        )
        if glue_to_prev:
            ps, _, pt = out[-1]
            out[-1] = (ps, w.end, pt + txt)
        else:
            out.append((w.start, w.end, txt))
    return out


def _chunk_words(merged):
    """Group (start, end, word) tuples into captions (list of word lists)."""
    captions, buf = [], []

    def chars():
        return sum(len(t) for _, _, t in buf) + max(0, len(buf) - 1)

    def flush():
        if buf:
            captions.append(buf.copy())
        buf.clear()

    for s, e, txt in merged:
        if buf and (
            chars() + 1 + len(txt) > MAX_CAPTION_CHARS
            or len(buf) >= MAX_CAPTION_WORDS
            or (e - buf[0][0]) > MAX_CAPTION_SECONDS
        ):
            flush()
        buf.append((s, e, txt))
        if txt.endswith((".", "!", "?", "…", ":")):
            flush()
    flush()
    return captions


def transcribe(model, clip: Path, language) -> tuple[list, str]:
    """Transcribe a clip into short captions. Returns (captions, language).

    captions: list of captions; each caption is a list of (start, end, word).
    """
    segments, info = model.transcribe(str(clip), language=language, beam_size=5,
                                      vad_filter=True, word_timestamps=True)
    dur = info.duration or 1.0
    captions = []
    for seg in segments:
        step_progress("transcribing", seg.end / dur)
        if seg.words:
            captions.extend(_chunk_words(_merge_words(seg.words)))
        elif seg.text.strip():            # fallback if no word timestamps
            captions.append([(seg.start, seg.end, seg.text.strip())])
    step_done("transcribing")
    return captions, info.language


def _layout(cap):
    """(word list, two-line break index) for a caption."""
    tokens = [t for _, _, t in cap]
    return tokens, _split_two_lines(tokens)


def write_srt(captions, path: Path):
    """Write captions as SRT (two lines max), one entry per caption."""
    blocks = []
    for i, cap in enumerate(captions, 1):
        tokens, brk = _layout(cap)
        text = " ".join(tokens) if not brk else \
            " ".join(tokens[:brk]) + "\n" + " ".join(tokens[brk:])
        blocks.append(
            f"{i}\n{srt_timestamp(cap[0][0])} --> {srt_timestamp(cap[-1][1])}\n{text}\n")
    path.write_text("\n".join(blocks), encoding="utf-8")


def _ass_ts(seconds: float) -> str:
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def write_ass(captions, path: Path):
    """Write a karaoke ASS file: the word being spoken is red, the others white;
    one event per word, at most two balanced lines."""
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {OUT_W}
PlayResY: {OUT_H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{ASS_FONT},{ASS_FONTSIZE},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{ASS_OUTLINE},0,2,{ASS_MARGIN_LR},{ASS_MARGIN_LR},{ASS_MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, Effect, Text
"""
    events = []
    for cap in captions:
        tokens, brk = _layout(cap)
        n = len(cap)
        for i in range(n):
            start = cap[i][0]
            end = cap[i + 1][0] if i + 1 < n else cap[i][1]
            if end <= start:
                end = start + 0.08
            rendered = [
                (r"{\1c" + HIGHLIGHT_COLOUR + r"}" + tok + r"{\1c&HFFFFFF&}")
                if j == i else tok
                for j, tok in enumerate(tokens)
            ]
            text = " ".join(rendered) if not brk else \
                " ".join(rendered[:brk]) + r"\N" + " ".join(rendered[brk:])
            events.append(
                f"Dialogue: 0,{_ass_ts(start)},{_ass_ts(end)},Default,,0,0,0,,{text}")
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
