"""Exercise published knowledge through retrieval and the desktop chat path."""

import pytest

from stylemate.agent.routing import WRITE_TOOLS, route_skills
from stylemate.agent.tool_schemas import READ_TOOL_SCHEMAS, WRITE_TOOL_SCHEMAS
from stylemate.rag.corpus import load_builtin_records
from tests.agent.test_service import service


@pytest.mark.parametrize("query, expected", [
    ("邻近色如何搭配", "color-analogous"),
    ("互补色搭配会有什么效果", "color-complementary"),
    ("黑白灰属于什么颜色，如何配色", "color-neutral"),
    ("户外分层内层作用是什么", "layer-base"),
    ("户外分层外层挡雨怎么选", "layer-shell"),
    ("旅行上下装怎么搭配比较省空间", "travel-mix"),
    ("面试衣服要注意什么", "interview-comfort"),
    ("徒步如何防晒", "hiking-sun"),
    ("高温出行衣服怎么选", "heat-activity"),
    ("羊毛衣物洗前需要翻面吗", "wool-reverse"),
    ("旅行如何根据行程带衣服", "travel-activities"),
])
def test_realistic_questions_retrieve_relevant_reviewed_sources(query, expected):
    app = service()
    hits = app.retriever.search(query, "owner-a", "thread-a", top_k=3)
    assert hits and hits[0].record_id == expected
    hit = next(hit for hit in hits if hit.record_id == expected)
    assert hit.review_status == "reviewed"
    assert hit.source_locator and hit.applicability and hit.limitations


@pytest.mark.parametrize("query, phrase", [
    ("邻近色如何搭配", "相邻"),
    ("互补色搭配会有什么效果", "对比"),
    ("户外分层内层作用是什么", "汗水"),
    ("知识库旅行上下装怎么搭配比较省空间", "上衣和下装"),
    ("知识库面试衣服要注意什么", "舒适"),
    ("知识库徒步如何防晒", "UPF"),
])
def test_knowledge_questions_reach_chat_without_model_or_write_capability(query, phrase):
    app = service()
    reply = app.chat("owner-a", "thread-a", query)
    assert phrase in reply.content
    assert reply.sources and reply.traces[0].name == "rag_search"
    route = route_skills(query, set(READ_TOOL_SCHEMAS) | set(WRITE_TOOL_SCHEMAS))
    assert "rag_search" in route.allowed_tools
    assert not route.allowed_tools & WRITE_TOOLS


def test_unconfirmed_sweater_material_does_not_get_specific_wool_care():
    app = service()
    reply = app.chat("owner-a", "thread-a", "毛衣应该怎么洗")
    assert "材质" in reply.content or "标签" in reply.content
    assert "洗前翻到反面" not in reply.content


def test_new_sources_are_not_unreviewed_project_rules():
    from pathlib import Path

    records = {record.id: record for record in load_builtin_records(Path("data/knowledge/records.jsonl"))}
    for record_id in ("color-analogous", "travel-mix", "layer-shell", "heat-clothing", "wool-woven-brush"):
        record = records[record_id]
        assert record.is_published_evidence and record.source_url
        assert record.applicability and record.limitations
