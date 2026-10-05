"""Gemini-backed translation / dubbing rewrite / recap / emotion / shortening.

Called only from the backend. The API key is resolved from AWS Secrets Manager
and never leaves the server.
"""
from __future__ import annotations

import json
import logging
import re
import wave

import httpx

from app.core.config import get_settings
from app.core.secrets import get_gemini_api_key
from app.providers.base import TTSResult

log = logging.getLogger(__name__)
API = "https://generativelanguage.googleapis.com/v1beta/models"


def _call(model: str, prompt: str, *, json_mode: bool = True, timeout: float = 120.0) -> str:
    key = get_gemini_api_key()
    if not key:
        raise RuntimeError("Gemini API key is not configured (AWS Secrets Manager)")
    body: dict = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    if json_mode:
        body["generationConfig"] = {"response_mime_type": "application/json"}
    r = httpx.post(
        f"{API}/{model}:generateContent",
        params={"key": key},
        json=body,
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _json_list(raw: str, n: int, fallback: list[str]) -> list[str]:
    try:
        m = re.search(r"\[.*\]", raw, re.S)
        items = json.loads(m.group(0) if m else raw)
        items = [str(x) for x in items]
    except Exception:
        log.warning("Gemini returned unparseable JSON, falling back")
        return fallback
    if len(items) < n:
        items += fallback[len(items):]
    return items[:n]


_LANG = {"my": "Burmese (Myanmar)", "en": "English"}


class GeminiTranslation:
    name = "gemini"

    def __init__(self):
        self.model = get_settings().gemini_model

    def translate(self, texts, source_lang, target_lang):
        prompt = (
            f"Translate each movie subtitle line from {_LANG.get(source_lang, source_lang)} to "
            f"{_LANG.get(target_lang, target_lang)}. Keep the speaker's register and any names.\n"
            "Return ONLY a JSON array of strings, same length and order as the input.\n\n"
            + json.dumps(texts, ensure_ascii=False)
        )
        return _json_list(_call(self.model, prompt), len(texts), list(texts))

    def dub_rewrite(self, texts, target_lang, durations, emotions):
        rows = [
            {"i": i, "text": t, "seconds": round(d, 2), "emotion": e}
            for i, (t, d, e) in enumerate(zip(texts, durations, emotions))
        ]
        prompt = (
            f"You are a dubbing script writer for {_LANG.get(target_lang, target_lang)}.\n"
            "Rewrite each line so it sounds like natural spoken dialogue, matches the given "
            "emotion/tone, and can be comfortably SPOKEN within the given number of seconds "
            "(duration-aware shortening: cut filler, never cut meaning that matters).\n"
            "Keep it one line each, no quotes, no narration, no speaker labels.\n"
            "Return ONLY a JSON array of strings in the same order.\n\n"
            + json.dumps(rows, ensure_ascii=False)
        )
        return _json_list(_call(self.model, prompt), len(texts), list(texts))

    def shorten(self, text, target_lang, max_chars):
        prompt = (
            f"Shorten this {_LANG.get(target_lang, target_lang)} dubbing line to at most "
            f"{max_chars} characters while keeping the meaning and natural speech rhythm.\n"
            'Return ONLY a JSON array with one string.\n\n' + json.dumps([text], ensure_ascii=False)
        )
        return _json_list(_call(self.model, prompt), 1, [text])[0]

    def detect_emotion(self, texts):
        prompt = (
            "Label the emotion/tone of each movie line with ONE of: "
            "neutral, sad, tense, warm, angry, urgent, playful, fearful.\n"
            "Return ONLY a JSON array of labels in the same order.\n\n"
            + json.dumps(texts, ensure_ascii=False)
        )
        return _json_list(_call(self.model, prompt), len(texts), ["neutral"] * len(texts))

    def recap(self, transcript, target_lang, minutes):
        prompt = (
            f"Write a spoken-voiceover RECAP script in {_LANG.get(target_lang, target_lang)} "
            f"for this film, timed to about {minutes:.1f} minutes of narration. "
            "No spoilers beyond the transcript, no headings, short punchy sentences.\n"
            "Return ONLY a JSON array of paragraph strings.\n\n"
            + json.dumps(transcript[:20000], ensure_ascii=False)
        )
        return "\n\n".join(_json_list(_call(self.model, prompt), 1, [""]))


class GeminiTTS:
    """Optional fallback TTS (used only when local MMS/Piper/Kokoro are unavailable)."""

    name = "gemini-tts"
    languages = ("en", "my")

    def __init__(self):
        self.model = get_settings().gemini_tts_model

    def synthesize(self, text, *, lang, voice, speed, emotion, out_path) -> TTSResult:
        key = get_gemini_api_key()
        if not key:
            raise RuntimeError("Gemini API key is not configured")
        style = f"Say this with a {emotion} tone, natural movie dubbing delivery: "
        body = {
            "contents": [{"parts": [{"text": style + text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": voice if voice != "default" else "Kore"}
                    }
                },
            },
        }
        r = httpx.post(f"{API}/{self.model}:generateContent", params={"key": key}, json=body, timeout=180)
        r.raise_for_status()
        import base64

        part = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
        pcm = base64.b64decode(part["data"])
        sr = 24000
        with wave.open(out_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm)
        return TTSResult(out_path, len(pcm) / (2 * sr), self.name, sr)
