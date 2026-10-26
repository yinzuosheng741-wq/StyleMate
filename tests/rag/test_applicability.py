import pytest

from stylemate.rag.models import KnowledgeRecord
from stylemate.rag.query_planning import knowledge_compatible
from stylemate.rag.retriever import HybridRetriever, create_chroma_client
from stylemate.repositories.agent_session import SessionAgentRepository
from stylemate.skills.knowledge_qa import KnowledgeQASkill, KnowledgeQuery


class ConstantEmbedding:
    def embed_documents(self, texts):
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, _text):
        return [1.0, 0.0]


def wool():
    return KnowledgeRecord(
        id="wool", title="羊毛洗护知识", content="羊毛衣物的洗护应依据具体洗标进行，羊毛衫洗后通常需平放干燥，受具体产品制造商说明限制。",
        source_url="https://example.test/wool", source_name="Fixture", topic="care", retrieved_at="2026-10-26",
        review_status="reviewed", source_locator="Fixture", reviewer="synthetic-test", reviewed_at="2026-10-26",
        review_note="Synthetic retrieval boundary fixture", applicability="羊毛衣物",
    )


@pytest.mark.parametrize("mode", ["bm25", "vector", "hybrid"])
def test_explicit_cotton_question_cannot_receive_wool_even_with_perfect_vector_score(mode):
    retriever = HybridRetriever([wool()], SessionAgentRepository({}), ConstantEmbedding(), create_chroma_client("demo"))
    assert retriever.search("棉衣洗护", "owner", "thread", mode=mode) == []
    assert retriever.last_audit["applicability_filtered"] == 1
    assert retriever.search("羊毛怎么洗护", "owner", "thread", mode=mode)[0].record_id == "wool"


@pytest.mark.parametrize("query", ["皮革怎么洗护", "亚麻怎么洗护", "涤纶如何护理", "请查品牌尺码表", "如何使用色轮配色"])
def test_missing_topic_or_material_does_not_borrow_unrelated_reviewed_care(query):
    assert not knowledge_compatible(query, title=wool().title, content=wool().content, topic="care")


def test_material_comparison_can_retrieve_each_subject_without_requiring_both_in_one_record():
    assert knowledge_compatible("羊毛和棉的护理区别", title=wool().title, content=wool().content, topic="care")


@pytest.mark.parametrize("query", ["羊毛洗后尺寸变化怎么办", "配色羊毛衫如何洗护"])
def test_care_context_is_not_misrouted_by_size_or_color_words(query):
    assert knowledge_compatible(query, title=wool().title, content=wool().content, topic="care")


def test_rewrite_cannot_bypass_original_color_topic_boundary_with_added_care_words():
    retriever = HybridRetriever([wool()], SessionAgentRepository({}), ConstantEmbedding(), create_chroma_client("demo"))
    outcome = KnowledgeQASkill(retriever).run("owner", "thread", KnowledgeQuery(query="色轮配色怎么搭配"))
    assert outcome.data["attempts"] == 2
    assert outcome.data["results"] == []
    assert outcome.data["sources"] == []
    assert "洗护" not in outcome.data["effective_query"]
