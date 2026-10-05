"""SRT / VTT writers."""
from __future__ import annotations


def _ts(seconds: float, sep: str = ",") -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:
        s, ms = s + 1, 0
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_srt(rows: list[dict]) -> str:
    out = []
    for i, r in enumerate(rows, 1):
        out.append(str(i))
        out.append(f"{_ts(r['start'])} --> {_ts(r['end'])}")
        out.append((r.get("text") or "").strip())
        out.append("")
    return "\n".join(out)


def to_vtt(rows: list[dict]) -> str:
    out = ["WEBVTT", ""]
    for r in rows:
        out.append(f"{_ts(r['start'], '.')} --> {_ts(r['end'], '.')}")
        out.append((r.get("text") or "").strip())
        out.append("")
    return "\n".join(out)
