from langchain_core.messages import AIMessage

from stylemate.agent.graph import build_agent_graph
from stylemate.agent.routing import route_skills
from stylemate.agent.state import initial_state
from tests.agent.test_graph import toolkit


def test_multi_intent_route_unions_read_skills_without_granting_writes():
    available = {tool.name for tool in toolkit().tools}
    route = route_skills("旅行穿搭和羊毛洗护", available)
    assert {"travel_planning", "outfit_planning", "knowledge_qa"} <= set(route.skills)
    assert {"travel_packing", "care_guide", "recommend_inventory_outfit"} <= route.allowed_tools
    assert not route.allowed_tools & {"add_garment", "update_garment", "delete_garment"}


def test_injected_model_call_cannot_bypass_tool_visibility_or_create_pending_write():
    class Model:
        calls = 0

        def bind_tools(self, tools):
            assert "delete_garment" not in {tool.name for tool in tools}
            return self

        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[{"name": "delete_garment", "args": {"garment_id": "g-1"}, "id": "bad"}])
            return AIMessage(content="已停止越权请求")

    tools = toolkit()
    result = build_agent_graph(Model(), tools.tools).invoke(initial_state("羊毛如何洗护？"))
    assert result["pending_action"] is None
    assert tools.wardrobe.get_garment("owner-a", "g-1") is not None
    assert any(t["summary"] == "skill tool permission denied" for t in result["traces"])


def test_current_turn_write_intent_only_opens_matching_proposal_tool():
    route = route_skills("删除这件白衬衫", {tool.name for tool in toolkit().tools})
    assert "delete_garment" in route.allowed_tools
    assert "add_garment" not in route.allowed_tools
    assert "update_garment" not in route.allowed_tools
