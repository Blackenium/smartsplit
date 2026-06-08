"""Shared configuration constants for SmartSplit.

All tunables live here so the editor pipeline and the CLI read the same values.
"""

from __future__ import annotations

from pathlib import Path

# Project root (the repo directory that holds models/ and input_videos/).
ROOT = Path(__file__).resolve().parent.parent

DEFAULT_TIKTOK_DURATION = 90    # TikTok clips: should be longer than 60s
YOUTUBE_MAX_DURATION = 59       # YouTube Shorts: platform limit (59s or less)
DEFAULT_MODEL = "base"          # tiny | base | small | medium | large-v3
DEFAULT_LANGUAGE = "fr"         # ISO code (e.g. "fr", "en") or "auto"

PLATFORMS = ("tiktok", "youtube")

# A clip whose loudest moment is below this is treated as silent (dead air,
# "starting soon" screens, DMCA-muted sections). Used by --skip-silent.
SILENCE_DB = -50.0

# Where downloaded source videos land by default.
DEFAULT_INPUT_DIR = ROOT / "input_videos"

OUT_W, OUT_H = 1080, 1920       # vertical 9:16
DET_WIDTH = 640                 # face-detection width (downscale = faster)
SAMPLE_FPS = 5                  # face detections per second
SMOOTH_SECONDS = 0.6            # smoothing window for the face path

YUNET_MODEL = ROOT / "models" / "face_detection_yunet_2023mar.onnx"

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
