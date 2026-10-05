# Handoff — where this project stands

Short note for whoever (or whichever session) picks this up next.

## What exists

A single-user Burmese ⇄ English movie dubbing studio, built low-cost on purpose:
local models do the repetitive work, Gemini only does language intelligence, and
the GPU is rented only for the optional lip-sync beta.

```
frontend/   React 19 + TypeScript (Vite). Projects, Editor, Settings.
backend/    FastAPI + SQLite + a durable job runner.
  app/api/routes.py          HTTP surface; handlers only enqueue jobs
  app/services/pipeline.py   the 9 stages, one function each
  app/providers/*            swappable modules behind protocols in base.py
  app/workers/runner.py      claims jobs, writes progress, requeues on boot
  app/workers/gpu_lipsync_worker.py   separate service, started on demand
deploy/     aws-deploy.sh (CloudShell, one shot) + install-on-server.sh
docs/       OPERATIONS.md (en), AWS_DEPLOY_MY.md (my)
AWS-HOST-GUIDE.txt            plain-text hosting guide
```

Everything ships in **mock mode**. You can create a project, run the whole
pipeline, edit the script, re-voice a line and export MP4/WAV/MP3/SRT/VTT
without a single AI call.

## State of each piece

| Area | State |
|---|---|
| Pipeline (extract → … → render) | done, mock + real paths both wired |
| Provider registry / fallbacks | done, falls back to mock on import error |
| Durable jobs, survives browser close | done, requeue-on-boot included |
| S3 presigned upload/download | done, API never touches video bytes |
| Secrets Manager for the Gemini key | done, no key path reaches the frontend |
| Editor (text, timing, voice, speed) | done |
| Duration fit / auto-shortening | done, capped `atempo` at mix time |
| Lip-sync | beta, off by default, failure never fails the project |
| Deploy scripts | new, see below |
| Tests | none yet — biggest gap |

## What was added this round

- `deploy/aws-deploy.sh` — run it in AWS CloudShell and it builds the whole
  stack in 13 announced steps: S3 bucket + lifecycle + CORS, Secrets Manager
  entry, least-privilege IAM role and instance profile, key pair, security
  group (22 from your IP, 80 open), Ubuntu 24.04 EC2 with a cloud-init that
  installs Docker/Node/nginx, builds the containers and the static frontend,
  then prints the URL and the generated access token. Idempotent.
  `bash deploy/aws-deploy.sh destroy` tears it down but keeps the bucket.
- `deploy/install-on-server.sh` — same end state, but run directly on an
  existing Ubuntu box (`sudo bash deploy/install-on-server.sh`). Also the
  update path: `git pull && sudo bash deploy/install-on-server.sh`.
- `AWS-HOST-GUIDE.txt` — plain-text hosting guide: architecture, real cost
  table, the three-command deploy, provider rollout order, GPU box handling,
  hardening checklist, troubleshooting, teardown.
- `docs/AWS_DEPLOY_MY.md` — the same thing in Burmese, 13 numbered steps,
  written for someone who is not comfortable on a Linux shell.

## Decisions worth not re-litigating

- **SQLite, not RDS.** Single user. A managed database would cost more than the
  compute. The job store is the only shared state; back up the docker volume.
- **Worker in its own container** (`DUB_WORKER_INLINE=0`). The API can restart
  mid-render without killing it.
- **Presigned S3 both ways.** Keeps the box at 2 GB RAM; video bytes never pass
  through FastAPI, so nginx has `client_max_body_size 0`.
- **Mock-first everywhere.** A missing optional dependency degrades to mock
  instead of crashing the pipeline. Check the Settings page if output looks
  fake.
- **Lip-sync is isolated.** Separate service, separate host, failure is logged
  and swallowed. The audio-only dub is always the deliverable.
- **Gemini is batched**, not per segment, because per-segment calls were the
  single largest cost driver in the estimate.

## Known gaps / next steps

1. **No tests.** Start with `services/pipeline.py` stage functions against the
   mock providers — they are pure enough to test cheaply.
2. **S3 CORS is `*`** after deploy. Tighten it once there is a real origin.
3. **No HTTPS by default.** certbot instructions are in the guide; nobody has
   run them.
4. **Model weights are not baked into the image**, so the first real
   transcription/TTS run is slow and the cost of a cold start is a download.
5. **No Elastic IP**, so stopping and starting the instance changes the URL.
6. **Burmese TTS quality** (MMS-TTS) is the weakest link in output quality —
   worth auditioning alternatives before polishing anything else.
7. `install-on-server.sh` assumes Ubuntu + apt. Not tested on Amazon Linux.

## Fastest way back in

```bash
# local, fully mocked
python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd backend && ../.venv/bin/uvicorn app.main:app --port 8000
cd frontend && npm install && npm run dev       # http://localhost:5173

# on AWS
bash deploy/aws-deploy.sh                        # from CloudShell
```

Read `README.md` for the requirement→code map, `docs/OPERATIONS.md` for IAM and
runtime detail, `AWS-HOST-GUIDE.txt` or `docs/AWS_DEPLOY_MY.md` for hosting.
