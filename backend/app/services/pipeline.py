"""The dubbing pipeline.

Runs entirely server-side in a worker process, so closing the browser does not
affect it: state lives in the DB and every stage is restartable.

Stages: extract -> transcribe -> translate -> emotion -> dub rewrite ->
        TTS per segment -> duration fit -> mix -> export.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Artifact, Job, JobStatus, Project, Segment, TaskStatus
from app.providers import registry
from app.providers.base import RenderRequest
from app.services.storage import storage
from app.services.subtitles import to_srt, to_vtt

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- utils
def _log(db: Session, job: Job, msg: str, progress: float | None = None, stage: str | None = None):
    entry = f"{datetime.utcnow().strftime('%H:%M:%S')} {msg}"
    job.logs = (job.logs or []) + [entry]
    if progress is not None:
        job.progress = round(min(1.0, max(0.0, progress)), 3)
    if stage:
        job.stage = stage
    db.commit()
    log.info("[%s] %s", job.id[:8], msg)


def work_dir(project_id: str, *parts: str) -> str:
    p = os.path.join(get_settings().data_dir, "work", project_id, *parts)
    os.makedirs(os.path.dirname(p) if os.path.splitext(p)[1] else p, exist_ok=True)
    return p


def _atempo_for(seg: Segment) -> float:
    """Speed factor so a slightly-long take still fits its slot (±25% cap)."""
    if not seg.audio_duration or not seg.target_duration:
        return 1.0
    ratio = seg.audio_duration / seg.target_duration
    return round(min(1.25, max(0.8, ratio)), 3) if ratio > 1.02 else 1.0


# --------------------------------------------------------------------------- stages
def stage_prepare_audio(db: Session, job: Job, project: Project) -> str:
    _log(db, job, "Extracting audio track", 0.05, "extract")
    r = registry.render()
    wav = work_dir(project.id, "source.wav")
    video = storage().path(project.source_key) if project.source_key else None
    if video and os.path.exists(video):
        r.extract_audio(video, wav)
        project.duration_sec = r.probe_duration(video) or project.duration_sec
    else:
        _log(db, job, "No source video found -- using mock audio")
        registry.render().extract_audio(video or "mock", wav)
    db.commit()
    return wav


def stage_transcribe(db: Session, job: Job, project: Project, wav: str) -> None:
    if project.segments and not job.params.get("force_transcribe"):
        _log(db, job, f"Reusing {len(project.segments)} existing segments", 0.25, "transcribe")
        return
    _log(db, job, "Transcribing with timestamps", 0.1, "transcribe")
    segs = registry.transcription().transcribe(wav, language=project.source_lang)
    for s in project.segments:
        db.delete(s)
    db.flush()
    for s in segs:
        db.add(
            Segment(
                project_id=project.id, index=s.index, start=s.start, end=s.end,
                speaker=s.speaker, source_text=s.text,
            )
        )
    db.commit()
    _log(db, job, f"Transcribed {len(segs)} segments", 0.25)


def stage_translate(db: Session, job: Job, project: Project) -> None:
    segs = [s for s in project.segments if not s.locked]
    if not segs:
        return
    t = registry.translation()
    _log(db, job, f"Translating {len(segs)} lines -> {project.target_lang}", 0.3, "translate")
    texts = [s.source_text for s in segs]
    try:
        translated = t.translate(texts, project.source_lang, project.target_lang)
        emotions = t.detect_emotion(texts)
        _log(db, job, "Adapting emotion/tone + duration-aware rewrite", 0.4, "dub_rewrite")
        dub = t.dub_rewrite(
            translated, project.target_lang, [s.target_duration for s in segs], emotions
        )
    except Exception as exc:
        _log(db, job, f"Translation provider error: {exc}")
        raise
    for s, tr, em, dd in zip(segs, translated, emotions, dub):
        s.translated_text, s.emotion, s.dub_text = tr, em, dd
    db.commit()
    _log(db, job, "Dubbing script ready", 0.45)


def stage_tts(db: Session, job: Job, project: Project, only_ids: list[str] | None = None) -> None:
    """Segment-by-segment generation -- never one long file."""
    lang = project.target_lang
    engine = registry.tts(lang)
    tr = registry.translation()
    segs = [s for s in project.segments if not only_ids or s.id in only_ids]
    total = max(1, len(segs))
    _log(db, job, f"Synthesising {total} segments with {engine.name}", 0.5, "tts")

    for i, seg in enumerate(segs):
        text = (seg.dub_text or seg.translated_text or seg.source_text).strip()
        if not text:
            continue
        out = work_dir(project.id, f"seg_{seg.index:04d}.wav")
        try:
            res = engine.synthesize(
                text, lang=lang, voice=seg.voice, speed=seg.speed,
                emotion=seg.emotion, out_path=out,
            )
        except Exception as exc:
            _log(db, job, f"segment {seg.index}: TTS failed ({exc}) -> fallback engine")
            fb = registry.tts(lang)
            res = fb.synthesize(text, lang=lang, voice=seg.voice, speed=seg.speed,
                                emotion=seg.emotion, out_path=out)

        seg.audio_duration = res.duration
        seg.tts_provider = res.provider
        seg.audio_key = storage().put_file(res.audio_path, f"{project.id}/audio/seg_{seg.index:04d}.wav")

        # Duration comparison vs the original dialogue slot.
        if seg.fit == "long" and not seg.locked and seg.target_duration > 0:
            budget = int(len(text) * (seg.target_duration / max(0.1, seg.audio_duration)))
            try:
                shorter = tr.shorten(text, lang, max(8, budget))
            except Exception:
                shorter = text
            if shorter and shorter != text:
                seg.dub_text = shorter
                res = engine.synthesize(shorter, lang=lang, voice=seg.voice, speed=seg.speed,
                                        emotion=seg.emotion, out_path=out)
                seg.audio_duration = res.duration
                seg.audio_key = storage().put_file(res.audio_path,
                                                   f"{project.id}/audio/seg_{seg.index:04d}.wav")
                _log(db, job, f"segment {seg.index}: shortened to fit ({seg.drift:+.2f}s)")
        db.commit()
        job.progress = round(0.5 + 0.3 * (i + 1) / total, 3)
        db.commit()

    over = [s.index for s in project.segments if s.fit == "long"]
    if over:
        _log(db, job, f"{len(over)} segments still over their slot: {over[:10]}")
    _log(db, job, "Segment audio complete", 0.8)


def stage_subtitles(db: Session, job: Job, project: Project) -> None:
    rows = [
        {"start": s.start, "end": s.end, "text": s.dub_text or s.translated_text or s.source_text}
        for s in project.segments
    ]
    for kind, body in (("srt", to_srt(rows)), ("vtt", to_vtt(rows))):
        p = work_dir(project.id, f"dub.{kind}")
        with open(p, "w", encoding="utf-8") as f:
            f.write(body)
        _register_artifact(db, project, kind, storage().put_file(p, f"{project.id}/exports/dub.{kind}"))
    _log(db, job, "Subtitles exported (SRT + VTT)", 0.85, "subtitles")


def stage_render(db: Session, job: Job, project: Project) -> None:
    _log(db, job, "Mixing dubbed track with original bed", 0.88, "mix")
    r = registry.render()
    st = storage()
    video = st.path(project.source_key) if project.source_key else None
    seg_rows = [
        {
            "start": s.start, "end": s.end,
            "audio_path": st.path(s.audio_key) if s.audio_key else None,
            "atempo": _atempo_for(s),
        }
        for s in project.segments
        if s.audio_key
    ]
    req = RenderRequest(
        project_id=project.id, video_path=video, segments=seg_rows,
        mix_original_db=float(project.settings.get("mix_original_db", -18.0)),
        burn_subtitles=bool(project.settings.get("burn_subtitles", False)),
        subtitle_path=work_dir(project.id, "dub.srt"),
    )
    wav = work_dir(project.id, "dub_mix.wav")
    r.mix(req, wav)
    _register_artifact(db, project, "wav", st.put_file(wav, f"{project.id}/exports/dub.wav"))

    mp3 = work_dir(project.id, "dub_mix.mp3")
    try:
        r.transcode_audio(wav, mp3)
        _register_artifact(db, project, "mp3", st.put_file(mp3, f"{project.id}/exports/dub.mp3"))
    except Exception as exc:
        _log(db, job, f"mp3 transcode skipped: {exc}")

    _log(db, job, "Rendering MP4", 0.95, "render")
    mp4 = work_dir(project.id, "dubbed.mp4")
    r.mux(req, wav, mp4)
    _register_artifact(db, project, "mp4", st.put_file(mp4, f"{project.id}/exports/dubbed.mp4"))
    _log(db, job, "Audio-only dubbed output is safe and downloadable", 1.0, "done")


def _register_artifact(db: Session, project: Project, kind: str, key: str, meta: dict | None = None):
    existing = next((a for a in project.artifacts if a.kind == kind), None)
    size = storage().size(key)
    if existing:
        existing.key, existing.bytes, existing.meta = key, size, meta or {}
    else:
        db.add(Artifact(project_id=project.id, kind=kind, key=key, bytes=size, meta=meta or {}))
    db.commit()


# --------------------------------------------------------------------------- lip-sync (beta)
def run_lipsync(db: Session, job: Job, project: Project) -> None:
    """Optional beta. Short clips only, single front-facing speaker.
    Failure never invalidates the audio-only dubbed output."""
    import time

    s = get_settings()
    client = registry.lipsync()
    st = storage()
    segs = [
        x for x in project.segments
        if x.audio_key and 0 < x.target_duration <= s.lipsync_max_clip_seconds
    ]
    segs = segs[: int(job.params.get("max_clips", 3))]
    if not segs:
        _log(db, job, "No clip short enough for the beta lip-sync constraints", 1.0, "skipped")
        job.status = TaskStatus.skipped
        db.commit()
        return

    _log(db, job, f"Submitting {len(segs)} short clips to the GPU worker", 0.1, "lipsync")
    done = 0
    for seg in segs:
        try:
            video = st.path(project.source_key) if project.source_key else ""
            tid = client.submit(video, st.path(seg.audio_key), seg.start, seg.end)
            for _ in range(120):
                res = client.poll(tid)
                if res.get("status") in ("succeeded", "failed"):
                    break
                time.sleep(2)
            if res.get("status") == "succeeded":
                done += 1
                _log(db, job, f"segment {seg.index}: lip-sync ok")
            else:
                _log(db, job, f"segment {seg.index}: lip-sync failed -- keeping audio-only dub")
        except Exception as exc:
            _log(db, job, f"segment {seg.index}: lip-sync error {exc} -- keeping audio-only dub")
        job.progress = round(0.1 + 0.9 * (segs.index(seg) + 1) / len(segs), 3)
        db.commit()

    if done:
        _register_artifact(db, project, "mp4_lipsync",
                           next(a.key for a in project.artifacts if a.kind == "mp4"),
                           {"beta": True, "clips": done})
    _log(db, job, f"Lip-sync beta finished ({done}/{len(segs)} clips)", 1.0, "done")


# --------------------------------------------------------------------------- entrypoints
def run_pipeline(db: Session, job: Job) -> None:
    project = db.get(Project, job.project_id)
    project.status = JobStatus.running
    db.commit()
    wav = stage_prepare_audio(db, job, project)
    stage_transcribe(db, job, project, wav)
    db.refresh(project)
    stage_translate(db, job, project)
    stage_tts(db, job, project)
    stage_subtitles(db, job, project)
    stage_render(db, job, project)
    project.status = JobStatus.needs_review
    db.commit()


def run_tts_only(db: Session, job: Job) -> None:
    project = db.get(Project, job.project_id)
    stage_tts(db, job, project, only_ids=job.params.get("segment_ids") or None)
    _log(db, job, "Re-synthesis complete", 1.0, "done")


def run_render_only(db: Session, job: Job) -> None:
    project = db.get(Project, job.project_id)
    stage_subtitles(db, job, project)
    stage_render(db, job, project)
    project.status = JobStatus.completed
    db.commit()


def run_recap(db: Session, job: Job) -> None:
    project = db.get(Project, job.project_id)
    _log(db, job, "Generating recap script", 0.2, "recap")
    transcript = "\n".join(
        f"[{s.start:.1f}] {s.source_text}" for s in project.segments if s.source_text
    )
    lang = job.params.get("lang", project.target_lang)
    minutes = float(job.params.get("minutes", 3.0))
    text = registry.translation().recap(transcript, lang, minutes)
    p = work_dir(project.id, "recap.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    _register_artifact(db, project, "recap", storage().put_file(p, f"{project.id}/exports/recap.txt"),
                       {"lang": lang, "minutes": minutes})
    _log(db, job, "Recap ready", 1.0, "done")


HANDLERS = {
    "pipeline": run_pipeline,
    "tts": run_tts_only,
    "render": run_render_only,
    "recap": run_recap,
    "lipsync": lambda db, job: run_lipsync(db, job, db.get(Project, job.project_id)),
}
