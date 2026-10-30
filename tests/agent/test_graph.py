from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from stylemate.agent.graph import MAX_MODEL_CALLS, MAX_TOOL_CALLS, build_agent_graph
from stylemate.agent.state import initial_state
from stylemate.agent.toolkit import AgentToolkit, build_toolkit
from stylemate.domain.models import Garment
from stylemate.repositories.agent_session import SessionAgentRepository
from stylemate.repositories.session import SessionWardrobeRepository
from stylemate.services.wardrobe_service import WardrobeService
from stylemate.storage.images import SessionImageStore


class FakeToolCallModel:
    def __init__(self, name: str, arguments: dict):
        self.name, self.arguments = name, arguments

    def bind_tools(self, tools):
        self.tools = tools
        return self

    def invoke(self, _messages):
        if not hasattr(self, "called"):
            self.called = True
            return AIMessage(content="", tool_calls=[{"name": self.name, "args": self.arguments, "id": "call-1"}])
        return AIMessage(content="已完成。")


class RepeatingToolCallModel:
    def __init__(self):
        self.calls = 0

    def bind_tools(self, _tools):
        return self

    def invoke(self, _messages):
        self.calls += 1
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "get_user_location",
                    "args": {},
                    "id": f"loop-{self.calls}",
                }
            ],
        )


def toolkit() -> AgentToolkit:
    wardrobe = SessionWardrobeRepository({})
    wardrobe.save_garment("owner-a", Garment(id="g-1", name="白衬衫", category="上装", primary_color="白色", seasons=["春"], styles=["通勤"], source="manual"))
    return build_toolkit(owner_id="owner-a", conversation_id="thread-a", app_mode="demo", wardrobe_repository=wardrobe, agent_repository=SessionAgentRepository({}), wardrobe_service=WardrobeService(wardrobe, SessionImageStore({}), 1024), weather_client=type("Weather", (), {"weather": lambda self, city: type("Result", (), {"available": True, "city": city, "summary": "晴", "temperature_c": 28, "humidity": 60, "reason": ""})()})())


def test_graph_routes_model_tool_call_and_returns_trace():
    tools = toolkit()
    result = build_agent_graph(FakeToolCallModel("get_weather", {"city": "杭州"}), tools.tools).invoke(initial_state("杭州天气怎么样", owner_id="owner-a"))
    assert result["messages"][-1].content == "已完成。"
    assert result["traces"][-1]["name"] == "get_weather"


def test_write_tool_updates_pending_state_but_not_wardrobe():
    tools = toolkit()
    result = build_agent_graph(FakeToolCallModel("delete_garment", {"garment_id": "g-1"}), tools.tools).invoke(initial_state("删除白衬衫", owner_id="owner-a", conversation_id="thread-a"))
    assert result["pending_action"]["operation"] == "delete"
    assert tools.wardrobe.get_garment("owner-a", "g-1") is not None


def test_graph_stops_a_model_that_continuously_requests_tools():
    tools = toolkit()
    model = RepeatingToolCallModel()

    result = build_agent_graph(model, tools.tools).invoke(
        initial_state(
            "继续调用工具",
            owner_id="owner-a",
            conversation_id="thread-a",
        )
    )

    assert model.calls <= MAX_MODEL_CALLS
    assert result["model_calls"] <= MAX_MODEL_CALLS
    assert result["tool_calls"] <= MAX_TOOL_CALLS
    assert "上限" in result["messages"][-1].content
    assert not result["messages"][-1].tool_calls


def test_every_agent_tool_exposes_a_strict_task_specific_schema():
    tools = {tool.name: tool for tool in toolkit().tools}
    expected_fields = {
        "get_user_location": set(),
        "get_weather": {"city"},
        "get_garment": {"garment_id"},
        "recommend_size": {"height_cm", "weight_kg", "fit_preference"},
            "care_guide": {"material"},
            "rag_search": {"query"},
            "recommend_open_outfit": {
                "scene",
                "target_date",
                "city",
                "target_season",
                "temperature_c",
                "weather_condition",
                "style_preference",
                "color_preference",
                "fit_preference",
                "extra_constraints",
                "candidate_garment_ids",
                "required_garment_id",
            },
            "recommend_purchases": {"season", "scene", "temperature_c"},
            "travel_packing": {
                "destination",
                "days",
                "activities",
                "temperature_c",
                "weather_condition",
            },
        "search_wardrobe": {"name", "category", "color", "season", "style"},
        "recommend_inventory_outfit": {
            "scene",
            "target_date",
            "city",
            "target_season",
            "temperature_c",
            "weather_condition",
            "style_preference",
            "color_preference",
            "fit_preference",
            "extra_constraints",
            "candidate_garment_ids",
            "required_garment_id",
        },
        "wardrobe_gap_check": {"season"},
        "item_style_analysis": {"garment_id"},
        "add_garment": {"metadata"},
        "update_garment": {"garment_id", "changes"},
        "delete_garment": {"garment_id"},
    }

    assert set(tools) == set(expected_fields)
    assert all(
        set(tools[name].args_schema.model_fields) == fields
        for name, fields in expected_fields.items()
    )
    assert len({tools[name].args_schema for name in tools}) == len(tools)
    with pytest.raises(ValidationError):
        tools["get_weather"].args_schema.model_validate(
            {"city": "杭州", "garment_id": "g-1"}
        )


def test_nested_add_schema_prepares_a_valid_pending_action():
    tools = toolkit()
    add = next(tool for tool in tools.tools if tool.name == "add_garment")

    payload = __import__("json").loads(
        add.invoke(
            {
                "metadata": {
                    "name": "蓝色针织衫",
                    "category": "上装",
                    "primary_color": "蓝色",
                    "seasons": ["春", "秋"],
                    "styles": ["休闲"],
                }
            }
        )
    )

    assert payload["pending_action"]["operation"] == "add"
    assert tools.wardrobe.list_garments("owner-a") == [
        tools.wardrobe.get_garment("owner-a", "g-1")
    ]
