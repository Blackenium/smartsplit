"""Split a source video into clips up to the platform's max length."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .. import ffmpeg
from ..console import fail, step_done, step_progress


def split_video(video: Path, clips_dir: Path, max_duration: int,
                limit=None, start: float = 0.0) -> list[Path]:
    """Split into clips up to max_duration seconds (stream copy, cut at keyframes).

    start  : second to start reading the source from (useful to skip an intro).
    limit  : only read limit*max_duration seconds from start and keep the first N
             clips - handy for a quick test.
    """
    clips_dir.mkdir(parents=True, exist_ok=True)
    duration = ffmpeg.video_duration(video)
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
    cmd = [ffmpeg.FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
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
