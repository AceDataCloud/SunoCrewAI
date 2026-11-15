"""Inspect an ordinary PyPI install without generating or querying media."""

import importlib
import json
import os
import sys
from importlib.metadata import distributions, version
from pathlib import Path
from unittest.mock import patch

PACKAGE = "crewai-suno"
EXPECTED_WHEEL_SHA256 = (
    "c00d2d011c72f0b1d294ce020b06c20668ef8d4572aaffbc53874341bc707ecf"
)
BRANDS = {
    "crewai-suno",
    "crewai-seedance",
    "crewai-happyhorse",
    "crewai-gpt-image",
    "crewai-nano-banana",
}


def main():
    report = json.loads(Path(sys.argv[1]).read_text())
    installed = {d.metadata["Name"].lower().replace("_", "-") for d in distributions()}
    assert installed & BRANDS == {PACKAGE}, "brand isolation failed"
    entry = next(
        item
        for item in report["install"]
        if item["metadata"]["name"].lower().replace("_", "-") == PACKAGE
    )
    download = entry["download_info"]
    assert download["url"].startswith("https://files.pythonhosted.org/")
    assert download["archive_info"]["hashes"]["sha256"] == EXPECTED_WHEEL_SHA256
    assert version(PACKAGE) == "0.1.0"
    os.environ.update(
        CREWAI_DISABLE_TELEMETRY="true",
        CREWAI_TELEMETRY_DISABLED="true",
        CREWAI_TRACING_ENABLED="false",
        OTEL_SDK_DISABLED="true",
    )
    with patch(
        "socket.socket.connect", side_effect=AssertionError("network forbidden")
    ):
        from crewai import Agent, BaseLLM
        from crewai.tools import BaseTool

        module = importlib.import_module("suno_crewai")
        module_file = Path(module.__file__).resolve()
        assert Path(sys.prefix).resolve() in module_file.parents

        class RegistrationOnlyLLM(BaseLLM):
            def call(self, *args, **kwargs):
                raise AssertionError("no model call is allowed")

        tools = []
        details = []
        for name, field in [
            ("SunoGenerateMusicTool", "prompt"),
            ("SunoRetrieveTaskTool", "task_id"),
        ]:
            tool = getattr(module, name)(api_key="consumer-fixture-only")
            assert isinstance(tool, BaseTool)
            assert field in tool.args_schema.model_fields
            assert "Suno" in tool.name and "Ace Data Cloud" in tool.name
            assert "consumer-fixture-only" not in str(tool.model_dump())
            tools.append(tool)
            details.append(
                {
                    "class": name,
                    "name": tool.name,
                    "fields": sorted(tool.args_schema.model_fields),
                }
            )
        agent = Agent(
            role="Suno tool interface verifier",
            goal="Inspect tool registration only",
            backstory="No generation or retrieval is executed.",
            tools=tools,
            llm=RegistrationOnlyLLM(model="local-registration-only"),
            allow_delegation=False,
            verbose=False,
        )
        assert len(agent.tools) == 2
    result = {
        "package": PACKAGE,
        "version": version(PACKAGE),
        "crewai": version("crewai"),
        "python": sys.version.split()[0],
        "module_file": str(module_file),
        "ordinary_pip_source": download["url"],
        "wheel_sha256": EXPECTED_WHEEL_SHA256,
        "installed_service_brands": sorted(installed & BRANDS),
        "tools": details,
        "agent_registration": "passed",
        "api_key_excluded_from_serialization": True,
        "external_model_calls": 0,
        "media_generation_calls": 0,
        "task_queries": 0,
        "billing_verified": False,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
