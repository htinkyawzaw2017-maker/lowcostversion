"""Client for the separate GPU lip-sync worker (beta).

The GPU worker is a standalone service (see workers/gpu_lipsync_worker.py).
It only accepts SHORT clips with a single front-facing speaker. If it fails,
the pipeline keeps the audio-only dubbed output as the deliverable.
"""
from __future__ import annotations

import httpx

from app.core.config import get_settings


class GpuLipSyncClient:
    name = "gpu-worker"

    def __init__(self):
        self.base = get_settings().lipsync_worker_url.rstrip("/")

    def submit(self, video_path: str, audio_path: str, start: float, end: float) -> str:
        r = httpx.post(
            f"{self.base}/tasks",
            json={"video_path": video_path, "audio_path": audio_path,
                  "start": start, "end": end},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["task_id"]

    def poll(self, task_id: str) -> dict:
        r = httpx.get(f"{self.base}/tasks/{task_id}", timeout=30)
        r.raise_for_status()
        return r.json()
