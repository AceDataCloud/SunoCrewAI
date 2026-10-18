"""Suno music generation and same-task retrieval for CrewAI."""

from __future__ import annotations

import json
from typing import Any

from crewai.tools.tool_failure import ToolFailure
from pydantic import BaseModel, ConfigDict, Field

from suno_crewai._base import RetrieveTaskInput, ServiceTool, https_urls


class GenerateMusicInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, description="Description of music to generate")
    model: str = Field(
        min_length=1, description="Current public Suno model ID, passed unchanged"
    )
    instrumental: bool = Field(
        default=True, description="Generate instrumental music without vocals"
    )


class _SunoTool(ServiceTool):
    service = "Suno"
    task_path = "/suno/tasks"

    def _media_urls(self, result: dict[str, Any]) -> list[str]:
        data = result.get("data") or []
        return https_urls(
            [item.get("audio_url") for item in data if isinstance(item, dict)]
            if isinstance(data, list)
            else []
        )


class SunoGenerateMusicTool(_SunoTool):
    name: str = "Suno by Ace Data Cloud - Generate Music"
    description: str = (
        "Generate music with Suno through Ace Data Cloud. This submits one billable job; "
        "accepted is pending, not complete. Save task_id and use Retrieve Task to wait. "
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
        )
        result = self._normalize(body, "", retrieved=False)
        return result if isinstance(result, ToolFailure) else json.dumps(result)


class SunoRetrieveTaskTool(_SunoTool):
    name: str = "Suno by Ace Data Cloud - Retrieve Task"
    description: str = (
        "Read an existing Suno task_id, optionally wait up to240 seconds. pending is not success. "
        "This tool never creates music; query the same ID if still pending."
    )
    args_schema: type[BaseModel] = RetrieveTaskInput

    def _run(self, task_id: str, wait_seconds: int = 0) -> str | ToolFailure:
        return self._retrieve(task_id, wait_seconds)
