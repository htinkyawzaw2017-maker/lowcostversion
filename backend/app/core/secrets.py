"""Secret resolution: AWS Secrets Manager first, env fallback for local dev.

Secrets are resolved server-side only. No endpoint ever returns a secret value.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache

from app.core.config import get_settings

log = logging.getLogger(__name__)


@lru_cache
def _from_secrets_manager(secret_id: str) -> dict:
    try:
        import boto3  # imported lazily so local dev works without AWS
    except Exception:  # pragma: no cover
        return {}
    try:
        client = boto3.client("secretsmanager", region_name=get_settings().s3_region)
        raw = client.get_secret_value(SecretId=secret_id)["SecretString"]
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"value": raw}
    except Exception as exc:
        log.warning("Secrets Manager lookup failed for %s: %s", secret_id, exc)
        return {}


def get_gemini_api_key() -> str:
    s = get_settings()
    payload = _from_secrets_manager(s.secrets_manager_gemini_id)
    return payload.get("GEMINI_API_KEY") or payload.get("value") or s.gemini_api_key


def secrets_status() -> dict:
    """Boolean-only view, safe to expose to the single-user UI."""
    return {"gemini_api_key_configured": bool(get_gemini_api_key())}
