import json
import logging
from unittest.mock import Mock

import pytest
import requests
from langchain_core.messages import AIMessage

from stylemate.agent.middleware import ToolExecutor
from stylemate.agent.telemetry import current_run_id, observe_run
from stylemate.domain.models import ToolSpec
from tests.agent.test_middleware import tool_context
from tests.agent.test_service import service


def test_public_chat_correlates_saved_reply_and_content_free_diagnostics(caplog):
    app = service()
    records = []
    app.observer = records.append
    with caplog.at_level(logging.INFO, logger="stylemate.agent.telemetry"):
        reply = app.chat("private-owner", "private-conversation", "查看衣橱 private-question")
    assert len(records) == 1
    record = records[0]
    assert record["run_id"] == reply.run_id
    assert app.repository.load_conversation("private-owner", "private-conversation").messages[-1].run_id == reply.run_id
    assert record["tool_calls"] >= 1
    assert record["tool_attempts"] >= 1
    assert record["outcome"] == "completed"
    assert "private-" not in json.dumps(record) + caplog.text
    assert current_run_id() is None


def test_failed_request_is_recorded_once_without_exception_text(monkeypatch):
    app = service()
    records = []
    app.observer = records.append
    def fail(*args):
        raise RuntimeError("private-exception")
    monkeypatch.setattr(app, "_chat", fail)
    with pytest.raises(RuntimeError):
        app.chat("a", "b", "你好")
    assert len(records) == 1 and records[0]["outcome"] == "failed"
    assert "private" not in json.dumps(records)
    assert current_run_id() is None


def test_model_calls_are_counted_and_observer_failure_does_not_break_chat():
    app = service()
    records = []
    app.model = Mock()
    app.model.bind_tools.return_value.invoke.return_value = AIMessage(content="hello")
    app.observer = records.append
    app.chat("a", "b", "你好")
    assert records[0]["model_calls"] == 1
    app.observer = Mock(side_effect=RuntimeError("private-key"))
    assert app.chat("a", "b", "你好").content == "hello"


def test_network_retry_counts_actual_attempts_and_context_is_restored():
    records = []
    call = Mock(side_effect=[requests.Timeout(), "ok"])
    with observe_run(records.append) as observation:
        parent = current_run_id()
        with observe_run() as nested:
            assert current_run_id() == nested.run_id != parent
        assert current_run_id() == parent
        result = ToolExecutor().execute(ToolSpec(name="get_weather", permission="read", retry_once=True),
                                        {}, tool_context(), lambda *_: call())
        observation.outcome = "completed"
    assert result.status == "success"
    assert records[0]["tool_attempts"] == 2
    assert records[0]["tool_successes"] == 1
    assert current_run_id() is None


def test_local_log_is_deduplicated_rotating_and_excludes_provider_logs(tmp_path):
    from stylemate.agent.telemetry import configure_run_logging, logger
    before = list(logger.handlers)
    previous_level = logger.level
    try:
        configure_run_logging(tmp_path)
        configure_run_logging(tmp_path)
        added = [handler for handler in logger.handlers if handler not in before]
        assert len(added) == 1
        assert added[0].maxBytes == 1024 * 1024 and added[0].backupCount == 3
        logging.getLogger("test_provider").warning("private-provider-body")
        with observe_run() as run:
            run.outcome = "completed"
        added[0].flush()
        text = (tmp_path / "agent-runs.log").read_text("utf-8")
        assert run.run_id in text
        assert "private-provider" not in text
    finally:
        for handler in list(logger.handlers):
            if handler not in before:
                logger.removeHandler(handler)
                handler.close()
        logger.setLevel(previous_level)


def test_late_worker_cannot_change_closed_run_counters():
    from threading import Event

    from stylemate.agent.execution import BoundedToolRunner
    from stylemate.agent.telemetry import record_counter
    runner = BoundedToolRunner(1)
    release = Event()
    snapshots = []
    def late():
        release.wait(5)
        record_counter("tool_attempts")
    try:
        with observe_run(snapshots.append) as observation:
            future = runner.submit(late)
        release.set()
        future.result(timeout=2)
        assert observation.counts["tool_attempts"] == 0
        assert snapshots[0]["tool_attempts"] == 0
    finally:
        release.set()
        runner.shutdown()
