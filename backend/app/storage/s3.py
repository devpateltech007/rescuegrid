"""Amazon S3 evidence store. Failures are reported, never hidden; local copies always exist
so a failed upload cannot corrupt incident state."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

import boto3
from botocore.config import Config

from app.config import settings

log = logging.getLogger("rescuegrid.s3")


class S3Store:
    def __init__(self):
        self.bucket = settings.bucket
        self.enabled = settings.s3_enabled and bool(self.bucket)
        self.last_error: str | None = None
        self.uploads = 0
        self._client = None
        self._lock = threading.Lock()

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client("s3", region_name=settings.region,
                                        config=Config(connect_timeout=5, read_timeout=20, retries={"max_attempts": 3, "mode": "standard"}))
        return self._client

    def put_bytes(self, key: str, data: bytes, content_type: str) -> str | None:
        if not self.enabled:
            return None
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type,
                                   ServerSideEncryption="AES256")
            with self._lock:
                self.uploads += 1
            self.last_error = None
            return f"s3://{self.bucket}/{key}"
        except Exception as e:  # noqa: BLE001
            self.last_error = f"{type(e).__name__}: {str(e)[:160]}"
            log.warning("S3 upload failed key=%s err=%s", key, self.last_error)
            return None

    def put_file(self, key: str, path: Path, content_type: str) -> str | None:
        return self.put_bytes(key, path.read_bytes(), content_type)

    def status(self) -> dict:
        return {"enabled": self.enabled, "bucket": self.bucket if self.enabled else None,
                "uploads": self.uploads, "last_error": self.last_error,
                "state": "DISABLED" if not self.enabled else ("DEGRADED" if self.last_error else "OK")}


s3 = S3Store()
