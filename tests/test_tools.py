import json
from unittest.mock import patch

import httpx
import pytest
from crewai.tools.tool_failure import ToolFailure

from suno_crewai import SunoGenerateMusicTool, SunoRetrieveTaskTool
from suno_crewai._base import ServiceHTTPError


def reply(body, status=200):
    return httpx.Response(
        status,
        json=body,
        request=httpx.Request("POST", "https://api.acedata.cloud/suno/tasks"),
    )


def completed():
    return {
        "id": "existing",
        "finished_at": 1,
        "request": {"secret": "not-for-agent"},
        "response": {
            "success": True,
            "data": [{"audio_url": "https://example.com/music.mp3"}],
            "cost": {"amount": 0.1, "currency": "credit"},
        },
    }


def test_submit_once_and_accepted_is_pending():
    tool = SunoGenerateMusicTool(api_key="test-consumer-key")
    with patch(
        "httpx.Client.post", return_value=reply({"success": True, "task_id": "new"})
    ) as post:
        result = json.loads(tool.run(prompt="piano", model="public-model"))
        assert post.call_count == 1
        assert post.call_args.args[0] == "https://api.acedata.cloud/suno/audios"
        assert post.call_args.kwargs["json"] == {
            "action": "generate",
            "custom": False,
            "prompt": "piano",
            "model": "public-model",
            "instrumental": True,
            "async": True,
        }
        assert result == {
            "status": "pending",
            "success": False,
            "task_id": "new",
            "media_urls": [],
            "cost": None,
        }
        assert isinstance(tool.run(prompt="again", model="public-model"), ToolFailure)
        assert post.call_count == 1


def test_read_same_id_and_filter_private_fields():
    tool = SunoRetrieveTaskTool(api_key="test-consumer-key")
    with patch("httpx.Client.post", return_value=reply(completed())) as post:
        result = json.loads(tool.run(task_id="existing"))
    assert post.call_args.kwargs["json"] == {"action": "retrieve", "id": "existing"}
    assert result["status"] == "succeeded" and result["success"]
    assert result["media_urls"] == ["https://example.com/music.mp3"]
    assert "not-for-agent" not in str(result)
    assert "test-consumer-key" not in str(tool.model_dump())


def test_unfinished_preview_is_pending():
    body = completed()
    body["finished_at"] = None
    with patch("httpx.Client.post", return_value=reply(body)):
        result = json.loads(SunoRetrieveTaskTool(api_key="key").run(task_id="existing"))
    assert result["status"] == "pending" and not result["media_urls"]


def test_terminal_failure_is_structured_and_not_retryable():
    body = {
        "id": "existing",
        "finished_at": 1,
        "response": {"success": False, "error": "fixture"},
    }
    with patch("httpx.Client.post", return_value=reply(body)):
        result = SunoRetrieveTaskTool(api_key="key").run(task_id="existing")
    assert isinstance(result, ToolFailure) and not result.retryable
    assert result.code == "task_failed"


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_http_status_retained_without_retry(status):
    with patch(
        "httpx.Client.post", return_value=reply({"error": "fixture"}, status)
    ) as post:
        with pytest.raises(ServiceHTTPError) as caught:
            SunoGenerateMusicTool(api_key="key").run(prompt="piano", model="model")
    assert caught.value.status_code == status
    assert post.call_count == 1


def test_timeout_is_not_retried():
    with patch(
        "httpx.Client.post", side_effect=httpx.ReadTimeout("unknown submission outcome")
    ) as post:
        with pytest.raises(TimeoutError):
            SunoGenerateMusicTool(api_key="key").run(prompt="piano", model="model")
    assert post.call_count == 1


def test_bounded_wait_queries_only_same_task():
    pending = {"id": "existing", "finished_at": None, "response": None}
    with (
        patch(
            "httpx.Client.post", side_effect=[reply(pending), reply(completed())]
        ) as post,
        patch("suno_crewai._base.time.monotonic", side_effect=[0, 1, 2]),
        patch("suno_crewai._base.time.sleep"),
    ):
        result = json.loads(
            SunoRetrieveTaskTool(api_key="key").run(task_id="existing", wait_seconds=10)
        )
    assert result["success"] and post.call_count == 2
    assert all(call.kwargs["json"]["id"] == "existing" for call in post.call_args_list)
    assert all(call.args[0].endswith("/suno/tasks") for call in post.call_args_list)


def test_input_and_identity_checks():
    with pytest.raises(ValueError):
        SunoRetrieveTaskTool(api_key="key").run(task_id="existing", wait_seconds=241)
    with patch("httpx.Client.post", return_value=reply(completed())):
        with pytest.raises(ValueError, match="does not match"):
            SunoRetrieveTaskTool(api_key="key").run(task_id="another")
    with pytest.raises(ValueError, match="without Bearer"):
        SunoRetrieveTaskTool(api_key="Bearer key")


def test_missing_key_fails_before_network(monkeypatch):
    monkeypatch.delenv("ACEDATACLOUD_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ACEDATACLOUD_API_KEY"):
        SunoRetrieveTaskTool()


def test_missing_submission_id_is_unknown_not_success():
    with patch("httpx.Client.post", return_value=reply({"success": True})):
        with pytest.raises(ValueError, match="No task ID"):
            SunoGenerateMusicTool(api_key="key").run(prompt="piano", model="model")


@pytest.mark.parametrize("where", ["top", "nested"])
def test_failed_state_before_timestamp_is_terminal(where):
    body = completed()
    body["finished_at"] = None
    if where == "top":
        body["state"] = "failed"
    else:
        body["response"]["data"][0]["status"] = "failed"
    with patch("httpx.Client.post", return_value=reply(body)):
        result = SunoRetrieveTaskTool(api_key="key").run(task_id="existing")
    assert isinstance(result, ToolFailure) and not result.retryable


def test_no_terminal_audio_is_not_success():
    body = completed()
    body["response"]["data"] = []
    with patch("httpx.Client.post", return_value=reply(body)):
        result = SunoRetrieveTaskTool(api_key="key").run(task_id="existing")
    assert isinstance(result, ToolFailure) and result.code == "missing_terminal_media"


def test_error_and_cost_payloads_do_not_leak_private_fields():
    with patch(
        "httpx.Client.post",
        return_value=reply({"error": "private service diagnostic secret-fixture"}, 403),
    ):
        with pytest.raises(ServiceHTTPError) as error:
            SunoRetrieveTaskTool(api_key="secret-fixture").run(task_id="existing")
    assert error.value.status_code == 403
    assert "private service" not in str(error.value) and "secret-fixture" not in str(
        error.value
    )
    body = completed()
    body["response"]["cost"]["private_key"] = "private account data"
    with patch("httpx.Client.post", return_value=reply(body)):
        result = SunoRetrieveTaskTool(api_key="key").run(task_id="existing")
    assert "private account data" not in result


def test_management_token_is_rejected_before_network():
    with pytest.raises(ValueError):
        SunoRetrieveTaskTool(api_key="platform-management-fixture")
