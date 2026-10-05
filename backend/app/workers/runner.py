"""Durable job runner.

Jobs live in the database, so work continues after the browser is closed and
survives an API restart (interrupted jobs are requeued on boot).

Run in-process (`DUB_WORKER_INLINE=1`, default for the single-user setup) or as
a separate process:  python -m app.workers.runner
"""
from __future__ import annotations

import logging
import threading
import time
import traceback

from app.core.db import session
from app.models import Job, JobStatus, Project, TaskStatus
from app.services.pipeline import HANDLERS

log = logging.getLogger(__name__)
POLL_SECONDS = 1.5
MAX_ATTEMPTS = 2

_stop = threading.Event()


def requeue_interrupted() -> int:
    db = session()
    try:
        stuck = db.query(Job).filter(Job.status == TaskStatus.running).all()
        for j in stuck:
            j.status = TaskStatus.pending
            j.stage = "requeued"
            j.logs = (j.logs or []) + ["requeued after restart"]
        db.commit()
        return len(stuck)
    finally:
        db.close()


def claim_next(db):
    job = (
        db.query(Job)
        .filter(Job.status == TaskStatus.pending)
        .order_by(Job.created_at.asc())
        .first()
    )
    if job:
        job.status = TaskStatus.running
        job.attempts += 1
        db.commit()
    return job


def run_once() -> bool:
    db = session()
    try:
        job = claim_next(db)
        if not job:
            return False
        handler = HANDLERS.get(job.kind)
        try:
            if not handler:
                raise RuntimeError(f"unknown job kind {job.kind}")
            handler(db, job)
            if job.status != TaskStatus.skipped:
                job.status = TaskStatus.succeeded
                job.progress = 1.0
                job.stage = "done"
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            job = db.get(Job, job.id)
            job.error = f"{exc}\n{traceback.format_exc()[-1500:]}"
            job.logs = (job.logs or []) + [f"ERROR: {exc}"]
            if job.attempts < MAX_ATTEMPTS and job.kind != "lipsync":
                job.status = TaskStatus.pending
                job.stage = "retrying"
            else:
                job.status = TaskStatus.failed
                job.stage = "failed"
                project = db.get(Project, job.project_id)
                # Lip-sync is beta: its failure must not invalidate the dub.
                if project and job.kind != "lipsync":
                    project.status = JobStatus.failed
            db.commit()
            log.exception("job %s failed", job.id)
        return True
    finally:
        db.close()


def loop():
    requeue_interrupted()
    log.info("worker loop started")
    while not _stop.is_set():
        try:
            if not run_once():
                _stop.wait(POLL_SECONDS)
        except Exception:  # noqa: BLE001
            log.exception("worker loop error")
            time.sleep(POLL_SECONDS)


def start_background() -> threading.Thread:
    t = threading.Thread(target=loop, name="dub-worker", daemon=True)
    t.start()
    return t


def stop():
    _stop.set()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    loop()
