"""A real CrewAI tool cycle, with a local model fixture and mocked Suno query."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import httpx
from crewai import LLM, Agent, Crew, Task

from suno_crewai import SunoRetrieveTaskTool


def test_agent_queries_existing_suno_task_without_generation(monkeypatch):
    monkeypatch.setenv("CREWAI_TELEMETRY_DISABLED", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    monkeypatch.setenv("CREWAI_TRACING_ENABLED", "false")
    requests = []

    class ModelFixture(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            tool_results = [m for m in body["messages"] if m.get("role") == "tool"]
            if tool_results:
                result = json.loads(tool_results[-1]["content"])
                assert result["status"] == "succeeded"
                message = {
                    "role": "assistant",
                    "content": "Existing Suno task succeeded.",
                }
                finish_reason = "stop"
            else:
                assert len(body["tools"]) == 1
                name = body["tools"][0]["function"]["name"]
                assert "suno" in name.lower() and "retrieve" in name.lower()
                message = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "read-only",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(
                                    {"task_id": "existing", "wait_seconds": 0}
                                ),
                            },
                        }
                    ],
                }
                finish_reason = "tool_calls"
            response = json.dumps(
                {
                    "id": "local",
                    "object": "chat.completion",
                    "created": 1,
                    "model": body["model"],
                    "choices": [
                        {"index": 0, "message": message, "finish_reason": finish_reason}
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

    server = ThreadingHTTPServer(("127.0.0.1", 0), ModelFixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        llm = LLM(
            model="gpt-4.1-mini",
            custom_openai=True,
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="local-fixture",
            max_retries=0,
        )
        tool = SunoRetrieveTaskTool(api_key="test-key")
        agent = Agent(
            role="Suno task reader",
            goal="Query the existing task once",
            backstory="Never generate new music",
            tools=[tool],
            llm=llm,
            function_calling_llm=llm,
            allow_delegation=False,
            max_iter=3,
            max_retry_limit=0,
        )
        task = Task(
            description="Query existing task existing and report its state",
            expected_output="Task state",
            agent=agent,
        )
        body = {
            "id": "existing",
            "finished_at": 1,
            "response": {
                "success": True,
                "data": [{"audio_url": "https://example.com/audio.mp3"}],
            },
        }
        response = httpx.Response(
            200,
            json=body,
            request=httpx.Request("POST", "https://api.acedata.cloud/suno/tasks"),
        )
        with patch("httpx.Client.post", return_value=response) as query:
            result = Crew(
                agents=[agent], tasks=[task], memory=False, tracing=False
            ).kickoff()
        assert result.raw == "Existing Suno task succeeded."
        assert query.call_count == 1
        assert query.call_args.args[0] == "https://api.acedata.cloud/suno/tasks"
        assert query.call_args.kwargs["json"] == {
            "action": "retrieve",
            "id": "existing",
        }
        assert len(requests) == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
