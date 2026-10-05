# Operations

## Topology

| Component | Host | Notes |
|---|---|---|
| API + worker | one small CPU instance (2 vCPU / 4 GB) | FastAPI + SQLite + durable job runner |
| Frontend | static build on S3/CloudFront, or served by the same box | no secrets in the bundle |
| Media | S3 bucket | presigned PUT for uploads, presigned GET for downloads |
| Secrets | AWS Secrets Manager (`dub-studio/gemini`) | read only by the API/worker role |
| Lip-sync | separate GPU instance, started on demand | `--profile gpu`, beta only |

Running the worker in a separate process (`DUB_WORKER_INLINE=0` + `python -m app.workers.runner`)
is recommended: the API can restart without killing a render.

## Why processing survives the browser

Every unit of work is a `jobs` row. The HTTP handler only inserts the row and returns `202`. The
worker claims pending jobs in creation order, writes progress and logs back to the row, and on
startup requeues anything left in `running` after a crash. The UI is a pure observer — polling it
or closing it changes nothing.

## S3

Bucket CORS (needed for direct browser PUT):

```json
[{
  "AllowedMethods": ["PUT", "GET", "HEAD"],
  "AllowedOrigins": ["https://your-app-host"],
  "AllowedHeaders": ["*"],
  "ExposeHeaders": ["ETag"],
  "MaxAgeSeconds": 3000
}]
```

Lifecycle: expire `*/source/*` and `*/audio/*` after 30 days, keep `*/exports/*`. Intermediate
segment WAVs are regenerable, so they are the cheapest thing to drop.

## IAM (API/worker role, least privilege)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow",
     "Action": ["s3:GetObject", "s3:PutObject", "s3:HeadObject"],
     "Resource": "arn:aws:s3:::dub-studio-media/*"},
    {"Effect": "Allow",
     "Action": ["secretsmanager:GetSecretValue"],
     "Resource": "arn:aws:secretsmanager:*:*:secret:dub-studio/gemini-*"}
  ]
}
```

The GPU worker role needs S3 read/write only — it never touches Secrets Manager.

## Secret handling rules enforced in code

- `core/secrets.py` is the only reader of the Gemini key; it prefers Secrets Manager and falls back
  to an env var for local development.
- `/api/config` exposes `{"gemini_api_key_configured": true|false}` — a boolean, never the value.
- No key is ever passed to the frontend, embedded in a build, or written into a job log.
- Gemini is called server-side only; the browser cannot reach `generativelanguage.googleapis.com`
  with our credentials.

## Single-user auth

Set `DUB_REQUIRE_AUTH=true` and `DUB_ACCESS_TOKEN=<long random string>`; the frontend sends it as a
bearer token from `localStorage.dub_token`. For a private deployment, also put the box behind a
VPN, Cloudflare Access, or an IP allowlist.

## Local model setup

```bash
pip install faster-whisper                      # transcription
pip install transformers torch                  # MMS-TTS (Burmese)
pip install piper-tts                           # English, and download a voice:
#   models/piper/en_US-amy-medium.onnx(.json)
pip install kokoro soundfile                    # alternative English voice
```

First run downloads model weights; cache them into the image or an EBS volume so cold starts stay cheap.

## Lip-sync beta

Point `LIPSYNC_ENGINE_CMD` at your inference command, using `{video}`, `{audio}` and `{out}`:

```bash
export LIPSYNC_ENGINE_CMD='python inference.py --face {video} --audio {audio} --outfile {out}'
uvicorn app.workers.gpu_lipsync_worker:app --host 0.0.0.0 --port 9100
```

Constraints are enforced server-side: clips longer than `LIPSYNC_MAX_CLIP_SECONDS` (default 20s) are
rejected with HTTP 400, and the feature assumes a single front-facing speaker. Without an engine
configured the worker simulates success so the UI flow stays testable.

Failure policy: the pipeline logs the failure, marks only the lip-sync job failed, and leaves the
project status and all audio-only artifacts intact.

## Troubleshooting

| Symptom | Check |
|---|---|
| Everything says `mock-*` | `/settings` page — a provider failed to import and fell back; check API logs |
| `artifact not ready` | the render job has not finished; see the Jobs tab |
| Segments marked `long` | edit the line or lower speed, then **Re-voice**; mix applies a capped `atempo` |
| Upload 403 | presigned URL expired (`DUB_S3_PRESIGN_TTL`) or bucket CORS missing |
