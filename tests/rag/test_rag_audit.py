import json
from datetime import date
from pathlib import Path

import pytest

from evaluation.rag_audit import document_audit
from stylemate.agent.service import AgentService
from stylemate.rag.models import KnowledgeRecord
from stylemate.rag.portable_vectors import PortableVectorClient
from stylemate.rag.retriever import HybridRetriever, _snippet, create_chroma_client
from stylemate.repositories.agent_session import SessionAgentRepository


def test_frozen_long_document_spans_survive_all_retrieval_stages():
    dataset = json.loads(Path("evaluation/rag_audit_cases.json").read_text(encoding="utf-8"))
    report = document_audit(dataset["documents"])
    for row in report["rows"]:
        assert row["chunk_span_coverage"] == 1, row["id"]
        assert row["retrieval_span_coverage"] == 1, row["id"]
        assert row["skill_context_span_coverage"] == 1, row["id"]
        assert row["isolated_from_other_owner"] and row["isolated_from_other_conversation"]
        assert set(row["expected_section_titles"]) <= set(row["actual_section_titles"])


def test_scoped_semantic_top_k_does_not_lose_relevant_item_to_filtered_distractors():
    def record(index, material):
        return KnowledgeRecord(id=f"item-{index}", title=f"{material}衣物资料",
                               content=f"{material}衣物需要遵循整件成衣的洗护标签，具体处理方式须按照制造商说明，不应仅凭材质作出判断。",
                               source_name="Synthetic", source_url="https://example.test/care", topic="care",
                               retrieved_at=date(2026, 10, 31), review_status="reviewed",
                               source_locator="fixture", review_note="Synthetic ranking fixture, not published source evidence.",
                               reviewed_at=date(2026, 10, 31), reviewer="test", applicability="test only")

    class DistractingEmbedding:
        def embed_documents(self, texts):
            return [[0, 1] if "羊毛" in text else [1, 0] for text in texts]

        def embed_query(self, text):
            return [1, 0]

    records = [record(0, "羊毛"), *(record(i, "棉") for i in range(1, 25))]
    retriever = HybridRetriever(records, SessionAgentRepository({}), DistractingEmbedding(), create_chroma_client("demo"))
    hits = retriever.search("羊毛衣物", "owner", "thread", mode="vector", top_k=1)
    assert [hit.record_id for hit in hits] == ["item-0"]
    assert retriever.last_audit["applicability_filtered"] == 24
    assert retriever.last_audit["vector_candidates"] == 1


def test_vector_allowlist_and_conversation_filter_apply_before_ranking():
    collection = PortableVectorClient().get_or_create_collection("test")
    collection.upsert(ids=["a", "b", "c"], documents=["a", "b", "c"],
                      embeddings=[[1, 0], [0, 1], [1, 0]], metadatas=[
                          {"conversation_id": "mine", "retrieval_key": "allowed"},
                          {"conversation_id": "mine", "retrieval_key": "blocked"},
                          {"conversation_id": "other", "retrieval_key": "allowed"},
                      ])
    result = collection.query(query_embeddings=[[0, 1]], n_results=1, where={"$and": [
        {"conversation_id": "mine"}, {"retrieval_key": {"$in": ["allowed"]}},
    ]})
    assert result["ids"] == [["a"]]
    with pytest.raises(ValueError, match="unsupported_vector_filter"):
        collection.query(query_embeddings=[[1, 0]], n_results=1, where={"$or": []})


def test_excerpt_keeps_short_atomic_evidence_and_bounds_long_context():
    short = "遵循成衣洗标，不能仅凭衣物类别判断可否机洗。"
    assert _snippet(short, "请问可以机洗吗") == short
    long = "背景介绍。" * 80 + "关键扣件必须用软布擦拭，禁止浸泡。"
    excerpt = _snippet(long, "关键扣件怎么处理")
    assert "关键扣件必须用软布擦拭" in excerpt
    assert len(excerpt) <= 366


def test_two_displayed_passages_keep_both_locations_and_one_document_source():
    payload = {"result": {"results": [
        {"document_id": "same", "title": "指南（第 1 页）", "snippet": "甲型软布", "source_url": "user-document://same"},
        {"document_id": "same", "title": "指南（第 2 页）", "snippet": "乙型软袋", "source_url": "user-document://same"},
        {"document_id": "other", "title": "无关指南", "snippet": "不应展示", "source_url": "user-document://other"},
    ]}, "sources": [{"title": "指南", "url": "user-document://same"},
                     {"title": "指南", "url": "user-document://same"},
                     {"title": "其他", "url": "user-document://other"}]}
    answer, _, sources = AgentService._present_named("rag_search", payload)
    assert "甲型软布" in answer and "乙型软袋" in answer
    assert "第 1 页" in answer and "第 2 页" in answer
    assert "不应展示" not in answer
    assert [source.url for source in sources] == ["user-document://same"]


@pytest.mark.parametrize("category", ["夹克", "衬衫", "外套", "大衣", "jacket", "shirt"])
def test_unspecified_category_does_not_acquire_goretex_or_wool_care(category):
    from stylemate.rag.query_planning import care_clarification, knowledge_compatible

    query = f"这种{category}应该怎么清洗"
    assert care_clarification(query)
    assert not knowledge_compatible(query, title="GORE-TEX", content="GORE-TEX 外套应遵循专门洗护说明。", topic="care")


def test_exact_product_measurement_cannot_use_generic_concepts_as_actual_dimensions():
    from stylemate.rag.corpus import load_builtin_records
    from stylemate.skills.knowledge_qa import KnowledgeQASkill, KnowledgeQuery

    retriever = HybridRetriever(load_builtin_records(Path("data/knowledge/records.jsonl")),
                                SessionAgentRepository({}), None, create_chroma_client("demo"))
    outcome = KnowledgeQASkill(retriever).run("owner", "thread", KnowledgeQuery(query="星云品牌X99款M码胸围多少厘米"))
    assert outcome.data["answer_status"] == "needs_clarification"
    assert outcome.data["missing_conditions"] == ["product_size_chart"]
    assert outcome.data["results"] == [] and outcome.data["sources"] == []
