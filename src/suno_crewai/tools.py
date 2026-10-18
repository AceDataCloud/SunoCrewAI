"""Branded native CrewAI tools using Ace's published Suno API contract."""

from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx
from crewai.tools import BaseTool, EnvVar
from crewai.tools.tool_failure import ToolFailure, ToolFailureReason
from pydantic import BaseModel, Field, PrivateAttr

API_BASE = "https://api.acedata.cloud"
FAILED = {"failed", "error", "cancelled", "canceled", "rejected"}


class GenerateMusicInput(BaseModel):
    """Only the initial text-to-music action; no hidden fallback or retry."""

    prompt: str = Field(
        min_length=1, description="Description of the music to generate"
    )
    model: str = Field(
        min_length=1,
        description="Current public Suno model ID from Ace's model catalog",
    )
    instrumental: bool = Field(
        default=True, description="Generate instrumental music without vocals"
    )


class RetrieveTaskInput(BaseModel):
    """Read the same task; never submit another generation to wait for it."""

    task_id: str = Field(
        min_length=1, description="The task_id from the original Suno generation"
    )
    wait_seconds: int = Field(
        default=0, ge=0, le=240, description="Bounded polling time; 0 makes one query"
    )


class _SunoTool(BaseTool):
    _api_key: str = PrivateAttr()
    env_vars: list[EnvVar] = Field(
        default_factory=lambda: [
            EnvVar(
                name="ACEDATACLOUD_API_KEY",
                description="Ace API-consumer Token with Suno access",
                required=True,
            )
        ]
    )

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        token = api_key or os.environ.get("ACEDATACLOUD_API_KEY", "")
        if not token or token != token.strip() or token.lower().startswith("bearer "):
            raise ValueError(
                "Set ACEDATACLOUD_API_KEY to the raw API-consumer Token, without Bearer or spaces"
            )
        self._api_key = token

    def _request(
        self, path: str, payload: dict[str, Any], timeout: float = 30
    ) -> dict[str, Any]:
        # Exactly one HTTP attempt. A timeout on submission is an unknown outcome:
        # inspect request history rather than automatically creating another song.
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            response = client.post(
                API_BASE + path,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Accept": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        if not isinstance(body, dict):
            raise ValueError(
                "Suno returned a non-object response; inspect the original request before resubmitting"
            )
        return body


def _normalize(
    body: dict[str, Any], task_id: str, *, retrieved: bool
) -> dict[str, Any] | ToolFailure:
    if retrieved and body.get("id") and body["id"] != task_id:
        raise ValueError("The returned task ID does not match the requested task")
    result = body.get("response") if retrieved else body
    if isinstance(result, str):
        result = json.loads(result)
    result = result if isinstance(result, dict) else {}
    resolved_id = task_id or str(body.get("task_id") or "")
    # A queued response may have success=true to mean accepted. Only a retrieved
    # task with finished_at and a successful response is a completed generation.
    finished = retrieved and bool(body.get("finished_at"))
    state = str(body.get("state") or body.get("status") or "").lower()
    failed = (
        bool(body.get("error"))
        or state in FAILED
        or (finished and result.get("success") is False)
    )
    if failed or (not retrieved and result.get("success") is False):
        return ToolFailure(
            message="Suno task failed. Inspect its task or trace ID before deciding whether to submit again.",
            reason=ToolFailureReason.TOOL_REPORTED,
            code="suno_task_failed",
            retryable=False,
            details={"task_id": resolved_id},
        )
    succeeded = finished and result.get("success") is True
    data = result.get("data", []) if succeeded else []
    urls = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                url = item.get("audio_url")
                if isinstance(url, str) and url.startswith("https://"):
                    urls.append(url)
    if not resolved_id:
        raise ValueError(
            "No task ID was returned; inspect request history before submitting again"
        )
    # Deliberately exclude original request, credential/application/user identity,
    # internal routing fields, video previews and the unfiltered raw response.
    return {
        "status": "succeeded" if succeeded else "pending",
        "success": succeeded,
        "task_id": resolved_id,
        "media_urls": urls,
        "cost": result.get("cost") if succeeded else None,
    }


class SunoGenerateMusicTool(_SunoTool):
    """Submit one billable Suno music job through Ace Data Cloud."""

    name: str = "Suno by Ace Data Cloud - Generate Music"
    description: str = (
        "Generate music with Suno through Ace Data Cloud. This submits one billable job; "
        "accepted is pending, not complete. Save task_id and use Suno Retrieve Task to wait. "
        "Never repeat generation to poll or recover an unknown submission outcome."
    )
    args_schema: type[BaseModel] = GenerateMusicInput
    max_usage_count: int | None = 1

    def _run(
        self, prompt: str, model: str, instrumental: bool = True
    ) -> str | ToolFailure:
        body = self._request(
            "/suno/audios",
            {
                "action": "generate",
                "custom": False,
                "prompt": prompt,
                "model": model,
                "instrumental": instrumental,
                "async": True,
            },
            timeout=60,
        )
        result = _normalize(body, "", retrieved=False)
        return result if isinstance(result, ToolFailure) else json.dumps(result)


class SunoRetrieveTaskTool(_SunoTool):
    """Retrieve one existing Suno task, optionally waiting for its terminal result."""

    name: str = "Suno by Ace Data Cloud - Retrieve Task"
    description: str = (
        "Read the original Suno task_id, optionally wait up to 240 seconds. "
        "pending is not success. This tool never creates music; query the same ID again if still pending."
    )
    args_schema: type[BaseModel] = RetrieveTaskInput

    def _run(self, task_id: str, wait_seconds: int = 0) -> str | ToolFailure:
        deadline = time.monotonic() + wait_seconds
        while True:
            body = self._request("/suno/tasks", {"action": "retrieve", "id": task_id})
            result = _normalize(body, task_id, retrieved=True)
            if isinstance(result, ToolFailure):
                return result
            remaining = deadline - time.monotonic()
            if result["status"] != "pending" or remaining <= 0:
                return json.dumps(result)
            time.sleep(min(5, remaining))
