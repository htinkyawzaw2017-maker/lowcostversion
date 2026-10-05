"""Mock providers: let the whole UI be clickable before any AI service exists.

They produce real files (silent/tone WAVs, valid SRT/VTT, placeholder MP4s) so
the download, playback and duration-comparison paths are exercised for real.
"""
from __future__ import annotations

import math
import os
import random
import struct
import time
import wave

from app.providers.base import (
    RenderRequest,
    TranscriptSegment,
    TTSResult,
)

_SAMPLE_EN = [
    "I thought you were gone for good.",
    "We don't have much time, the train leaves at nine.",
    "Promise me you'll come back.",
    "Everything changed the night of the fire.",
    "You never told me the truth about my father.",
    "Run! Don't look back!",
    "This city owes me nothing, and I owe it everything.",
    "Sit down. We need to talk about the money.",
]
_SAMPLE_MY = [
    "မင်းအပြီးအပိုင်ထွက်သွားပြီလို့ ထင်နေတာ။",
    "အချိန်မရှိတော့ဘူး၊ ရထားက ကိုးနာရီထွက်မယ်။",
    "ပြန်လာမယ်လို့ ကတိပေးပါ။",
    "မီးလောင်တဲ့ညကတည်းက အားလုံးပြောင်းလဲသွားတယ်။",
    "အဖေ့အကြောင်း အမှန်တရားကို မင်းဘယ်တုန်းကမှ မပြောဖူးဘူး။",
    "ပြေး! နောက်ပြန်မကြည့်နဲ့!",
    "ဒီမြို့က ငါ့ကို ဘာမှမပေးဆပ်ရဘူး၊ ငါကတော့ အားလုံးပေးဆပ်ရတယ်။",
    "ထိုင်ပါ။ ပိုက်ဆံအကြောင်း ပြောစရာရှိတယ်။",
]
_EMOTIONS = ["neutral", "sad", "tense", "warm", "angry", "urgent"]


class MockTranscription:
    name = "mock-whisper"

    def transcribe(self, audio_path: str, language: str | None = None) -> list[TranscriptSegment]:
        rnd = random.Random(os.path.basename(audio_path or "x"))
        segs: list[TranscriptSegment] = []
        t = 1.5
        for i in range(12):
            dur = round(rnd.uniform(1.8, 4.2), 2)
            segs.append(
                TranscriptSegment(
                    index=i,
                    start=round(t, 2),
                    end=round(t + dur, 2),
                    text=rnd.choice(_SAMPLE_EN),
                    speaker=f"SPK{rnd.randint(1, 2)}",
                )
            )
            t += dur + round(rnd.uniform(0.3, 1.4), 2)
            time.sleep(0.01)
        return segs


class MockTranslation:
    name = "mock-gemini"

    def translate(self, texts: list[str], source_lang: str, target_lang: str) -> list[str]:
        if target_lang.startswith("my"):
            return [_SAMPLE_MY[i % len(_SAMPLE_MY)] for i, _ in enumerate(texts)]
        return [f"[{target_lang}] {t}" for t in texts]

    def dub_rewrite(self, texts, target_lang, durations, emotions):
        out = []
        for t, d in zip(texts, durations):
            budget = max(8, int(d * 14))
            out.append(t if len(t) <= budget else t[: budget - 1].rstrip() + "…")
        return out

    def shorten(self, text: str, target_lang: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[: max(4, max_chars - 1)].rstrip() + "…"

    def detect_emotion(self, texts: list[str]) -> list[str]:
        rnd = random.Random(7)
        return [rnd.choice(_EMOTIONS) for _ in texts]

    def recap(self, transcript: str, target_lang: str, minutes: float) -> str:
        lang = "Burmese" if target_lang.startswith("my") else "English"
        return (
            f"[MOCK {lang} recap · target {minutes:.1f} min]\n"
            "1. The story opens on a city that never forgave its own.\n"
            "2. A promise made before the nine o'clock train becomes the spine of the film.\n"
            "3. The fire reframes every relationship, especially with the father.\n"
            "4. The final act trades money for the truth.\n"
        )


def _write_tone_wav(path: str, duration: float, sample_rate: int = 24000, freq: float = 180.0):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    n = max(1, int(duration * sample_rate))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        frames = bytearray()
        for i in range(n):
            env = min(1.0, i / (0.02 * sample_rate)) * min(1.0, (n - i) / (0.02 * sample_rate))
            v = int(6000 * env * math.sin(2 * math.pi * freq * i / sample_rate))
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))
    return path


class MockTTS:
    """Deterministic 'speech': duration derived from text length and speed,
    so duration-vs-timing comparison in the UI behaves realistically."""

    languages = ("en", "my")

    def __init__(self, name: str = "mock-tts", cps: float = 15.0):
        self.name = name
        self.cps = cps

    def synthesize(self, text, *, lang, voice, speed, emotion, out_path) -> TTSResult:
        chars = max(1, len(text.strip()))
        base = chars / (self.cps * max(0.4, speed))
        jitter = 1.0 + ((hash((text, voice)) % 25) - 12) / 100.0
        duration = round(max(0.35, base * jitter), 3)
        freq = 150 + (abs(hash(voice)) % 120)
        _write_tone_wav(out_path, duration, freq=freq)
        return TTSResult(audio_path=out_path, duration=duration, provider=self.name)


class MockLipSync:
    name = "mock-lipsync"

    def __init__(self):
        self._tasks: dict[str, float] = {}

    def submit(self, video_path, audio_path, start, end) -> str:
        tid = f"mock-{int(time.time() * 1000)}"
        self._tasks[tid] = time.time()
        return tid

    def poll(self, task_id: str) -> dict:
        started = self._tasks.get(task_id, time.time())
        elapsed = time.time() - started
        if elapsed < 6:
            return {"status": "running", "progress": min(0.95, elapsed / 6)}
        return {"status": "succeeded", "progress": 1.0, "output_path": None}


class MockRender:
    name = "mock-render"

    def extract_audio(self, video_path: str, out_path: str) -> str:
        return _write_tone_wav(out_path, 2.0, freq=90)

    def probe_duration(self, path: str) -> float:
        try:
            with wave.open(path, "rb") as w:
                return w.getnframes() / float(w.getframerate())
        except Exception:
            return 0.0

    def mix(self, req: RenderRequest, out_path: str) -> str:
        total = max((s["end"] for s in req.segments), default=5.0) + 1.0
        return _write_tone_wav(out_path, min(total, 60.0), freq=120)

    def mux(self, req: RenderRequest, audio_path: str, out_path: str) -> str:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
            f.write(b"MOCK-RENDER-" + req.project_id.encode())
        return out_path

    def transcode_audio(self, wav_path: str, out_path: str) -> str:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(wav_path, "rb") as src, open(out_path, "wb") as dst:
            dst.write(src.read())
        return out_path
