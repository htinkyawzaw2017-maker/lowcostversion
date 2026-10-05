from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uid() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class JobStatus(str, enum.Enum):
    created = "created"
    uploading = "uploading"
    queued = "queued"
    running = "running"
    needs_review = "needs_review"
    completed = "completed"
    failed = "failed"
    canceled = "canceled"


class TaskStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    title: Mapped[str] = mapped_column(String(255))
    source_lang: Mapped[str] = mapped_column(String(8), default="en")
    target_lang: Mapped[str] = mapped_column(String(8), default="my")
    source_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    duration_sec: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.created)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    segments: Mapped[list["Segment"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Segment.index"
    )
    jobs: Mapped[list["Job"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Job.created_at"
    )
    artifacts: Mapped[list["Artifact"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Segment(Base):
    __tablename__ = "segments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    index: Mapped[int] = mapped_column(Integer)

    start: Mapped[float] = mapped_column(Float, default=0.0)
    end: Mapped[float] = mapped_column(Float, default=0.0)
    speaker: Mapped[str] = mapped_column(String(64), default="SPK1")

    source_text: Mapped[str] = mapped_column(Text, default="")
    translated_text: Mapped[str] = mapped_column(Text, default="")
    dub_text: Mapped[str] = mapped_column(Text, default="")  # natural dubbing rewrite (editable)

    emotion: Mapped[str] = mapped_column(String(32), default="neutral")
    voice: Mapped[str] = mapped_column(String(64), default="default")
    speed: Mapped[float] = mapped_column(Float, default=1.0)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)  # user edited -> don't overwrite

    audio_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    audio_duration: Mapped[float] = mapped_column(Float, default=0.0)
    tts_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)

    project: Mapped[Project] = relationship(back_populates="segments")

    # ---- duration fit helpers -------------------------------------------------
    @property
    def target_duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def drift(self) -> float:
        """Generated audio duration minus original dialogue slot (seconds)."""
        if not self.audio_duration:
            return 0.0
        return round(self.audio_duration - self.target_duration, 3)

    @property
    def fit(self) -> str:
        if not self.audio_duration:
            return "unknown"
        d = self.drift
        tol = max(0.35, self.target_duration * 0.12)
        if abs(d) <= tol:
            return "ok"
        return "long" if d > 0 else "short"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))  # pipeline | tts | render | lipsync | recap
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.pending)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    stage: Mapped[str] = mapped_column(String(64), default="queued")
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    logs: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    project: Mapped[Project] = relationship(back_populates="jobs")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))  # mp4 | mp4_lipsync | wav | mp3 | srt | vtt | recap
    key: Mapped[str] = mapped_column(String(512))
    bytes: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    project: Mapped[Project] = relationship(back_populates="artifacts")
