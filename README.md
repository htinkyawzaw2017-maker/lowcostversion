# Dubbing Studio — private Burmese ⇄ English movie dubbing

A single-user web app for dubbing films between English and Burmese, built on a deliberately
low-cost architecture: local models do the expensive repetitive work, Gemini is used only for
language intelligence, and the GPU is rented only for the optional lip-sync beta.

```
React + TypeScript (Vite)
        │  relative /api calls, no API keys in the browser
        ▼
FastAPI  ──► SQLite job store ──► worker process (durable, survives browser close)
        │                               │
        │                               ├── transcription  : faster-whisper (local)
        │                               ├── translation    : Gemini (backend only)
        │                               ├── TTS            : MMS-TTS (my) / Piper·Kokoro (en)
        │                               │                    Gemini TTS = optional fallback
        │                               ├── render         : FFmpeg
        │                               └── lip-sync       : separate GPU worker (beta)
        ▼
S3 (presigned PUT/GET)        AWS Secrets Manager (Gemini key)
```

## Quick start (fully mocked, zero AI cost)

```bash
# backend
python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd backend && ../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

# frontend
cd frontend && npm install && npm run dev      # http://localhost:5173
```

Everything ships in **mock mode**: create a project, run the pipeline, edit the script, re-voice a
line, and download MP4/WAV/MP3/SRT/VTT — all without a single AI call. Swap providers in
`backend/.env` one at a time.

## How the requirements map to the code

| Requirement | Where |
|---|---|
| React + TypeScript frontend | `frontend/src` |
| FastAPI backend | `backend/app/main.py`, `backend/app/api/routes.py` |
| S3 presigned uploads | `services/storage.py` → `POST /api/projects/{id}/upload-url`; browser PUTs directly |
| FFmpeg extract / mix / subtitles / render | `providers/ffmpeg_render.py` |
| faster-whisper timestamped transcription | `providers/whisper_local.py` |
| Gemini: translate, dub rewrite, recap, emotion, shortening | `providers/gemini.py` (backend only) |
| TTS adapter, local-first with Gemini fallback | `providers/tts_local.py` + `providers/registry.py::tts()` |
| Segment-by-segment audio generation | `services/pipeline.py::stage_tts` — one WAV per segment |
| Duration comparison vs original timing | `models.py::Segment.drift/fit`, auto-shortening in `stage_tts` |
| Edit text, timing, voice, speed | `components/SegmentRow.tsx`, `PATCH /api/segments/{id}` |
| Export MP4 / WAV / MP3 / SRT / VTT | `stage_subtitles`, `stage_render`, Export tab |
| Lip-sync optional beta | Extras tab, `run_lipsync`, disabled by default |
| Short clips, one front-facing speaker | `lipsync_max_clip_seconds`, enforced in the GPU worker |
| Separate GPU worker | `workers/gpu_lipsync_worker.py`, `docker-compose --profile gpu` |
| Keys in AWS Secrets Manager | `core/secrets.py` |
| No keys in frontend | `/api/config` returns booleans only; no endpoint returns key material |
| Processing continues after browser close | jobs persist in SQLite, run in `workers/runner.py`; interrupted jobs requeue on boot |
| Lip-sync failure keeps audio-only dub | `runner.py` never fails the project on `kind == "lipsync"` |
| Mock workers + clickable UI first | `providers/mock.py`, default config |
| Replaceable provider modules | `providers/base.py` protocols + `providers/registry.py` |

## Pipeline

1. **extract** — FFmpeg pulls a 16 kHz mono WAV from the source video.
2. **transcribe** — faster-whisper produces timestamped segments.
3. **translate** — Gemini translates line by line.
4. **emotion** — Gemini labels tone per line; the label drives TTS delivery.
5. **dub rewrite** — Gemini rewrites each line as natural spoken dialogue that fits its slot.
6. **TTS** — one WAV per segment. Each take's duration is compared with the original dialogue gap;
   overlong takes are shortened by Gemini and re-synthesised, with a capped `atempo` nudge at mix time.
7. **subtitles** — SRT + VTT from the final dub text.
8. **mix / render** — segments placed at their exact start times over a ducked original bed, then muxed to MP4.
9. **lip-sync (optional beta)** — short clips sent to the GPU worker; failure is logged and ignored.

## Cost notes

- Transcription and TTS run locally on CPU — no per-minute API cost.
- Gemini is called once per batch of lines, not per segment.
- The GPU box only runs when you explicitly trigger the lip-sync beta.
- S3 presigned uploads mean the API server never handles video bytes, so it can stay tiny.

## Going live, one provider at a time

```ini
DUB_PROVIDER_RENDER=ffmpeg            # 1. real media handling
DUB_PROVIDER_TRANSCRIPTION=faster_whisper
DUB_PROVIDER_TRANSLATION=gemini       # needs the Secrets Manager entry
DUB_PROVIDER_TTS_MY=mms_tts
DUB_PROVIDER_TTS_EN=piper
DUB_PROVIDER_STORAGE=s3
DUB_PROVIDER_LIPSYNC=gpu_worker       # last, and optional
```

Create the secret once:

```bash
aws secretsmanager create-secret --name dub-studio/gemini \
  --secret-string '{"GEMINI_API_KEY":"..."}'
```

See `docs/OPERATIONS.md` for deployment and IAM details.

## Hosting it on AWS

One command from AWS CloudShell builds the whole stack (S3 + Secrets Manager +
least-privilege IAM + EC2 with Docker, nginx and the built frontend):

```bash
git clone <this repo> dub && cd dub && bash deploy/aws-deploy.sh
```

- `AWS-HOST-GUIDE.txt` — full hosting guide: cost table, provider rollout order,
  GPU box, hardening, troubleshooting, teardown.
- `docs/AWS_DEPLOY_MY.md` — the same guide in Burmese (မြန်မာလမ်းညွှန်, ၁၃ ဆင့်).
- `deploy/install-on-server.sh` — install/update directly on an existing Ubuntu box.
- `HANDOFF.md` — project state, decisions, and known gaps.
