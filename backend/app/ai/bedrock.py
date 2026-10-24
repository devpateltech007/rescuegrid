"""Amazon Bedrock Runtime wrapper (Converse API) with timeouts, retry/backoff and
sanitized invocation records. Credentials come from the default boto3 chain only."""
from __future__ import annotations

import logging
import random
import time
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import settings

log = logging.getLogger("rescuegrid.bedrock")

RETRYABLE = {"ThrottlingException", "ServiceUnavailableException", "ModelNotReadyException",
             "InternalServerException", "ModelTimeoutException"}
FATAL_AUTH = {"ExpiredTokenException", "UnrecognizedClientException", "AccessDeniedException",
              "InvalidSignatureException"}


class BedrockError(Exception):
    def __init__(self, reason: str, attempts: int, code: str | None = None):
        super().__init__(reason)
        self.reason, self.attempts, self.code = reason, attempts, code


class BedrockClient:
    def __init__(self):
        self.enabled = settings.bedrock_enabled and bool(settings.model_id)
        self.model_id = settings.model_id
        self._client = None
        self.state = "UNVERIFIED" if self.enabled else "DISABLED"
        self.last_error: str | None = None
        self.calls_ok = 0
        self.calls_failed = 0

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client(
                "bedrock-runtime", region_name=settings.region,
                config=Config(connect_timeout=5, read_timeout=90, retries={"max_attempts": 1}))
        return self._client

    def converse(self, messages: list[dict], system: str, tool: dict | None = None,
                 max_tokens: int = 1200, model_id: str | None = None, max_attempts: int = 3) -> dict[str, Any]:
        if not self.enabled:
            raise BedrockError("Bedrock disabled by configuration (RESCUEGRID_BEDROCK=0 or no model id)", 0, "Disabled")
        kwargs: dict[str, Any] = {
            "modelId": model_id or self.model_id,
            "messages": messages,
            "system": [{"text": system}],
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0},
        }
        if tool:
            kwargs["toolConfig"] = {"tools": [tool], "toolChoice": {"tool": {"name": tool["toolSpec"]["name"]}}}
        delay = 1.0
        for attempt in range(1, max_attempts + 1):
            t0 = time.perf_counter()
            try:
                resp = self.client.converse(**kwargs)
                latency = (time.perf_counter() - t0) * 1000
                self.state, self.last_error = "OK", None
                self.calls_ok += 1
                return {"response": resp, "latency_ms": latency, "attempts": attempt,
                        "request_id": resp.get("ResponseMetadata", {}).get("RequestId")}
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "ClientError")
                msg = f"{code}: {e.response.get('Error', {}).get('Message', '')[:200]}"
                if code in FATAL_AUTH or code not in RETRYABLE or attempt == max_attempts:
                    self._fail(msg, code)
                    raise BedrockError(msg, attempt, code) from e
                log.warning("bedrock retryable %s (attempt %d)", code, attempt)
            except Exception as e:  # noqa: BLE001  (timeouts, connection errors)
                msg = f"{type(e).__name__}: {str(e)[:200]}"
                if attempt == max_attempts:
                    self._fail(msg, type(e).__name__)
                    raise BedrockError(msg, attempt, type(e).__name__) from e
            time.sleep(delay + random.random() * 0.5)
            delay *= 2
        raise BedrockError("unreachable", max_attempts)

    def _fail(self, msg: str, code: str | None) -> None:
        self.calls_failed += 1
        self.last_error = msg
        self.state = "AUTH_FAILED" if code in FATAL_AUTH else "DEGRADED"

    def status(self) -> dict:
        return {"enabled": self.enabled, "model_id": self.model_id, "state": self.state,
                "calls_ok": self.calls_ok, "calls_failed": self.calls_failed, "last_error": self.last_error,
                "region": settings.region}


bedrock = BedrockClient()


def extract_tool_input(resp: dict) -> tuple[dict | None, str]:
    content = resp["output"]["message"]["content"]
    text = " ".join(c.get("text", "") for c in content if "text" in c)
    for c in content:
        if "toolUse" in c:
            return c["toolUse"]["input"], text
    return None, text
