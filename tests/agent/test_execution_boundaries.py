"""Regression cases for real thread boundaries and business-tool composition."""

import json
from concurrent.futures import TimeoutError as FutureTimeout
from threading import Event
from unittest.mock import Mock

import pytest
import requests

from stylemate.agent.middleware import ToolExecutor
from stylemate.agent.policy import denied_tool_payload, request_policy
from stylemate.agent.tools.location_weather import WeatherResult
from stylemate.domain.models import ToolSpec
from tests.agent.test_middleware import tool_context
from tests.agent.test_service import service


def test_read_executor_cannot_execute_write_preparation():
    handler = Mock()
    result = ToolExecutor().execute(ToolSpec(name="delete", permission="write_prepare"), {}, tool_context(), handler)
    assert result.trace.summary == "read_executor_permission_denied"
    handler.assert_not_called()


def test_worker_inherits_request_capabilities_and_context_is_restored():
    def handler(arguments, context):
        return json.loads(denied_tool_payload("delete_garment", "owner-a", "thread-a"))

    with request_policy("owner-a", "thread-a", {"rag_search"}):
        result = ToolExecutor().execute(ToolSpec(name="rag_search", permission="read"), {}, tool_context(), handler)
    assert result.data["trace"]["summary"] == "tool_capability_denied"
    assert denied_tool_payload("anything", "other", "other") is None


def test_expired_request_never_starts_a_worker():
    handler = Mock()
    with request_policy("owner-a", "thread-a", {"rag_search"}, timeout=0):
        result = ToolExecutor().execute(ToolSpec(name="rag_search", permission="read"), {}, tool_context(), handler)
    assert result.trace.summary == "request_deadline_exceeded"
    handler.assert_not_called()


def test_wait_timeout_does_not_overlap_a_retry_or_accept_late_data():
    entered, release, finished = Event(), Event(), Event()
    calls = []

    def handler(arguments, context):
        calls.append(1)
        entered.set()
        try:
            release.wait(5)
            return {"temperature_c": 42}
        finally:
            finished.set()

    try:
        with request_policy("owner-a", "thread-a", {"get_weather"}, timeout=0.1):
            result = ToolExecutor().execute(
                ToolSpec(name="get_weather", permission="read", retry_once=True), {}, tool_context(), handler,
            )
        assert entered.is_set()
        assert result.status == "failed" and result.data is None
        assert result.trace.summary == "request_deadline_exceeded"
        assert calls == [1]
        assert not finished.is_set()
    finally:
        release.set()
        assert finished.wait(5)
    assert result.data is None  # Finishing the abandoned read cannot mutate the result.


def test_tool_wait_timeout_with_remaining_budget_is_not_retried(monkeypatch):
    waiter = Mock(side_effect=FutureTimeout())
    monkeypatch.setattr(ToolExecutor, "_call_with_timeout", waiter)
    with request_policy("owner-a", "thread-a", {"get_weather"}):
        result = ToolExecutor().execute(
            ToolSpec(name="get_weather", permission="read", retry_once=True), {}, tool_context(), Mock(),
        )
    assert result.trace.summary == "tool_wait_timeout"
    assert waiter.call_count == 1


def test_completed_network_failure_can_retry_only_inside_request_deadline():
    def handler(arguments, context):
        policy.deadline = 0
        raise requests.Timeout("private provider response")

    call = Mock(side_effect=handler)
    with request_policy("owner-a", "thread-a", {"get_weather"}) as policy:
        result = ToolExecutor().execute(
            ToolSpec(name="get_weather", permission="read", retry_once=True), {}, tool_context(), call,
        )
    assert call.call_count == 1
    assert result.trace.summary == "request_deadline_exceeded"


@pytest.mark.parametrize("message", ["天气穿搭", "去成都旅游4天，主要城市观光"])
def test_weather_business_flows_reuse_one_successful_tool_result(message):
    app = service()
    weather = Mock(return_value=WeatherResult(available=True, city="成都", summary="小雨", temperature_c=18))
    app.weather_client = Mock(weather=weather)
    reply = app.chat("owner-a", "thread-a", message)
    assert weather.call_count == 1
    assert "18" in reply.content
    assert [t.name for t in reply.traces].count("get_weather") == 1


@pytest.mark.parametrize("message", ["天气穿搭", "去成都旅游4天，主要城市观光"])
def test_blocked_weather_does_not_call_provider_through_a_business_shortcut(message):
    app = service()
    app.weather_client = Mock()
    toolkit = app._toolkit("owner-a", "thread-a")
    state = app.repository.load_conversation("owner-a", "thread-a")
    with request_policy("owner-a", "thread-a", {"travel_packing", "recommend_open_outfit", "recommend_inventory_outfit"}):
        if message == "天气穿搭":
            app._shortcut_route("owner-a", "thread-a", message, state=state)
        else:
            app._travel_route(toolkit, destination="成都", days=4, activities=[])
    app.weather_client.weather.assert_not_called()
