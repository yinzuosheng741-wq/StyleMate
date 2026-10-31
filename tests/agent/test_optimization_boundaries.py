"""Regressions from measured failures, including unseen phrasing variants."""

import pytest
from langchain_core.messages import AIMessage

from stylemate.agent.graph import build_agent_graph
from stylemate.agent.routing import route_skills
from stylemate.agent.state import initial_state
from stylemate.demo.sample_data import sample_garments
from tests.agent.test_service import service


@pytest.mark.parametrize("question", ["用我已有的衣服搭一套上班穿的", "帮我搭一身周末穿的", "配一套通勤装"])
def test_common_outfit_phrasing_reaches_inventory_without_model(question):
    app = service()
    for item in sample_garments():
        app.wardrobe_repository.save_garment("owner", item)
    reply = app.chat("owner", "thread", question)
    assert reply.outfits
    assert "recommend_inventory_outfit" in [t.name for t in reply.traces]


@pytest.mark.parametrize("question", ["不要删除衣物 ID: sample-shirt-white", "先别移除衣物", "删除衣物会怎样？"])
def test_negated_or_explanatory_delete_does_not_attempt_a_write(question):
    reply = service().chat("owner", "thread", question)
    assert reply.traces == []
    assert "不会删除" in reply.content


def test_unknown_material_graph_cannot_invent_wool_or_invoke_model():
    class MustNotCall:
        def bind_tools(self, _tools):
            raise AssertionError("material clarification must precede the model")

    app = service()
    graph = build_agent_graph(MustNotCall(), app._toolkit("owner", "thread").tools)
    result = graph.invoke(initial_state("针织外套可以机洗吗", owner_id="owner", conversation_id="thread"))
    assert "材质" in result["messages"][-1].content
    assert not result.get("sources")
    assert result.get("model_calls", 0) == 0
    assert [t["name"] for t in result["traces"] if t["name"] != "skill_router"] == ["care_guide"]


def test_explicit_material_still_reaches_model_graph():
    class Model:
        called = False

        def bind_tools(self, _tools):
            return self

        def invoke(self, _messages):
            self.called = True
            return AIMessage(content="请以这件羊毛衣物的洗标为准。")

    model = Model()
    graph = build_agent_graph(model, service()._toolkit("owner", "thread").tools)
    graph.invoke(initial_state("羊毛外套能机洗吗"))
    assert model.called


def test_color_only_question_does_not_expose_care_but_mixed_care_does():
    available = {"rag_search", "care_guide", "get_garment"}
    assert "care_guide" not in route_skills("请讲讲互补色配色", available).allowed_tools
    assert "care_guide" in route_skills("配色羊毛衫怎么洗护", available).allowed_tools
