"""FFmpeg provider: audio extraction, segment-accurate mixing, subtitles, muxing."""
from __future__ import annotations

import json
import os
import subprocess

from app.core.config import get_settings
from app.providers.base import RenderRequest


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(cmd[:6])}…\n{proc.stderr.decode()[-2000:]}")


class FfmpegRender:
    name = "ffmpeg"

    def __init__(self):
        s = get_settings()
        self.ffmpeg, self.ffprobe = s.ffmpeg_bin, s.ffprobe_bin

    # -- probing ---------------------------------------------------------------
    def probe_duration(self, path: str) -> float:
        out = subprocess.run(
            [self.ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "json", path],
            capture_output=True,
        )
        if out.returncode != 0:
            return 0.0
        try:
            return float(json.loads(out.stdout)["format"]["duration"])
        except Exception:
            return 0.0

    # -- stages ----------------------------------------------------------------
    def extract_audio(self, video_path: str, out_path: str) -> str:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        _run([self.ffmpeg, "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000", out_path])
        return out_path

    def mix(self, req: RenderRequest, out_path: str) -> str:
        """Place each dubbed segment WAV at its start time (adelay) and mix them
        with a ducked copy of the original audio bed."""
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        segs = [s for s in req.segments if s.get("audio_path") and os.path.exists(s["audio_path"])]
        inputs: list[str] = []
        filters: list[str] = []
        labels: list[str] = []
        idx = 0

        if req.video_path and os.path.exists(req.video_path):
            inputs += ["-i", req.video_path]
            filters.append(f"[0:a]volume={req.mix_original_db}dB,aresample=48000[bed]")
            labels.append("[bed]")
            idx = 1

        for n, s in enumerate(segs):
            inputs += ["-i", s["audio_path"]]
            delay_ms = int(max(0.0, float(s["start"])) * 1000)
            atempo = float(s.get("atempo") or 1.0)
            chain = f"[{idx + n}:a]aresample=48000"
            if abs(atempo - 1.0) > 0.01:
                chain += f",atempo={min(2.0, max(0.5, atempo)):.3f}"
            chain += f",adelay={delay_ms}|{delay_ms}[s{n}]"
            filters.append(chain)
            labels.append(f"[s{n}]")

        if not labels:
            raise RuntimeError("nothing to mix")
        filters.append(
            f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:dropout_transition=0,"
            "dynaudnorm=f=250:g=5[out]"
        )
        _run([self.ffmpeg, "-y", *inputs, "-filter_complex", ";".join(filters),
              "-map", "[out]", "-ac", "2", "-ar", "48000", out_path])
        return out_path

    def mux(self, req: RenderRequest, audio_path: str, out_path: str) -> str:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        cmd = [self.ffmpeg, "-y", "-i", req.video_path, "-i", audio_path]
        if req.burn_subtitles and req.subtitle_path:
            sub = req.subtitle_path.replace("\\", "/").replace(":", r"\:")
            cmd += ["-vf", f"subtitles='{sub}':force_style='FontName=Noto Sans Myanmar,Fontsize=20'",
                    "-c:v", "libx264", "-crf", "20", "-preset", "veryfast"]
        else:
            cmd += ["-c:v", "copy"]
        cmd += ["-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "192k",
                "-shortest", out_path]
        _run(cmd)
        return out_path

    def transcode_audio(self, wav_path: str, out_path: str) -> str:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        codec = ["-c:a", "libmp3lame", "-b:a", "192k"] if out_path.endswith(".mp3") else []
        _run([self.ffmpeg, "-y", "-i", wav_path, *codec, out_path])
        return out_path

    def cut_clip(self, video_path: str, start: float, end: float, out_path: str) -> str:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        _run([self.ffmpeg, "-y", "-ss", str(start), "-to", str(end), "-i", video_path,
              "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-an", out_path])
        return out_path
