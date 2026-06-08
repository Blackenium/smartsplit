"""Background job manager.

Each job runs a SmartSplit CLI command in a subprocess. Its combined output is
read live (handling both `\\n` finalised lines and `\\r` progress updates) and
turned into a stream of events that the web UI subscribes to over SSE.
"""

from __future__ import annotations

import asyncio
import codecs
import itertools
import os
import subprocess
import threading
import time

from ..config import ROOT


def _split_segments(buf: str):
    """Yield (text, transient) for each complete segment in buf, returning the
    trailing partial. A segment ending in '\\r' is transient (a progress line);
    one ending in '\\n' is a finalised line."""
    segments = []
    while True:
        i_r = buf.find("\r")
        i_n = buf.find("\n")
        if i_r == -1 and i_n == -1:
            break
        if i_n == -1 or (i_r != -1 and i_r < i_n):
            idx, transient = i_r, True
        else:
            idx, transient = i_n, False
        segments.append((buf[:idx], transient))
        buf = buf[idx + 1:]
    return segments, buf


class Job:
    def __init__(self, job_id: str, kind: str, title: str, argv: list[str], loop):
        self.id = job_id
        self.kind = kind
        self.title = title
        self.argv = argv
        self.status = "running"          # running | succeeded | failed | cancelled
        self.returncode: int | None = None
        self.created = time.time()
        self.events: list[dict] = []
        self.subscribers: set[asyncio.Queue] = set()
        self.proc: subprocess.Popen | None = None
        self._loop = loop
        self._lock = threading.Lock()

    def summary(self) -> dict:
        return {"id": self.id, "kind": self.kind, "title": self.title,
                "status": self.status, "returncode": self.returncode,
                "created": self.created}

    def emit(self, event: dict):
        with self._lock:
            self.events.append(event)
            subs = list(self.subscribers)
        for q in subs:
            try:
                self._loop.call_soon_threadsafe(q.put_nowait, event)
            except RuntimeError:
                pass


class JobManager:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self._ids = itertools.count(1)
        self.loop = None                 # set on app startup

    def create(self, kind: str, title: str, argv: list[str]) -> Job:
        job = Job(str(next(self._ids)), kind, title, argv, self.loop)
        self.jobs[job.id] = job
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def cancel(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if job and job.proc and job.status == "running":
            job.proc.terminate()
            return True
        return False

    def _run(self, job: Job):
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        try:
            job.proc = subprocess.Popen(
                job.argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=str(ROOT), env=env)
        except OSError as e:
            job.emit({"type": "log", "text": f"failed to start: {e}", "transient": False})
            job.status = "failed"
            job.emit({"type": "status", "status": job.status, "returncode": -1})
            return

        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        buf = ""
        while True:
            data = job.proc.stdout.read1(4096)
            if not data:
                break
            buf += decoder.decode(data)
            segments, buf = _split_segments(buf)
            for text, transient in segments:
                if transient and not text.strip():
                    continue
                job.emit({"type": "log", "text": text, "transient": transient})
        if buf.strip():
            job.emit({"type": "log", "text": buf, "transient": False})

        job.returncode = job.proc.wait()
        if job.status != "cancelled":
            job.status = "succeeded" if job.returncode == 0 else "failed"
        job.emit({"type": "status", "status": job.status, "returncode": job.returncode})

    async def subscribe(self, job: Job):
        """Async generator: replay past events, then stream live ones until the
        job finishes and its queue drains."""
        q: asyncio.Queue = asyncio.Queue()
        with job._lock:
            backlog = list(job.events)
            job.subscribers.add(q)
        try:
            for ev in backlog:
                yield ev
            while True:
                if job.status != "running" and q.empty():
                    break
                try:
                    yield await asyncio.wait_for(q.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
        finally:
            with job._lock:
                job.subscribers.discard(q)
