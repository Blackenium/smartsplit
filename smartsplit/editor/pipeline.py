"""Per-video / per-platform orchestration of the editor pipeline."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .. import ffmpeg
from ..config import OUT_H, OUT_W, SILENCE_DB, YOUTUBE_MAX_DURATION
from ..console import fail
from .captions import write_ass, write_srt
from .reframe import burn_only, compute_face_track, reframe_and_burn
from .split import split_video
from .transcribe import transcribe


def load_model(model_name: str):
    """Load a faster-whisper model once (downloaded on first use)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        fail("faster-whisper is not installed. Activate the venv then: "
             "pip install -r requirements.txt")
    print(f"\nLoading Whisper model '{model_name}' "
          "(the model is downloaded on first run)...")
    return WhisperModel(model_name, device="cpu", compute_type="int8")


def resolve_targets(platform: str, tiktok_dur: int, youtube_dur: int):
    """Return [(platform, max_duration), ...] for the requested platform(s),
    warning when the durations look off."""
    if tiktok_dur <= 60:
        print(f"Warning: TikTok duration {tiktok_dur}s <= 60s - TikTok targets clips > 60s.")
    if youtube_dur > YOUTUBE_MAX_DURATION:
        print(f"Warning: YouTube Shorts are <= {YOUTUBE_MAX_DURATION}s - capping "
              f"({youtube_dur}s -> {YOUTUBE_MAX_DURATION}s).")
        youtube_dur = YOUTUBE_MAX_DURATION

    targets = []
    if platform in ("tiktok", "both"):
        targets.append(("tiktok", tiktok_dur))
    if platform in ("youtube", "both"):
        targets.append(("youtube", youtube_dur))
    return targets


def _render_clip(model, clip: Path, out: Path, language, reframe: str,
                 duration: int, tmp: str):
    """Transcribe one raw clip and produce its final vertical/landscape file."""
    captions, _ = transcribe(model, clip, language)
    n = len(captions)

    if reframe == "none":
        srt = Path(tmp) / f"{clip.stem}.srt"
        if n:
            write_srt(captions, srt)
        burn_only(clip, srt if n else None, out, duration)
        return

    src_w, src_h, fps, fps_frac = ffmpeg.probe_video(clip)
    track = None
    if reframe == "track":
        track = compute_face_track(clip, src_w, src_h, fps)
        if track is None:
            print("   no face detected -> center crop")
    ass = Path(tmp) / f"{clip.stem}.ass"
    if n:
        write_ass(captions, ass)
    reframe_and_burn(clip, ass if n else None, out, track,
                     src_w, src_h, fps, fps_frac, reframe, duration)


def process_platform(model, video: Path, platform: str, duration: int,
                     base_out: Path, language, reframe: str, limit, start: float,
                     keep_clips: bool, skip_silent: bool = False) -> tuple[int, int, int]:
    """Split the video to the platform's length and generate the final clips.

    Output: base_out/<platform>/<title>_NN.mp4 (title = source file name).
    Returns (succeeded, skipped, total).
    """
    stem = video.stem
    final_dir = base_out / platform
    final_dir.mkdir(parents=True, exist_ok=True)
    clips_dir = base_out / f".clips_{platform}"

    print(f"\n[{platform}] clips of <= {duration}s  ->  {final_dir}/")
    clips = split_video(video, clips_dir, duration, limit, start)
    pad = max(2, len(str(len(clips))))   # zero-padded index: _01, _02 ... (or _001 if >99)

    ok, skipped = 0, 0
    with tempfile.TemporaryDirectory() as tmp:
        for idx, clip in enumerate(clips, 1):
            out = final_dir / f"{stem}_{idx:0{pad}d}.mp4"
            print(f"[{idx}/{len(clips)}] {out.name}")
            if skip_silent:
                peak = ffmpeg.max_volume(clip)
                if peak <= SILENCE_DB:
                    skipped += 1
                    print(f"   silent clip skipped (peak {peak:.0f} dB)")
                    continue
            try:
                _render_clip(model, clip, out, language, reframe, duration, tmp)
            except Exception as e:
                # A corrupt/unreadable clip must NOT abort the whole video.
                skipped += 1
                detail = str(e).splitlines()[0][:120] if str(e).strip() else type(e).__name__
                print(f"   clip skipped ({detail})")
                out.unlink(missing_ok=True)
                continue
            print(f"   -> {out.name}")
            ok += 1

    if not keep_clips:
        shutil.rmtree(clips_dir, ignore_errors=True)
    return ok, skipped, len(clips)


def process_video(model, video: Path, targets, language, reframe: str,
                  limit, start: float, out_dir, keep_clips: bool,
                  skip_silent: bool = False) -> Path:
    """Run the editor over one source video for every target platform.

    Prints the per-video header and summary. Returns the output directory.
    """
    stem = video.stem
    base_out = out_dir if out_dir else video.parent / f"{stem}_final"
    base_out.mkdir(parents=True, exist_ok=True)

    print(f"\nInput  : {video.name}")
    print(f"Output : {base_out}/")
    if not ffmpeg.has_audio(video):
        print("WARNING: this source has no audio track -> the clips will be SILENT "
              "(if it was downloaded, the audio stream was probably not fetched).")
    print("Targets: " + " | ".join(f"{p} (<= {d}s)" for p, d in targets))
    print(f"Reframe: {reframe} ({OUT_W}x{OUT_H})"
          + (f"  -  quick test ({limit} clip(s))" if limit else ""))

    summary = []
    for platform, dur in targets:
        ok, skipped, total = process_platform(
            model, video, platform, dur, base_out, language, reframe, limit, start,
            keep_clips, skip_silent)
        summary.append((platform, ok, skipped, total))

    print(f"\nDone -> {base_out.name}/")
    for platform, ok, skipped, total in summary:
        line = f"   - {platform:<8}: {ok}/{total} clip(s)"
        if skipped:
            line += f"  ({skipped} skipped)"
        print(line)
    if keep_clips:
        print("   (raw clips kept in .clips_<platform>/)")
    return base_out
