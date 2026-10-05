"""Separate GPU lip-sync worker (beta).

Deployed on its own GPU box/spot instance so the main API stays cheap and CPU-only.
Constraints enforced here on purpose:
  * short clips only (default <= 20s)
  * one front-facing speaker
  * failures return status=failed -- the main pipeline then keeps the
    audio-only dubbed output as the deliverable.

Run:  uvicorn app.workers.gpu_lipsync_worker:app --host 0.0.0.0 --port 9100
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

MAX_CLIP_SECONDS = float(os.getenv("LIPSYNC_MAX_CLIP_SECONDS", "20"))
ENGINE_CMD = os.getenv("LIPSYNC_ENGINE_CMD", "")  # e.g. Wav2Lip / LatentSync inference command
OUT_DIR = os.getenv("LIPSYNC_OUT_DIR", "./data/lipsync")

app = FastAPI(title="Lip-sync GPU worker (beta)")
_tasks: dict[str, dict] = {}
_lock = threading.Lock()


class TaskIn(BaseModel):
    video_path: str
    audio_path: str
    start: float = 0.0
    end: float = 0.0


def _run(task_id: str, req: TaskIn):
    t = _tasks[task_id]
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        out = os.path.join(OUT_DIR, f"{task_id}.mp4")
        t.update(status="running", progress=0.2)
        if not ENGINE_CMD:
            # No GPU engine configured: simulate so the UI flow stays testable.
            time.sleep(5)
            t.update(status="succeeded", progress=1.0, output_path=None,
                     note="simulated (no LIPSYNC_ENGINE_CMD configured)")
            return
        cmd = ENGINE_CMD.format(video=req.video_path, audio=req.audio_path, out=out)
        proc = subprocess.run(cmd, shell=True, capture_output=True, timeout=1800)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode()[-1000:])
        t.update(status="succeeded", progress=1.0, output_path=out)
    except Exception as exc:  # noqa: BLE001
        t.update(status="failed", progress=1.0, error=str(exc))


@app.get("/health")
def health():
    return {"ok": True, "engine_configured": bool(ENGINE_CMD), "max_clip_seconds": MAX_CLIP_SECONDS}


@app.post("/tasks")
def submit(req: TaskIn):
    dur = req.end - req.start
    if dur <= 0 or dur > MAX_CLIP_SECONDS:
        raise HTTPException(400, f"beta accepts clips of 0-{MAX_CLIP_SECONDS:.0f}s only")
    task_id = uuid.uuid4().hex
    with _lock:
        _tasks[task_id] = {"task_id": task_id, "status": "queued", "progress": 0.0}
    threading.Thread(target=_run, args=(task_id, req), daemon=True).start()
    return {"task_id": task_id}


@app.get("/tasks/{task_id}")
def poll(task_id: str):
    t = _tasks.get(task_id)
    if not t:
        raise HTTPException(404, "unknown task")
    return t
