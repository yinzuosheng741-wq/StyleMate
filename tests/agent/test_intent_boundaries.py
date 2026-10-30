import json

import pytest
from langchain_core.messages import AIMessage

from stylemate.agent.graph import build_agent_graph
from stylemate.agent.routing import WRITE_TOOLS, explicit_write_tools, route_skills
from stylemate.agent.service import _outfit_arguments
from stylemate.agent.state import initial_state
from stylemate.demo.sample_data import sample_garments
from tests.agent.test_graph import toolkit
from tests.agent.test_service import service


@pytest.mark.parametrize("text", [
    "不要删除这件衣服", "请别删除编号g-1", "我不想删除白衬衫", "暂不修改颜色",
    "如果删除了还能恢复吗", "如何删除衣物", "删除按钮在哪里", "删除后会怎么样",
    "能不能添加一件衣服？", "解释删除功能", "示例：删除白衬衫", "他说“删除这件衣服”",
    'Explain "delete this garment"', "do not delete garment g-1", "how do I delete a garment?",
    "如果删除失败，删除记录会恢复吗", "帮我看看删除功能", "我已经删除了衣服",
    "如果找到重复项，请删除衣物编号g-1", "删除后衣物就没了", "删除了这件衣服",
    "不要把白衬衫名称改为外套", "如何重命名衣物？", "如果把名称改为外套会怎样？",
    "他说“把白衬衫名称改为外套”", "我已经重命名了衣服", "改名功能在哪里",
    "重命名了这件衣服", "把白衬衫名称改为了通勤衬衫",
])
def test_non_action_messages_cannot_open_write_proposal_tools(text):
    route = route_skills(text, {tool.name for tool in toolkit().tools})
    assert not route.allowed_tools & WRITE_TOOLS


@pytest.mark.parametrize("text,expected", [
    ("请帮我删除衣物编号g-1", {"delete_garment"}),
    ("把白衬衫从衣橱移除", {"delete_garment"}),
    ("将白衬衫颜色改成米色", {"update_garment"}),
    ("请把编号 g-1 的衣服名称改为“出行衬衫”，等我确认后再改。", {"update_garment"}),
    ("帮我将白衬衫改名为通勤衬衫", {"update_garment"}),
    ("重命名编号 g-1 为通勤衬衫", {"update_garment"}),
    ("新增一件白色上衣", {"add_garment"}),
    ("Please delete garment g-1", {"delete_garment"}),
    ("不要删除白衬衫，但请更新裤子的颜色", {"update_garment"}),
])
def test_clear_requests_only_open_corresponding_preview(text, expected):
    assert explicit_write_tools(text) == expected


def test_negation_cannot_be_overridden_by_model_tool_call():
    tools = toolkit()

    class Model:
        calls = 0

        def bind_tools(self, visible):
            assert not {t.name for t in visible} & WRITE_TOOLS
            return self

        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[{
                    "name": "delete_garment", "args": {"garment_id": "g-1"}, "id": "denied"
                }])
            return AIMessage(content="已保留这件衣服。")

    result = build_agent_graph(Model(), tools.tools).invoke(initial_state("不要删除白衬衫"))
    assert result["pending_action"] is None
    assert tools.wardrobe.get_garment("owner-a", "g-1") is not None
    assert any(t["summary"] == "skill tool permission denied" for t in result["traces"])


def test_no_key_denied_or_failed_write_does_not_claim_preview_exists():
    app = service()
    denied = app.chat("owner-a", "thread-a", "不要删除衣物编号g-1")
    missing = app.chat("owner-a", "thread-a", "删除衣物编号missing")
    assert "已生成衣橱变更预览" not in denied.content
    assert "已生成衣橱变更预览" not in missing.content
    assert app.repository.get_pending("owner-a", "thread-a") is None


def test_invalid_candidate_ids_do_not_expand_to_all_owned_garments():
    tools = toolkit()
    for garment in sample_garments():
        tools.wardrobe.save_garment("owner-a", garment)
    tool = next(t for t in tools.tools if t.name == "recommend_inventory_outfit")
    normal = json.loads(tool.invoke({"scene": "通勤"}))["result"]
    invalid = json.loads(tool.invoke({"scene": "通勤", "candidate_garment_ids": ["foreign-or-deleted"]}))["result"]
    assert normal["recommendations"]
    assert invalid["recommendations"] == []
    assert "未扩大" in invalid["message"]


def test_chat_extracts_temporary_color_exclusion_without_creating_profile_preference():
    app = service()
    assert _outfit_arguments("今天通勤搭配，不穿黑色和红色")["extra_constraints"] == ["不穿黑色", "不穿红色"]
    app.chat("owner-a", "thread-a", "今天通勤搭配，不穿黑色")
    assert "color_preference" not in app.profile_service.get("owner-a")
