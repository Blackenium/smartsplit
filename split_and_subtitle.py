#!/usr/bin/env python3
"""Backward-compatible entry point for SmartSplit.

The tool was reorganised into the `smartsplit` package. This shim keeps the old
command working:

    python3 split_and_subtitle.py "video.mp4" --platform tiktok

is mapped to the new `split` subcommand. Prefer the package entry point:

    python3 -m smartsplit split "video.mp4" --platform tiktok
    python3 -m smartsplit download youtube "@channel" --latest 10 --process
"""

import sys

from smartsplit.cli import main

if __name__ == "__main__":
    argv = sys.argv[1:]
    # Old usage put the video first; route it to the `split` subcommand.
    if argv and argv[0] not in ("split", "download", "-h", "--help"):
        argv = ["split", *argv]
    main(argv)
