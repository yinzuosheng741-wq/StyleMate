import json
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from stylemate.agent.graph import build_agent_graph
from stylemate.agent.middleware import ToolExecutor
from stylemate.agent.routing import route_skills
from stylemate.agent.state import initial_state
from stylemate.agent.telemetry import observe_run
from stylemate.agent.tool_results import InventoryOutfitResult
from stylemate.domain.models import ToolSpec
from tests.agent.test_graph import toolkit
from tests.agent.test_middleware import tool_context
from tests.agent.test_service import service


@pytest.mark.parametrize(("name", "arguments", "outcome", "reason"), [
    ("get_garment", {"garment_id": "missing"}, "not_found", "item_not_found"),
    ("care_guide", {"material": "毛衣"}, "needs_clarification", "missing_conditions"),
    ("search_wardrobe", {"name": "不存在的衣物"}, "empty", "no_matching_garments"),
    ("recommend_purchases", {}, "needs_clarification", "missing_conditions"),
])
def test_successful_execution_retains_distinct_business_outcome(name, arguments, outcome, reason):
    tool = next(t for t in toolkit().tools if t.name == name)
    records = []
    with observe_run(records.append):
        payload = json.loads(tool.invoke(arguments))
    assert payload["execution_status"] == "success"
    assert payload["outcome"] == outcome
    assert payload["reason_code"] == reason
    assert records[0]["tool_successes"] == 1
    assert records[0][f"tool_outcome_{outcome}"] == 1


def test_invalid_typed_tool_output_is_rejected_before_publication():
    result = ToolExecutor().execute(
        ToolSpec(name="recommend_inventory_outfit", permission="read", result_model=InventoryOutfitResult),
        {}, tool_context(), lambda *_: {"recommendations": [{"garment_ids": ["id"]}]},
    )
    assert result.status == "failed" and result.outcome == "error"
    assert result.reason_code == "invalid_tool_result"
    assert result.data is None and not result.retryable


def test_graph_forwards_outcome_metadata_to_model():
    class Model:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            payloads = [json.loads(m.content) for m in messages if isinstance(m, ToolMessage)]
            if not payloads:
                return AIMessage(content="", tool_calls=[{"name": "get_garment", "args": {"garment_id": "missing"}, "id": "read"}])
            assert payloads[-1]["outcome"] == "not_found"
            assert payloads[-1]["execution_status"] == "success"
            return AIMessage(content="未找到衣物")

    result = build_agent_graph(Model(), toolkit().tools).invoke(initial_state("查询衣柜编号missing"))
    assert result["messages"][-1].content == "未找到衣物"


@pytest.mark.parametrize("text", ["给我配身上班的衣服吧", "帮我搭套日常衣服", "想配一身通勤装"])
def test_colloquial_outfit_has_same_service_and_graph_intent(text):
    tools = toolkit()
    decision = route_skills(text, {t.name for t in tools.tools})
    assert decision.intent == "outfit" and decision.deterministic
    assert "recommend_inventory_outfit" in decision.allowed_tools
    model = Mock()
    model.bind_tools.return_value.invoke.return_value = AIMessage(content="完成")
    state = build_agent_graph(model, tools.tools).invoke(initial_state(text))
    assert state["task_intent"] == decision.intent


def test_selection_prevents_unused_weather_shortcut_calls():
    app = service()
    shortcut = Mock(side_effect=AssertionError("shortcut must not execute for a selected item"))
    app._shortcut_route = shortcut
    reply = app.chat("owner-a", "thread-a", "根据今天的天气推荐穿搭", garment_id="missing")
    shortcut.assert_not_called()
    assert "未找到" in reply.content
