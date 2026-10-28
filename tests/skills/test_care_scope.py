"""Care decisions must not infer a fibre from the clothing category."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from stylemate.agent.tools.styling import care_guide
from stylemate.rag.models import RetrievalHit
from stylemate.skills.knowledge_qa import KnowledgeQASkill, KnowledgeQuery
from tests.agent.test_middleware import tool_context
from tests.agent.test_service import service
from tests.rag.test_applicability import ConstantEmbedding, wool
from tests.skills.test_knowledge_qa import SequenceRetriever, hit


@pytest.mark.parametrize("query", ["毛衣怎么洗", "我的针织衫如何清洗", "冲锋衣清洗方法", "衣物"])
def test_ambiguous_care_collects_material_or_label_before_searching(query):
    context = tool_context()
    retriever = Mock()
    object.__setattr__(context, "retriever", retriever)
    result = care_guide({"material": query}, context)
    assert result["answer_status"] == "needs_clarification"
    assert result["missing_conditions"] == ["material_or_care_label"]
    assert result["results"] == result["sources"] == []
    retriever.search.assert_not_called()


def test_retry_rewrite_cannot_turn_a_sweater_into_wool():
    retriever = SequenceRetriever([[], []])
    result = KnowledgeQASkill(retriever).run("owner", "thread", KnowledgeQuery(query="毛衣如何处理"))
    assert len(retriever.calls) == 2
    assert all("羊毛" not in call[0] for call in retriever.calls)
    assert result.data["results"] == result.data["sources"] == []


def test_final_skill_validation_uses_original_material_even_if_retriever_is_wrong():
    retriever = SequenceRetriever([[hit()], [hit()]])
    result = KnowledgeQASkill(retriever).run("owner", "thread", KnowledgeQuery(query="棉衣可以用柔顺剂吗"))
    assert result.status == "fallback"
    assert result.data["results"] == result.data["sources"] == []


def test_scoped_user_document_remains_searchable_for_unknown_clothing_material():
    uploaded = RetrievalHit(title="上传的洗标", snippet="此件针织衫注明手洗且不可烘干。", source_name="User upload",
                            source_url="user-document://doc-a", topic="care", score=1.0, document_id="doc-a")
    retriever = SequenceRetriever([[uploaded]])
    result = KnowledgeQASkill(retriever).run("owner", "thread", KnowledgeQuery(query="毛衣洗标要求是什么"))
    assert result.data["results"][0]["document_id"] == "doc-a"


@pytest.mark.parametrize("mode", ["bm25", "vector", "hybrid"])
def test_unknown_sweater_cannot_borrow_wool_even_with_identical_vectors(mode):
    from stylemate.rag.retriever import HybridRetriever, create_chroma_client
    from stylemate.repositories.agent_session import SessionAgentRepository

    search = HybridRetriever([wool()], SessionAgentRepository({}), ConstantEmbedding(), create_chroma_client("demo"))
    assert search.search("针织毛衣怎么洗护", "owner", "thread", mode=mode) == []
    assert search.search("羊毛怎么洗护", "owner", "thread", mode=mode)[0].record_id == "wool"


def test_chat_clarifies_then_uses_explicitly_supplied_fibre():
    app = service()
    first = app.chat("owner-a", "thread-a", "我的毛衣怎么洗")
    assert "材质成分或洗护标签" in first.content
    assert first.sources == []
    second = app.chat("owner-a", "thread-a", "羊毛衣物应该怎么洗")
    assert second.sources
    assert "适用范围" in second.content


@pytest.mark.parametrize("mode", ["bm25", "vector", "hybrid"])
def test_unknown_shell_does_not_replace_missing_technical_evidence_with_laundry_tips(mode):
    from stylemate.rag.corpus import load_builtin_records
    from stylemate.rag.retriever import HybridRetriever, create_chroma_client
    from stylemate.repositories.agent_session import SessionAgentRepository

    search = HybridRetriever(load_builtin_records(Path("data/knowledge/records.jsonl")), SessionAgentRepository({}),
                             ConstantEmbedding(), create_chroma_client("demo"))
    assert search.search("冲锋衣拒水效果下降", "owner", "thread", mode=mode) == []
    assert search.search("GORE-TEX 拒水效果下降", "owner", "thread", mode=mode)
