from __future__ import annotations

import os
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.secrets import secrets_status
from app.core.security import require_user
from app.models import Artifact, Job, JobStatus, Project, Segment, TaskStatus
from app.providers import registry
from app.services.storage import LocalStorage, storage

router = APIRouter(dependencies=[Depends(require_user)])


# ----------------------------------------------------------------- schemas
class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    source_lang: str = "en"
    target_lang: str = "my"
    filename: str | None = None
    content_type: str = "video/mp4"


class ProjectUpdate(BaseModel):
    title: str | None = None
    source_lang: str | None = None
    target_lang: str | None = None
    settings: dict | None = None


class SegmentUpdate(BaseModel):
    start: float | None = None
    end: float | None = None
    dub_text: str | None = None
    translated_text: str | None = None
    source_text: str | None = None
    voice: str | None = None
    speed: float | None = Field(default=None, ge=0.5, le=2.0)
    emotion: str | None = None
    speaker: str | None = None
    locked: bool | None = None


class JobCreate(BaseModel):
    kind: str = "pipeline"
    params: dict = Field(default_factory=dict)


def _seg_out(s: Segment) -> dict:
    return {
        "id": s.id, "index": s.index, "start": s.start, "end": s.end,
        "speaker": s.speaker, "source_text": s.source_text,
        "translated_text": s.translated_text, "dub_text": s.dub_text,
        "emotion": s.emotion, "voice": s.voice, "speed": s.speed, "locked": s.locked,
        "audio_url": f"/api/segments/{s.id}/audio" if s.audio_key else None,
        "audio_duration": s.audio_duration, "target_duration": round(s.target_duration, 3),
        "drift": s.drift, "fit": s.fit, "tts_provider": s.tts_provider,
    }


def _job_out(j: Job) -> dict:
    return {
        "id": j.id, "project_id": j.project_id, "kind": j.kind, "status": j.status.value,
        "progress": j.progress, "stage": j.stage, "error": j.error,
        "logs": (j.logs or [])[-40:], "attempts": j.attempts,
        "created_at": j.created_at.isoformat(), "updated_at": j.updated_at.isoformat(),
    }


def _project_out(p: Project, detail: bool = False) -> dict:
    data = {
        "id": p.id, "title": p.title, "source_lang": p.source_lang,
        "target_lang": p.target_lang, "status": p.status.value,
        "duration_sec": p.duration_sec, "settings": p.settings or {},
        "segment_count": len(p.segments), "has_source": bool(p.source_key),
        "created_at": p.created_at.isoformat(),
        "artifacts": [
            {"kind": a.kind, "bytes": a.bytes, "meta": a.meta,
             "url": f"/api/projects/{p.id}/artifacts/{a.kind}"}
            for a in p.artifacts
        ],
    }
    if detail:
        data["segments"] = [_seg_out(s) for s in p.segments]
        data["jobs"] = [_job_out(j) for j in p.jobs[-10:]]
    return data


def _get_project(db: Session, pid: str) -> Project:
    p = db.get(Project, pid)
    if not p:
        raise HTTPException(404, "project not found")
    return p


# ----------------------------------------------------------------- system
@router.get("/health")
def health():
    return {"ok": True}


@router.get("/config")
def config():
    """Non-secret runtime info for the UI. Never returns key material."""
    s = get_settings()
    return {
        "app_name": s.app_name,
        "providers": registry.describe(),
        "secrets": secrets_status(),
        "lipsync": {"beta": True, "max_clip_seconds": s.lipsync_max_clip_seconds},
        "storage": s.provider_storage,
        "mock_mode": all(
            v.get("configured") == "mock"
            for k, v in registry.describe().items()
            if k not in ("storage", "tts_fallback")
        ),
    }


# ----------------------------------------------------------------- projects
@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    rows = db.query(Project).order_by(Project.created_at.desc()).all()
    return [_project_out(p) for p in rows]


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    p = Project(title=body.title, source_lang=body.source_lang, target_lang=body.target_lang,
                settings={"mix_original_db": -18.0, "burn_subtitles": False})
    db.add(p)
    db.commit()
    out = _project_out(p)
    if body.filename:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", body.filename)[-120:]
        key = f"{p.id}/source/{safe}"
        pre = storage().presign_upload(key, body.content_type)
        p.source_key = key
        p.status = JobStatus.uploading
        db.commit()
        out = _project_out(p)
        out["upload"] = pre.__dict__
    return out


@router.get("/projects/{pid}")
def get_project(pid: str, db: Session = Depends(get_db)):
    return _project_out(_get_project(db, pid), detail=True)


@router.patch("/projects/{pid}")
def update_project(pid: str, body: ProjectUpdate, db: Session = Depends(get_db)):
    p = _get_project(db, pid)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(p, k, {**(p.settings or {}), **v} if k == "settings" else v)
    db.commit()
    return _project_out(p, detail=True)


@router.delete("/projects/{pid}", status_code=204)
def delete_project(pid: str, db: Session = Depends(get_db)):
    db.delete(_get_project(db, pid))
    db.commit()


@router.post("/projects/{pid}/upload-url")
def upload_url(pid: str, filename: str, content_type: str = "video/mp4",
               db: Session = Depends(get_db)):
    """Presigned S3 PUT -- the video never transits the API server."""
    p = _get_project(db, pid)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)[-120:]
    key = f"{p.id}/source/{safe}"
    pre = storage().presign_upload(key, content_type)
    p.source_key, p.status = key, JobStatus.uploading
    db.commit()
    return pre.__dict__


@router.post("/projects/{pid}/upload-complete")
def upload_complete(pid: str, db: Session = Depends(get_db)):
    p = _get_project(db, pid)
    if not p.source_key or not storage().exists(p.source_key):
        raise HTTPException(400, "source object not found in storage")
    p.status = JobStatus.created
    db.commit()
    return _project_out(p)


# ----------------------------------------------------------------- segments
@router.get("/projects/{pid}/segments")
def list_segments(pid: str, db: Session = Depends(get_db)):
    return [_seg_out(s) for s in _get_project(db, pid).segments]


@router.patch("/segments/{sid}")
def update_segment(sid: str, body: SegmentUpdate, db: Session = Depends(get_db)):
    s = db.get(Segment, sid)
    if not s:
        raise HTTPException(404, "segment not found")
    data = body.model_dump(exclude_none=True)
    for k, v in data.items():
        setattr(s, k, v)
    if any(k in data for k in ("dub_text", "voice", "speed", "emotion", "start", "end")):
        s.locked = data.get("locked", True)
    if s.end < s.start:
        raise HTTPException(400, "end must be after start")
    db.commit()
    return _seg_out(s)


@router.post("/segments/{sid}/resynthesize", status_code=202)
def resynthesize(sid: str, db: Session = Depends(get_db)):
    s = db.get(Segment, sid)
    if not s:
        raise HTTPException(404, "segment not found")
    job = Job(project_id=s.project_id, kind="tts", params={"segment_ids": [s.id]},
              status=TaskStatus.pending, logs=[])
    db.add(job)
    db.commit()
    return _job_out(job)


@router.get("/segments/{sid}/audio")
def segment_audio(sid: str, db: Session = Depends(get_db)):
    s = db.get(Segment, sid)
    if not s or not s.audio_key:
        raise HTTPException(404, "no audio for this segment")
    st = storage()
    if isinstance(st, LocalStorage):
        return FileResponse(st.path(s.audio_key), media_type="audio/wav")
    return RedirectResponse(st.presign_download(s.audio_key))


# ----------------------------------------------------------------- jobs
@router.post("/projects/{pid}/jobs", status_code=202)
def create_job(pid: str, body: JobCreate, db: Session = Depends(get_db)):
    p = _get_project(db, pid)
    if body.kind not in ("pipeline", "tts", "render", "recap", "lipsync"):
        raise HTTPException(400, "unknown job kind")
    job = Job(project_id=p.id, kind=body.kind, params=body.params,
              status=TaskStatus.pending, logs=[])
    if body.kind == "pipeline":
        p.status = JobStatus.queued
    db.add(job)
    db.commit()
    return _job_out(job)


@router.get("/jobs/{jid}")
def get_job(jid: str, db: Session = Depends(get_db)):
    j = db.get(Job, jid)
    if not j:
        raise HTTPException(404, "job not found")
    return _job_out(j)


@router.get("/projects/{pid}/jobs")
def list_jobs(pid: str, db: Session = Depends(get_db)):
    return [_job_out(j) for j in reversed(_get_project(db, pid).jobs)]


@router.post("/jobs/{jid}/cancel")
def cancel_job(jid: str, db: Session = Depends(get_db)):
    j = db.get(Job, jid)
    if not j:
        raise HTTPException(404, "job not found")
    if j.status == TaskStatus.pending:
        j.status = TaskStatus.failed
        j.error = "canceled by user"
        db.commit()
    return _job_out(j)


# ----------------------------------------------------------------- exports
EXPORT_MEDIA = {
    "mp4": "video/mp4", "mp4_lipsync": "video/mp4", "wav": "audio/wav",
    "mp3": "audio/mpeg", "srt": "application/x-subrip",
    "vtt": "text/vtt", "recap": "text/plain",
}


@router.get("/projects/{pid}/artifacts/{kind}")
def download_artifact(pid: str, kind: str, db: Session = Depends(get_db)):
    p = _get_project(db, pid)
    a = next((x for x in p.artifacts if x.kind == kind), None)
    if not a:
        raise HTTPException(404, "artifact not ready")
    st = storage()
    if isinstance(st, LocalStorage):
        return FileResponse(st.path(a.key), media_type=EXPORT_MEDIA.get(kind, "application/octet-stream"),
                            filename=os.path.basename(a.key))
    return RedirectResponse(st.presign_download(a.key))


@router.get("/projects/{pid}/subtitles.{fmt}", response_class=PlainTextResponse)
def preview_subtitles(pid: str, fmt: str, db: Session = Depends(get_db)):
    from app.services.subtitles import to_srt, to_vtt

    p = _get_project(db, pid)
    rows = [{"start": s.start, "end": s.end,
             "text": s.dub_text or s.translated_text or s.source_text} for s in p.segments]
    if fmt == "srt":
        return to_srt(rows)
    if fmt == "vtt":
        return to_vtt(rows)
    raise HTTPException(400, "fmt must be srt or vtt")


# ----------------------------------------------------------------- local storage shim (dev)
local_router = APIRouter()


@local_router.put("/storage/local/{key:path}")
async def local_put(key: str, request: Request):
    st = storage()
    if not isinstance(st, LocalStorage):
        raise HTTPException(400, "local storage disabled")
    path = st.path(key)
    with open(path, "wb") as f:
        async for chunk in request.stream():
            f.write(chunk)
    return {"key": key, "bytes": os.path.getsize(path)}


@local_router.get("/storage/local/{key:path}")
def local_get(key: str):
    st = storage()
    if not isinstance(st, LocalStorage) or not st.exists(key):
        raise HTTPException(404, "not found")
    return FileResponse(st.path(key))
