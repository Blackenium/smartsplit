"""Command-line interface for SmartSplit.

Subcommands:
  split     turn a local video into vertical 9:16 clips (the original tool)
  download  fetch source videos from YouTube or Twitch (optionally --process)
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import ffmpeg
from .config import (DEFAULT_INPUT_DIR, DEFAULT_LANGUAGE, DEFAULT_MODEL,
                     DEFAULT_TIKTOK_DURATION, YOUTUBE_MAX_DURATION)
from .console import fail
from .editor import pipeline
from .editor.reframe import CV2_AVAILABLE
from .config import YUNET_MODEL
from .scrapers import twitch, youtube


# --------------------------------------------------------------------------- #
#  Shared editor options (used by `split` and by `download --process`)
# --------------------------------------------------------------------------- #
def add_editor_args(parser: argparse.ArgumentParser):
    parser.add_argument("--platform", choices=["tiktok", "youtube", "both"], default="both",
                        help="Platform(s) to generate (default: both). "
                             "TikTok = long clips (> 60s), YouTube = Shorts (<= 59s)")
    parser.add_argument("--tiktok-duration", type=int, default=None, metavar="SECONDS",
                        help=f"Max length of a TikTok clip, should be > 60 "
                             f"(default: {DEFAULT_TIKTOK_DURATION})")
    parser.add_argument("--youtube-duration", type=int, default=YOUTUBE_MAX_DURATION,
                        metavar="SECONDS",
                        help=f"Max length of a YouTube Shorts clip, capped at "
                             f"{YOUTUBE_MAX_DURATION} (default: {YOUTUBE_MAX_DURATION})")
    parser.add_argument("--max-duration", type=int, default=None, metavar="SECONDS",
                        help="(deprecated) alias for --tiktok-duration")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"Whisper model (default: {DEFAULT_MODEL}). "
                             "tiny/base = fast, small = better for French")
    parser.add_argument("--language", default=DEFAULT_LANGUAGE,
                        help=f"Language code or 'auto' (default: {DEFAULT_LANGUAGE})")
    parser.add_argument("--reframe", choices=["track", "center", "none"], default="track",
                        help="track = follow the face in 9:16 (default), "
                             "center = fixed center 9:16 crop, none = keep original")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Quick test: only process the first N clips "
                             "(and only read the start of the source)")
    parser.add_argument("--start", type=float, default=0.0, metavar="SECONDS",
                        help="Start reading the source at this second "
                             "(e.g. to skip an intro during a quick test)")
    parser.add_argument("--keep-clips", action="store_true",
                        help="Keep the intermediate raw clip folders")
    parser.add_argument("--skip-silent", action="store_true",
                        help="Skip clips with no real audio (dead air, 'starting "
                             "soon'/BRB screens, DMCA-muted sections)")


def _editor_targets(args):
    """Resolve per-platform durations and the validated target list."""
    tiktok_dur = args.tiktok_duration or args.max_duration or DEFAULT_TIKTOK_DURATION
    return pipeline.resolve_targets(args.platform, tiktok_dur, args.youtube_duration)


def _check_reframe(reframe: str):
    if reframe == "track" and not CV2_AVAILABLE:
        fail("OpenCV is required for face tracking: pip install -r requirements.txt\n"
             "   (or use --reframe center / --reframe none)")
    if reframe == "track" and not YUNET_MODEL.exists():
        fail(f"Face-detection model not found: {YUNET_MODEL}\n"
             "   Re-download it (see README) or use --reframe center.")


# --------------------------------------------------------------------------- #
#  split
# --------------------------------------------------------------------------- #
def cmd_split(args):
    ffmpeg.resolve()
    if not args.video.exists():
        fail(f"File not found: {args.video}")
    _check_reframe(args.reframe)

    targets = _editor_targets(args)
    language = None if args.language == "auto" else args.language
    print(f"ffmpeg : {ffmpeg.FFMPEG}")
    model = pipeline.load_model(args.model)
    pipeline.process_video(model, args.video, targets, language, args.reframe,
                           args.limit, args.start, args.out_dir, args.keep_clips,
                           args.skip_silent)


# --------------------------------------------------------------------------- #
#  download (youtube / twitch), optionally chaining into the editor
# --------------------------------------------------------------------------- #
def _process_downloads(videos: list[Path], args):
    """Run the editor over freshly downloaded videos (download --process)."""
    if not videos:
        print("Nothing downloaded - nothing to process.")
        return
    _check_reframe(args.reframe)
    targets = _editor_targets(args)
    language = None if args.language == "auto" else args.language
    model = pipeline.load_model(args.model)
    for video in videos:
        pipeline.process_video(model, video, targets, language, args.reframe,
                               args.limit, args.start, None, args.keep_clips,
                               args.skip_silent)


def cmd_download(args):
    ffmpeg.resolve()
    dest = args.dest or DEFAULT_INPUT_DIR
    if args.source == "youtube":
        videos = youtube.download(args.channel, dest,
                                  latest=args.latest, match=args.match)
    else:
        videos = twitch.download(args.channel, dest,
                                 kind=args.kind, latest=args.latest)

    print(f"\nDownloaded {len(videos)} file(s) -> {dest}/")
    for v in videos:
        print(f"   - {v.name}")

    if args.process:
        _process_downloads(videos, args)


# --------------------------------------------------------------------------- #
#  web (FastAPI UI)
# --------------------------------------------------------------------------- #
def cmd_web(args):
    try:
        import uvicorn
    except ImportError:
        fail("FastAPI/uvicorn are not installed. Activate the venv then: "
             "pip install -r requirements.txt")
    from .web.app import app
    print(f"SmartSplit web UI -> http://{args.host}:{args.port}  (Ctrl-C to stop)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


# --------------------------------------------------------------------------- #
#  Parser
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smartsplit",
        description="Download source videos (YouTube/Twitch) and turn long "
                    "landscape videos into vertical 9:16 clips with face tracking "
                    "and auto subtitles.")
    sub = parser.add_subparsers(dest="command", required=True)

    # split
    p_split = sub.add_parser(
        "split", help="Split a local video into 9:16 clips (face tracking + subtitles)")
    p_split.add_argument("video", type=Path, help="Input video")
    p_split.add_argument("--out-dir", type=Path, default=None,
                         help="Output directory (default: <video>_final). The tiktok/ "
                              "and youtube/ subfolders are created inside it.")
    add_editor_args(p_split)
    p_split.set_defaults(func=cmd_split)

    # download
    p_dl = sub.add_parser(
        "download", help="Download source videos from YouTube or Twitch")
    dl_sub = p_dl.add_subparsers(dest="source", required=True)

    p_yt = dl_sub.add_parser("youtube", help="Download from a YouTube channel")
    p_yt.add_argument("channel", help="@handle, channel/video URL, or channel name")
    p_yt.add_argument("--latest", type=int, default=None, metavar="N",
                      help="Download the N most recent uploads (default: 1)")
    p_yt.add_argument("--match", default=None, metavar="TEXT",
                      help="Only videos whose title contains TEXT "
                           f"(scans the latest {youtube.MATCH_SCAN_WINDOW} uploads)")

    p_tw = dl_sub.add_parser("twitch", help="Download from a Twitch channel")
    p_tw.add_argument("channel", help="Channel login, URL, or name")
    p_tw.add_argument("--kind", choices=list(twitch.KINDS), default="vods",
                      help="vods (default), clips, or all")
    p_tw.add_argument("--latest", type=int, default=None, metavar="N",
                      help="Download the N most recent items (default: 1)")

    for p in (p_yt, p_tw):
        p.add_argument("--dest", type=Path, default=None,
                       help=f"Download directory (default: {DEFAULT_INPUT_DIR})")
        p.add_argument("--process", action="store_true",
                       help="Split the downloaded videos into clips right away")
        add_editor_args(p)
        p.set_defaults(func=cmd_download)

    # web
    p_web = sub.add_parser("web", help="Launch the web UI (FastAPI)")
    p_web.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p_web.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    p_web.set_defaults(func=cmd_web)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
