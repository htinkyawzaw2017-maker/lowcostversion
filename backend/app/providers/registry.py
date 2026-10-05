"""Provider registry -- the single place where a stage is bound to an implementation."""
from __future__ import annotations

import logging
from functools import lru_cache

from app.core.config import get_settings
from app.providers import mock

log = logging.getLogger(__name__)


def _safe(factory, fallback, label: str):
    try:
        return factory()
    except Exception as exc:
        log.warning("provider %s unavailable (%s) -> using mock", label, exc)
        return fallback


@lru_cache
def transcription():
    s = get_settings()
    if s.provider_transcription == "faster_whisper":
        from app.providers.whisper_local import FasterWhisperTranscription

        return _safe(FasterWhisperTranscription, mock.MockTranscription(), "faster_whisper")
    return mock.MockTranscription()


@lru_cache
def translation():
    s = get_settings()
    if s.provider_translation == "gemini":
        from app.providers.gemini import GeminiTranslation

        return _safe(GeminiTranslation, mock.MockTranslation(), "gemini")
    return mock.MockTranslation()


def _build_tts(kind: str, lang: str):
    if kind == "mms_tts":
        from app.providers.tts_local import MmsTTS

        return MmsTTS()
    if kind == "piper":
        from app.providers.tts_local import PiperTTS

        return PiperTTS()
    if kind == "kokoro":
        from app.providers.tts_local import KokoroTTS

        return KokoroTTS()
    if kind == "gemini_tts":
        from app.providers.gemini import GeminiTTS

        return GeminiTTS()
    return mock.MockTTS(name=f"mock-tts-{lang}", cps=15.0 if lang == "en" else 11.0)


@lru_cache
def tts(lang: str):
    """Local model first, Gemini TTS only as an optional fallback."""
    s = get_settings()
    primary = s.provider_tts_my if lang.startswith("my") else s.provider_tts_en
    try:
        return _build_tts(primary, lang)
    except Exception as exc:
        log.warning("primary TTS %s failed (%s) -> fallback %s", primary, exc, s.provider_tts_fallback)
        try:
            return _build_tts(s.provider_tts_fallback, lang)
        except Exception as exc2:
            log.warning("fallback TTS failed too (%s) -> mock", exc2)
            return mock.MockTTS(name=f"mock-tts-{lang}")


@lru_cache
def lipsync():
    if get_settings().provider_lipsync == "gpu_worker":
        from app.providers.lipsync_gpu import GpuLipSyncClient

        return _safe(GpuLipSyncClient, mock.MockLipSync(), "gpu_worker")
    return mock.MockLipSync()


@lru_cache
def render():
    if get_settings().provider_render == "ffmpeg":
        from app.providers.ffmpeg_render import FfmpegRender

        return _safe(FfmpegRender, mock.MockRender(), "ffmpeg")
    return mock.MockRender()


def describe() -> dict:
    s = get_settings()
    return {
        "transcription": {"configured": s.provider_transcription, "active": transcription().name},
        "translation": {"configured": s.provider_translation, "active": translation().name},
        "tts_my": {"configured": s.provider_tts_my, "active": tts("my").name},
        "tts_en": {"configured": s.provider_tts_en, "active": tts("en").name},
        "tts_fallback": {"configured": s.provider_tts_fallback},
        "lipsync": {"configured": s.provider_lipsync, "active": lipsync().name, "beta": True},
        "render": {"configured": s.provider_render, "active": render().name},
        "storage": {"configured": s.provider_storage},
    }
