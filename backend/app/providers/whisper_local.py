"""Local timestamped transcription with faster-whisper (CTranslate2, CPU-friendly)."""
from __future__ import annotations

from app.providers.base import TranscriptSegment


class FasterWhisperTranscription:
    name = "faster-whisper"

    def __init__(self, model_size: str = "small", device: str = "auto", compute_type: str = "int8"):
        from faster_whisper import WhisperModel  # lazy: heavy optional dep

        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, audio_path: str, language: str | None = None) -> list[TranscriptSegment]:
        segments, _info = self.model.transcribe(
            audio_path,
            language=language,
            vad_filter=True,
            word_timestamps=True,
            beam_size=5,
        )
        out: list[TranscriptSegment] = []
        for i, s in enumerate(segments):
            text = (s.text or "").strip()
            if not text:
                continue
            out.append(
                TranscriptSegment(index=len(out), start=round(s.start, 3), end=round(s.end, 3), text=text)
            )
        return out
