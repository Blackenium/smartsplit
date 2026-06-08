"""Face tracking and 9:16 reframing, plus subtitle burning."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from .. import ffmpeg
from ..config import (DET_WIDTH, LANDSCAPE_STYLE, OUT_H, OUT_W, SAMPLE_FPS,
                      SMOOTH_SECONDS, YUNET_MODEL)
from ..console import step_done, step_progress

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False


def crop_dims(src_w: int, src_h: int) -> tuple[str, int, int]:
    """9:16 crop size within the source. axis='x' (horizontal tracking) for a
    landscape source, 'y' otherwise."""
    target = OUT_W / OUT_H  # 9/16
    if src_w / src_h > target:           # source wider than 9:16 -> crop width
        crop_h = src_h
        crop_w = int(round(src_h * target))
        axis = "x"
    else:                                # source narrower -> crop height
        crop_w = src_w
        crop_h = int(round(src_w / target))
        axis = "y"
    return axis, min(crop_w, src_w), min(crop_h, src_h)


def _moving_average(a: np.ndarray, win: int) -> np.ndarray:
    if win <= 1:
        return a
    if win % 2 == 0:
        win += 1
    pad = win // 2
    ap = np.pad(a, pad, mode="edge")
    return np.convolve(ap, np.ones(win) / win, mode="valid")[:len(a)]


def _make_detector(src_w: int, src_h: int):
    """A YuNet detector sized to a downscaled frame. Returns (detector, det_w,
    det_h, scale) where scale maps detection pixels back to source pixels."""
    det_w = min(DET_WIDTH, src_w)
    scale = det_w / src_w
    det_h = int(round(src_h * scale))
    detector = cv2.FaceDetectorYN.create(
        str(YUNET_MODEL), "", (det_w, det_h),
        score_threshold=0.6, nms_threshold=0.3, top_k=20)
    return detector, det_w, det_h, scale


def _largest_face_center(faces, scale: float):
    """X center (in source pixels) of the biggest detected face, or None."""
    if faces is None or not len(faces):
        return None
    best = max(faces, key=lambda f: float(f[2]) * float(f[3]))
    return (float(best[0]) + float(best[2]) / 2) / scale


def _sample_face_centers(clip: Path, detector, det_w: int, det_h: int,
                         scale: float, step: int):
    """Detect the main face on every `step`-th frame.
    Returns (sample_indices, sample_centers, total_frames)."""
    cap = cv2.VideoCapture(str(clip))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    sample_idx: list[int] = []
    sample_cx: list[float] = []
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % step == 0:
            small = cv2.resize(frame, (det_w, det_h)) if scale != 1 else frame
            _, faces = detector.detect(small)
            cx = _largest_face_center(faces, scale)
            if cx is not None:
                sample_idx.append(i)
                sample_cx.append(cx)
            step_progress("face analysis", i / total)
        i += 1
    cap.release()
    step_done("face analysis")
    return sample_idx, sample_cx, i


def compute_face_track(clip: Path, src_w: int, src_h: int, fps: float):
    """Smoothed face-center path (one value per frame), or None if no face found."""
    if not CV2_AVAILABLE or not YUNET_MODEL.exists():
        return None
    detector, det_w, det_h, scale = _make_detector(src_w, src_h)
    step = max(1, int(round(fps / SAMPLE_FPS)))
    sample_idx, sample_cx, n_frames = _sample_face_centers(
        clip, detector, det_w, det_h, scale, step)
    if not sample_idx:
        return None
    track = np.interp(np.arange(n_frames), sample_idx, sample_cx)
    return _moving_average(track, int(round(fps * SMOOTH_SECONDS)))


def _build_burn_command(clip: Path, ass, out: Path, fps_frac: str,
                        max_duration: int) -> list[str]:
    """ffmpeg command: read raw 1080x1920 BGR frames from stdin, burn the
    subtitles (if any) and remux the clip's audio."""
    vf = ["-vf", f"ass={ffmpeg.filter_escape(ass)}"] if ass is not None else []
    return [ffmpeg.FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pixel_format", "bgr24",
            "-video_size", f"{OUT_W}x{OUT_H}", "-framerate", fps_frac, "-i", "pipe:0",
            "-i", str(clip),
            "-map", "0:v:0", "-map", "1:a:0?", *vf,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-t", str(max_duration), "-shortest", str(out)]


def _crop_frame(frame, axis: str, crop_w: int, crop_h: int, src_w: int, cx: float):
    """Crop one frame to the 9:16 window (tracked on x, centered on y) and resize
    it to the 1080x1920 output canvas."""
    if axis == "x":
        x0 = max(0, min(int(round(cx - crop_w / 2)), src_w - crop_w))
        crop = frame[0:crop_h, x0:x0 + crop_w]
    else:
        y0 = (frame.shape[0] - crop_h) // 2
        crop = frame[y0:y0 + crop_h, 0:crop_w]
    if crop.shape[1] != OUT_W or crop.shape[0] != OUT_H:
        crop = cv2.resize(crop, (OUT_W, OUT_H), interpolation=cv2.INTER_AREA)
    return crop


def _raise_if_ffmpeg_failed(proc):
    if proc.wait() != 0:
        err = proc.stderr.read().decode(errors="replace").strip() if proc.stderr else ""
        last = err.splitlines()[-1] if err else "ffmpeg failed"
        raise RuntimeError(f"ffmpeg (reframe/burn): {last}")


def reframe_and_burn(clip: Path, ass, out: Path, track,
                     src_w: int, src_h: int, fps: float, fps_frac: str, reframe: str,
                     max_duration: int):
    """Stream every frame cropped to 9:16 into ffmpeg, which burns the subtitles
    and remuxes the audio. Capped at max_duration seconds (keyframe splitting can
    overshoot, and YouTube Shorts must stay <= 59s)."""
    axis, crop_w, crop_h = crop_dims(src_w, src_h)
    proc = subprocess.Popen(
        _build_burn_command(clip, ass, out, fps_frac, max_duration),
        stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    cap = cv2.VideoCapture(str(clip))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or (len(track) if track is not None else 1)
    max_frames = int(round(max_duration * fps)) if max_duration else frame_count
    total = min(frame_count, max_frames)
    use_track = (reframe == "track" and track is not None)
    i = 0
    try:
        while i < max_frames:             # do not exceed the platform's target length
            ok, frame = cap.read()
            if not ok:
                break
            cx = track[min(i, len(track) - 1)] if use_track else src_w / 2
            crop = _crop_frame(frame, axis, crop_w, crop_h, src_w, cx)
            proc.stdin.write(np.ascontiguousarray(crop).tobytes())
            i += 1
            if i % 10 == 0:
                step_progress("reframe + subtitles", i / total)
    except BrokenPipeError:
        pass
    finally:
        cap.release()
        try:
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
    _raise_if_ffmpeg_failed(proc)
    step_done("reframe + subtitles")


def burn_only(clip: Path, srt, out: Path, max_duration: int):
    """reframe='none': keep the original aspect ratio, just burn the subtitles.
    Capped at max_duration seconds (see reframe_and_burn)."""
    if srt is None:
        subprocess.run(
            [ffmpeg.FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(clip), "-t", str(max_duration), "-c", "copy", str(out)],
            check=True)
        step_done("copy (no speech)")
        return
    vf = f"subtitles={ffmpeg.filter_escape(srt)}:force_style='{LANDSCAPE_STYLE}'"
    subprocess.run(
        [ffmpeg.FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(clip), "-vf", vf,
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-c:a", "copy", "-t", str(max_duration), str(out)],
        check=True)
    step_done("burning subtitles")
