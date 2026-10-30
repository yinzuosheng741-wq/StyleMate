from concurrent.futures import TimeoutError as FutureTimeout
from contextvars import ContextVar
from threading import Event
from unittest.mock import Mock

import pytest

from stylemate.agent.execution import BoundedToolRunner, ToolCapacityExceeded
from stylemate.agent.middleware import ToolExecutor
from stylemate.domain.models import ToolSpec
from tests.agent.test_middleware import tool_context


def test_timed_out_work_holds_capacity_until_it_actually_finishes():
    runner = BoundedToolRunner(1)
    entered, release, done = Event(), Event(), Event()
    def handler():
        entered.set()
        release.wait(5)
        return "late result"
    try:
        future = runner.submit(handler)
        future.add_done_callback(lambda _: done.set())
        assert entered.wait(2)
        with pytest.raises(FutureTimeout):
            future.result(timeout=0.01)
        for _ in range(20):
            with pytest.raises(ToolCapacityExceeded):
                runner.submit(lambda: pytest.fail("saturated work ran"))
        assert runner.stats() == {"limit": 1, "in_flight": 1, "capacity_rejections": 20}
        release.set()
        assert done.wait(2)
        assert runner.submit(lambda: "recovered").result(timeout=2) == "recovered"
    finally:
        release.set()
        runner.shutdown()


def test_saturation_returns_structured_failure_without_retrying_handler():
    runner = BoundedToolRunner(1)
    release = Event()
    handler = Mock()
    try:
        runner.submit(lambda: release.wait(5))
        result = ToolExecutor(runner).execute(ToolSpec(name="get_weather", permission="read", retry_once=True),
                                              {}, tool_context(), handler)
        assert result.status == "failed"
        assert result.trace.summary == "tool_capacity_exhausted"
        assert runner.stats()["capacity_rejections"] == 1
        handler.assert_not_called()
    finally:
        release.set()
        runner.shutdown()


def test_worker_context_does_not_leak_between_requests_and_failure_releases_slot():
    runner = BoundedToolRunner(1)
    current = ContextVar("test_identity", default="none")
    try:
        token = current.set("first")
        assert runner.submit(current.get).result(timeout=2) == "first"
        current.reset(token)
        assert runner.submit(current.get).result(timeout=2) == "none"
        result = ToolExecutor(runner).execute(ToolSpec(name="rag_search", permission="read"), {}, tool_context(),
                                              lambda *_: 1 / 0)
        assert result.status == "failed"
        assert runner.stats()["in_flight"] == 0
        assert runner.submit(lambda: 42).result(timeout=2) == 42
    finally:
        runner.shutdown()


def test_submit_failure_after_shutdown_does_not_leak_capacity():
    runner = BoundedToolRunner(1)
    runner.shutdown()
    with pytest.raises(RuntimeError):
        runner.submit(lambda: None)
    assert runner.stats()["in_flight"] == 0
