"""Replaceable provider interfaces.

Every AI/media stage is behind one of these protocols so a provider can be
swapped (mock -> real) purely through configuration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class TranscriptSegment:
    index: int
    start: float
    end: float
    text: str
    speaker: str = "SPK1"


@dataclass
class TTSResult:
    audio_path: str
    duration: float
    provider: str
    sample_rate: int = 24000


@dataclass
class RenderRequest:
    project_id: str
    video_path: str | None
    segments: list = field(default_factory=list)
    mix_original_db: float = -18.0
    burn_subtitles: bool = False
    subtitle_path: str | None = None


@runtime_checkable
class TranscriptionProvider(Protocol):
    name: str

    def transcribe(self, audio_path: str, language: str | None = None) -> list[TranscriptSegment]: ...


@runtime_checkable
class TranslationProvider(Protocol):
    name: str

    def translate(self, texts: list[str], source_lang: str, target_lang: str) -> list[str]: ...

    def dub_rewrite(
        self, texts: list[str], target_lang: str, durations: list[float], emotions: list[str]
    ) -> list[str]: ...

    def shorten(self, text: str, target_lang: str, max_chars: int) -> str: ...

    def detect_emotion(self, texts: list[str]) -> list[str]: ...

    def recap(self, transcript: str, target_lang: str, minutes: float) -> str: ...


@runtime_checkable
class TTSProvider(Protocol):
    name: str
    languages: tuple[str, ...]

    def synthesize(
        self, text: str, *, lang: str, voice: str, speed: float, emotion: str, out_path: str
    ) -> TTSResult: ...


@runtime_checkable
class LipSyncProvider(Protocol):
    name: str

    def submit(self, video_path: str, audio_path: str, start: float, end: float) -> str: ...

    def poll(self, task_id: str) -> dict: ...


@runtime_checkable
class RenderProvider(Protocol):
    name: str

    def extract_audio(self, video_path: str, out_path: str) -> str: ...

    def mix(self, req: RenderRequest, out_path: str) -> str: ...

    def mux(self, req: RenderRequest, audio_path: str, out_path: str) -> str: ...

    def transcode_audio(self, wav_path: str, out_path: str) -> str: ...

    def probe_duration(self, path: str) -> float: ...
