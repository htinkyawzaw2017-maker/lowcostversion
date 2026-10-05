"""Storage abstraction: S3 (presigned uploads/downloads) or local disk for dev.

Uploads never pass through the API server -- the browser PUTs straight to S3
with a short-lived presigned URL.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from app.core.config import get_settings


@dataclass
class PresignedUpload:
    url: str
    method: str
    key: str
    headers: dict
    expires_in: int


class LocalStorage:
    name = "local"

    def __init__(self):
        self.root = os.path.abspath(os.path.join(get_settings().data_dir, "media"))
        os.makedirs(self.root, exist_ok=True)

    def path(self, key: str) -> str:
        p = os.path.join(self.root, key)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        return p

    def exists(self, key: str) -> bool:
        return os.path.exists(os.path.join(self.root, key))

    def size(self, key: str) -> int:
        try:
            return os.path.getsize(os.path.join(self.root, key))
        except OSError:
            return 0

    def presign_upload(self, key: str, content_type: str) -> PresignedUpload:
        # dev mode: the frontend PUTs to our own endpoint with identical semantics
        return PresignedUpload(
            url=f"/api/storage/local/{key}",
            method="PUT",
            key=key,
            headers={"Content-Type": content_type},
            expires_in=get_settings().s3_presign_ttl,
        )

    def presign_download(self, key: str) -> str:
        return f"/api/storage/local/{key}"

    def put_file(self, local_path: str, key: str) -> str:
        dst = self.path(key)
        if os.path.abspath(local_path) != os.path.abspath(dst):
            shutil.copyfile(local_path, dst)
        return key


class S3Storage:
    name = "s3"

    def __init__(self):
        import boto3

        s = get_settings()
        self.bucket, self.ttl = s.s3_bucket, s.s3_presign_ttl
        self.client = boto3.client("s3", region_name=s.s3_region)
        self.cache = os.path.abspath(os.path.join(s.data_dir, "cache"))
        os.makedirs(self.cache, exist_ok=True)

    def path(self, key: str) -> str:
        """Local working copy of an S3 object (downloaded on demand)."""
        p = os.path.join(self.cache, key)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if not os.path.exists(p):
            self.client.download_file(self.bucket, key, p)
        return p

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def size(self, key: str) -> int:
        try:
            return int(self.client.head_object(Bucket=self.bucket, Key=key)["ContentLength"])
        except Exception:
            return 0

    def presign_upload(self, key: str, content_type: str) -> PresignedUpload:
        url = self.client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=self.ttl,
        )
        return PresignedUpload(url, "PUT", key, {"Content-Type": content_type}, self.ttl)

    def presign_download(self, key: str) -> str:
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=self.ttl
        )

    def put_file(self, local_path: str, key: str) -> str:
        self.client.upload_file(local_path, self.bucket, key)
        return key


_instance = None


def storage():
    global _instance
    if _instance is None:
        _instance = S3Storage() if get_settings().provider_storage == "s3" else LocalStorage()
    return _instance
