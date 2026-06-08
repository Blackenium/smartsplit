"""FastAPI application for the SmartSplit web UI."""

import json
import sys
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import DEFAULT_INPUT_DIR, ROOT
from .jobs import JobManager

STATIC_DIR = Path(__file__).resolve().parent / "static"
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm", ".m4v", ".avi"}
BASE_ARGV = [sys.executable, "-u", "-m", "smartsplit"]

app = FastAPI(title="SmartSplit")
manager = JobManager()


@app.on_event("startup")
async def _capture_loop():
    import asyncio
    manager.loop = asyncio.get_event_loop()


# --------------------------------------------------------------------------- #
#  Request models + argv builders
# --------------------------------------------------------------------------- #
class EditorOpts(BaseModel):
    platform: str = "both"
    model: str = "base"
    language: str = "fr"
    reframe: str = "track"
    tiktok_duration: Optional[int] = None
    youtube_duration: Optional[int] = None
    limit: Optional[int] = None
    start: float = 0.0
    keep_clips: bool = False


class SplitReq(EditorOpts):
    video: str


class DownloadReq(EditorOpts):
    source: str                       # youtube | twitch
    channel: str
    latest: Optional[int] = None
    match: Optional[str] = None       # youtube
    kind: str = "vods"                # twitch
    dest: Optional[str] = None
    process: bool = False


def _editor_args(o: EditorOpts) -> List[str]:
    a = ["--platform", o.platform, "--model", o.model,
         "--language", o.language, "--reframe", o.reframe]
    if o.tiktok_duration:
        a += ["--tiktok-duration", str(o.tiktok_duration)]
    if o.youtube_duration:
        a += ["--youtube-duration", str(o.youtube_duration)]
    if o.limit:
        a += ["--limit", str(o.limit)]
    if o.start:
        a += ["--start", str(o.start)]
    if o.keep_clips:
        a += ["--keep-clips"]
    return a


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def _safe_under_root(path: Path) -> Path:
    """Resolve a path and ensure it stays inside the project root."""
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT.resolve()):
        raise HTTPException(403, "Path outside the project root")
    return resolved


def _rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve()))


# --------------------------------------------------------------------------- #
#  API: sources, jobs, clips, media
# --------------------------------------------------------------------------- #
@app.get("/api/videos")
def list_videos():
    """Local source videos available to split (input_videos/ by default)."""
    if not DEFAULT_INPUT_DIR.exists():
        return []
    items = []
    for f in sorted(DEFAULT_INPUT_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() in VIDEO_EXTS:
            items.append({"name": f.name, "path": _rel(f),
                          "size": f.stat().st_size})
    return items


@app.post("/api/split")
def start_split(req: SplitReq):
    video = _safe_under_root(Path(req.video) if Path(req.video).is_absolute()
                             else ROOT / req.video)
    if not video.exists():
        raise HTTPException(404, f"Video not found: {req.video}")
    argv = BASE_ARGV + ["split", str(video)] + _editor_args(req)
    job = manager.create("split", f"split · {video.name}", argv)
    return {"id": job.id}


@app.post("/api/download")
def start_download(req: DownloadReq):
    if req.source not in ("youtube", "twitch"):
        raise HTTPException(400, "source must be 'youtube' or 'twitch'")
    argv = BASE_ARGV + ["download", req.source, req.channel]
    if req.source == "youtube":
        if req.latest:
            argv += ["--latest", str(req.latest)]
        if req.match:
            argv += ["--match", req.match]
    else:
        argv += ["--kind", req.kind]
        if req.latest:
            argv += ["--latest", str(req.latest)]
    if req.dest:
        argv += ["--dest", req.dest]
    if req.process:
        argv += ["--process"] + _editor_args(req)
    title = f"download {req.source} · {req.channel}" + (" + split" if req.process else "")
    job = manager.create("download", title, argv)
    return {"id": job.id}


@app.get("/api/jobs")
def list_jobs():
    return [j.summary() for j in
            sorted(manager.jobs.values(), key=lambda j: j.created, reverse=True)]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = manager.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")
    return {**job.summary(), "events": job.events}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    if job_id not in manager.jobs:
        raise HTTPException(404, "Unknown job")
    return {"cancelled": manager.cancel(job_id)}


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str):
    job = manager.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")

    async def gen():
        async for ev in manager.subscribe(job):
            yield f"data: {json.dumps(ev)}\n\n"
        yield f"data: {json.dumps({'type': 'end'})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/api/clips")
def list_clips():
    """Produced clips: any tiktok/ or youtube/ folder under the project root."""
    groups: dict[str, dict] = {}
    for platform in ("tiktok", "youtube"):
        for clip in sorted(ROOT.rglob(f"{platform}/*.mp4")):
            if "venv" in clip.parts or ".git" in clip.parts:
                continue
            group_dir = clip.parent.parent
            g = groups.setdefault(_rel(group_dir),
                                   {"name": group_dir.name, "clips": []})
            g["clips"].append({"name": clip.name, "platform": platform,
                               "url": f"/media?path={_rel(clip)}"})
    return [{"group": k, **v} for k, v in sorted(groups.items())]


@app.get("/media")
def media(path: str):
    f = _safe_under_root(ROOT / path)
    if not f.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(str(f))


# Static UI (mounted last so /api/* and /media win).
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
