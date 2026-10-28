"""Late provider outputs cannot escape the public chat acceptance boundary."""

import pytest
from langchain_core.messages import AIMessage

from stylemate.agent import policy
from stylemate.agent.graph import build_agent_graph
from stylemate.agent.state import initial_state
from stylemate.demo.sample_data import sample_garments
from tests.agent.test_service import service


class ClockedModel:
    def __init__(self, clock, *, late=True, failure=False, outfit=False):
        self.clock, self.late, self.failure, self.outfit = clock, late, failure, outfit
        self.calls = 0

    def bind_tools(self, _tools):
        return self

    def invoke(self, _messages):
        self.calls += 1
        if self.outfit and self.calls == 1:
            return AIMessage(content="", tool_calls=[{
                "name": "recommend_inventory_outfit", "args": {"scene": "日常"}, "id": "outfit-1",
            }])
        self.clock[0] = 100.0 if self.late else 1.0
        if self.failure:
            raise TimeoutError("private provider detail")
        return AIMessage(content="model answer")


@pytest.mark.parametrize("failure", [False, True])
def test_late_model_result_or_failure_never_starts_fallback_or_saves_model_text(monkeypatch, failure):
    clock = [0.0]
    monkeypatch.setattr(policy, "monotonic", lambda: clock[0])
    app = service()
    app.model = ClockedModel(clock, failure=failure)
    monkeypatch.setattr(app, "_route_without_model", lambda *a, **kw: pytest.fail("late fallback"))
    reply = app.chat("owner-a", "thread-a", "你好")
    assert app.model.calls == 1
    assert "时间预算" in reply.content
    assert reply.traces[0].summary == "request_deadline_exceeded"
    assert not reply.sources and not reply.outfits
    saved = app.repository.load_conversation("owner-a", "thread-a")
    assert saved.messages[-1].content == reply.content
    assert "model answer" not in str(saved.model_dump())


def test_expired_graph_stops_before_starting_model(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(policy, "monotonic", lambda: clock[0])
    model = ClockedModel(clock)
    with policy.request_policy("owner-a", "thread-a", [], timeout=1):
        clock[0] = 2.0
        with pytest.raises(policy.RequestExecutionDenied, match="request_deadline_exceeded"):
            build_agent_graph(model, []).invoke(initial_state("你好", owner_id="owner-a"))
    assert model.calls == 0


@pytest.mark.parametrize("late", [False, True])
def test_outfit_tool_results_only_accompany_an_accepted_model_reply(monkeypatch, late):
    clock = [0.0]
    monkeypatch.setattr(policy, "monotonic", lambda: clock[0])
    app = service()
    for garment in sample_garments():
        app.wardrobe_repository.save_garment("owner-a", garment)
    app.model = ClockedModel(clock, late=late, outfit=True)
    reply = app.chat("owner-a", "thread-a", "帮我看看")
    assert app.model.calls == 2
    assert bool(reply.outfits) is (not late)
    assert (reply.content == "model answer") is (not late)
    assert policy.remaining_request_seconds() is None  # Request context is reset.


def test_late_deterministic_result_is_rejected_before_persistence(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(policy, "monotonic", lambda: clock[0])
    app = service()
    original = app._route_without_model

    def late_route(*args, **kwargs):
        result = original(*args, **kwargs)
        clock[0] = 100.0
        return result

    monkeypatch.setattr(app, "_route_without_model", late_route)
    reply = app.chat("owner-a", "thread-a", "知识库里羊毛怎么洗")
    assert "时间预算" in reply.content
    assert not reply.sources and not reply.outfits
    assert app.repository.load_conversation("owner-a", "thread-a").messages[-1].content == reply.content
