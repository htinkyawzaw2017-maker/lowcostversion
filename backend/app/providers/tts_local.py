"""Local-first TTS engines: MMS-TTS for Burmese, Piper/Kokoro for English."""
from __future__ import annotations

import os
import subprocess
import wave

from app.providers.base import TTSResult


def _wav_duration(path: str) -> float:
    with wave.open(path, "rb") as w:
        return w.getnframes() / float(w.getframerate())


class MmsTTS:
    """facebook/mms-tts-mya -- Burmese, runs locally on CPU."""

    name = "mms-tts-mya"
    languages = ("my",)

    def __init__(self, model_id: str = "facebook/mms-tts-mya"):
        from transformers import VitsModel, AutoTokenizer  # lazy

        self.model = VitsModel.from_pretrained(model_id)
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)

    def synthesize(self, text, *, lang, voice, speed, emotion, out_path) -> TTSResult:
        import torch
        import numpy as np

        self.model.speaking_rate = float(speed)
        inputs = self.tokenizer(text, return_tensors="pt")
        with torch.no_grad():
            wav = self.model(**inputs).waveform[0].cpu().numpy()
        sr = int(self.model.config.sampling_rate)
        pcm = (np.clip(wav, -1, 1) * 32767).astype("<i2").tobytes()
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with wave.open(out_path, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm)
        return TTSResult(out_path, len(wav) / sr, self.name, sr)


class PiperTTS:
    """Piper -- fast local English neural TTS via CLI."""

    name = "piper"
    languages = ("en",)

    def __init__(self, binary: str = "piper", voices_dir: str = "./models/piper",
                 default_voice: str = "en_US-amy-medium"):
        self.binary, self.voices_dir, self.default_voice = binary, voices_dir, default_voice

    def synthesize(self, text, *, lang, voice, speed, emotion, out_path) -> TTSResult:
        model = os.path.join(self.voices_dir, f"{voice if voice != 'default' else self.default_voice}.onnx")
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        subprocess.run(
            [self.binary, "-m", model, "-f", out_path, "--length_scale", str(round(1.0 / max(0.4, speed), 3))],
            input=text.encode("utf-8"), check=True, capture_output=True,
        )
        return TTSResult(out_path, _wav_duration(out_path), self.name)


class KokoroTTS:
    """Kokoro-82M -- expressive local English TTS."""

    name = "kokoro"
    languages = ("en",)

    def __init__(self, default_voice: str = "af_heart"):
        from kokoro import KPipeline  # lazy

        self.pipeline = KPipeline(lang_code="a")
        self.default_voice = default_voice

    def synthesize(self, text, *, lang, voice, speed, emotion, out_path) -> TTSResult:
        import numpy as np

        chunks = [
            audio for _gs, _ps, audio in self.pipeline(
                text, voice=voice if voice != "default" else self.default_voice, speed=float(speed)
            )
        ]
        wav = np.concatenate(chunks) if chunks else np.zeros(1, dtype="float32")
        sr = 24000
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with wave.open(out_path, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
            w.writeframes((np.clip(wav, -1, 1) * 32767).astype("<i2").tobytes())
        return TTSResult(out_path, len(wav) / sr, self.name, sr)
