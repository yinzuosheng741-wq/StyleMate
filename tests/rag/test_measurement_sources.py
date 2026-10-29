"""Verified measurement facts must reach both retrieval and the public chat route."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from stylemate.agent.routing import WRITE_TOOLS, route_skills
from stylemate.agent.tool_schemas import READ_TOOL_SCHEMAS, WRITE_TOOL_SCHEMAS
from stylemate.rag.corpus import load_builtin_records
from tests.agent.test_service import service


@pytest.mark.parametrize("query,expected", [
    ("衬里装饰部件是否也需要考虑整件衣物洗护标签", "care-label-complete"),
    ("UNIQLO 成衣尺寸平铺测量前需要抚平褶皱吗", "size-measure-same-garment"),
    ("UNIQLO 商品尺寸和人体尺寸有什么区别", "size-body-versus-product"),
    ("UNIQLO 平铺胸宽是半胸宽还是人体胸围", "size-flat-body-width"),
])
def test_compared_source_section_is_top_retrieval_result(query, expected):
    app = service()
    hits = app.retriever.search(query, "owner-a", "thread-a", top_k=3)
    assert hits[0].record_id == expected
    assert hits[0].review_status == "reviewed"
    assert hits[0].source_locator and hits[0].applicability and hits[0].limitations


@pytest.mark.parametrize("query,phrase", [
    ("UNIQLO 商品尺寸和人体尺寸有什么区别", "不穿衣物"),
    ("UNIQLO 平铺胸宽是半胸宽还是人体胸围", "左右侧缝"),
    ("UNIQLO 成衣尺寸平铺测量前需要抚平褶皱吗", "抚平褶皱"),
])
def test_measurement_fact_chat_uses_sources_without_model_or_write_capabilities(query, phrase):
    app = service()
    app.model = Mock(bind_tools=Mock(side_effect=AssertionError("must not call paid model")))
    reply = app.chat("owner-a", "thread-a", query)
    assert phrase in reply.content
    assert "UNIQLO" in reply.content and "限制" in reply.content
    assert reply.sources
    assert reply.traces[0].name == "rag_search"
    app.model.bind_tools.assert_not_called()
    route = route_skills(query, set(READ_TOOL_SCHEMAS) | set(WRITE_TOOL_SCHEMAS))
    assert "rag_search" in route.allowed_tools
    assert not route.allowed_tools & WRITE_TOOLS


def test_new_source_facts_keep_their_brand_scope_and_do_not_publish_pending_cotton_claims():
    records = {r.id: r for r in load_builtin_records(Path("data/knowledge/records.jsonl"))}
    for key in ("size-measure-same-garment", "size-body-versus-product", "size-flat-body-width"):
        assert "UNIQLO" in records[key].applicability
        assert "品牌" in records[key].limitations
    assert not records["fabric-cotton-shrink-risk"].is_published_evidence
