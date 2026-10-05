from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Secrets (Gemini API key) are NEVER read from the frontend and never sent to it.
    In production they come from AWS Secrets Manager (see core/secrets.py).
    """

    model_config = SettingsConfigDict(env_file=".env", env_prefix="DUB_", extra="ignore")

    app_name: str = "Burmese/English Dubbing Studio"
    data_dir: str = "./data"
    database_url: str = "sqlite:///./data/dub.db"

    # single-user auth: a static token the frontend sends as Bearer
    access_token: str = "dev-local-token"
    require_auth: bool = False

    # Provider selection -- every stage is a replaceable module.
    provider_transcription: str = "mock"        # mock | faster_whisper
    provider_translation: str = "mock"          # mock | gemini
    provider_tts_my: str = "mock"               # mock | mms_tts | gemini_tts
    provider_tts_en: str = "mock"               # mock | piper | kokoro | gemini_tts
    provider_tts_fallback: str = "mock"         # gemini_tts
    provider_lipsync: str = "mock"              # mock | gpu_worker
    provider_render: str = "mock"               # mock | ffmpeg
    provider_storage: str = "local"             # local | s3

    # S3
    s3_bucket: str = "dub-studio-media"
    s3_region: str = "ap-southeast-1"
    s3_presign_ttl: int = 3600

    # Secrets Manager
    secrets_manager_gemini_id: str = "dub-studio/gemini"
    gemini_api_key: str = ""   # dev-only override, never exposed via API
    gemini_model: str = "gemini-2.0-flash"
    gemini_tts_model: str = "gemini-2.5-flash-preview-tts"

    # GPU worker (lip-sync, beta)
    lipsync_worker_url: str = "http://localhost:9100"
    lipsync_max_clip_seconds: int = 20

    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"


@lru_cache
def get_settings() -> Settings:
    return Settings()
