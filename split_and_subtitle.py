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
