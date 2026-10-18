"""Single-attempt consumer-token transport and strict asynchronous task results.

Shared safety semantics with the independently reviewed media packages.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, ClassVar
from urllib.parse import urlsplit

import httpx
from crewai.tools import BaseTool, EnvVar
from crewai.tools.tool_failure import ToolFailure, ToolFailureReason
from pydantic import BaseModel, Field, PrivateAttr

API_BASE = "https://api.acedata.cloud"
FAILED = {"failed", "error", "cancelled", "canceled", "rejected"}
PENDING = {"pending", "queued", "processing", "running", "submitted", "created"}


class ServiceHTTPError(RuntimeError):
    """Preserve HTTP meaning without exposing response bodies or request headers."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(
            f"Service HTTP {status_code}; inspect the request using its task/trace ID. Do not include your Token."
        )


class RetrieveTaskInput(BaseModel):
    task_id: str = Field(
        min_length=1,
        description="The original task_id from generation; never create another job to poll",
    )
    wait_seconds: int = Field(
        default=0, ge=0, le=240, description="Bounded same-ID polling; 0 queries once"
    )


class ServiceTool(BaseTool):
    _api_key: str = PrivateAttr()
    service: ClassVar[str]
    task_path: ClassVar[str]
    env_vars: list[EnvVar] = Field(
        default_factory=lambda: [
            EnvVar(
                name="ACEDATACLOUD_API_KEY",
                description="Raw Ace API-consumer Token with the selected service access",
                required=True,
            )
        ]
    )

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        token = api_key or os.environ.get("ACEDATACLOUD_API_KEY", "")
        if (
            not token
            or token != token.strip()
            or token.lower().startswith(("bearer ", "platform-"))
        ):
            raise ValueError(
                "Set ACEDATACLOUD_API_KEY to the raw API-consumer Token, without Bearer, spaces or platform management credentials"
            )
        self._api_key = token

    def _request(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=45, follow_redirects=False) as client:
                response = client.post(
                    API_BASE + path,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Accept": "application/json",
                    },
                    json=payload,
                )
                if response.status_code >= 300:
                    raise ServiceHTTPError(response.status_code)
                try:
                    body = response.json()
                except ValueError:
                    raise ValueError(
                        "Invalid service JSON; check request history before submitting again"
                    ) from None
        except httpx.TimeoutException:
            raise TimeoutError(
                "Request timed out; submission outcome may be unknown. Inspect request history before any resubmission."
            ) from None
        except httpx.TransportError:
            raise ConnectionError(
                "Service connection failed; inspect request history before any resubmission."
            ) from None
        if not isinstance(body, dict):
            raise ValueError(
                "Invalid service response shape; check request history before submitting again"
            )
        return body

    def _failure(self, task_id: str, code: str = "task_failed") -> ToolFailure:
        return ToolFailure(
            message=f"{self.service} task failed or returned an invalid terminal result; inspect its task/trace ID before resubmitting.",
            reason=ToolFailureReason.TOOL_REPORTED,
            code=code,
            retryable=False,
            details={"task_id": task_id},
        )

    def _media_urls(self, result: dict[str, Any]) -> list[str]:
        raise NotImplementedError

    def _normalize(
        self, body: dict[str, Any], task_id: str, *, retrieved: bool
    ) -> dict[str, Any] | ToolFailure:
        if retrieved:
            returned_id = body.get("id") or body.get("task_id")
            if returned_id and returned_id != task_id:
                raise ValueError("Returned task ID does not match the requested task")
        result = body.get("response") if retrieved else body
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except ValueError:
                return self._failure(task_id, "invalid_terminal_result")
        result = result if isinstance(result, dict) else {}
        resolved_id = task_id or str(
            body.get("task_id")
            or (
                body.get("task", {}).get("id")
                if isinstance(body.get("task"), dict)
                else ""
            )
            or ""
        )
        finished = retrieved and bool(body.get("finished_at"))
        # Check service state within data/content, including item lists, before
        # interpreting the envelope success flag. Do not recurse arbitrary fields.
        states: list[str] = [
            str(body[key]).lower()
            for key in ("state", "status")
            if isinstance(body.get(key), str)
        ]
        errors = [bool(body.get("error")), bool(result.get("error"))]

        def inspect(node: Any) -> None:
            if isinstance(node, list):
                for item in node:
                    inspect(item)
            elif isinstance(node, dict):
                for key in ("state", "status"):
                    if isinstance(node.get(key), str):
                        states.append(node[key].lower())
                if node.get("error") or node.get("success") is False:
                    errors.append(True)
                for key in ("data", "content", "task"):
                    if key in node:
                        inspect(node[key])

        inspect(body if not retrieved else result)
        failed = any(errors) or any(state in FAILED for state in states)
        if (
            any(state in FAILED for state in states)
            or body.get("error")
            or (finished and failed)
            or (not retrieved and failed)
        ):
            return self._failure(resolved_id)
        if not resolved_id:
            raise ValueError(
                "No task ID returned; inspect request history before any resubmission"
            )
        succeeded = (
            finished
            and result.get("success") is True
            and not any(s in PENDING for s in states)
        )
        urls = self._media_urls(result) if succeeded else []
        if succeeded and not urls:
            return self._failure(resolved_id, "missing_terminal_media")
        cost = result.get("cost") if succeeded else None
        cost = (
            {
                k: v
                for k, v in cost.items()
                if (
                    k in {"amount", "list_amount"}
                    and isinstance(v, (int, float))
                    and not isinstance(v, bool)
                )
                or (k == "currency" and v == "credit")
            }
            if isinstance(cost, dict)
            else None
        )
        return {
            "status": "succeeded" if succeeded else "pending",
            "success": succeeded,
            "task_id": resolved_id,
            "media_urls": urls,
            "cost": cost,
        }

    def _retrieve(self, task_id: str, wait_seconds: int = 0) -> str | ToolFailure:
        deadline = time.monotonic() + wait_seconds
        while True:
            body = self._request(self.task_path, {"action": "retrieve", "id": task_id})
            result = self._normalize(body, task_id, retrieved=True)
            if isinstance(result, ToolFailure):
                return result
            remaining = deadline - time.monotonic()
            if result["status"] != "pending" or remaining <= 0:
                return json.dumps(result)
            time.sleep(min(5, remaining))


def https_urls(values: list[Any]) -> list[str]:
    urls = []
    for value in values:
        if isinstance(value, str):
            parts = urlsplit(value)
            if (
                parts.scheme == "https"
                and parts.hostname
                and not parts.username
                and not parts.password
                and value not in urls
            ):
                urls.append(value)
    return urls
