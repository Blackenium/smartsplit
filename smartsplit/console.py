"""Terminal helpers: fatal errors and the single-line progress bar."""

from __future__ import annotations

import sys


def fail(msg: str):
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


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
