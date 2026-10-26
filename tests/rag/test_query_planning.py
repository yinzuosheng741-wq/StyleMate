from datetime import date

from stylemate.rag.models import KnowledgeRecord
from stylemate.rag.query_planning import lexical_queries
from stylemate.rag.retriever import HybridRetriever, create_chroma_client
from stylemate.repositories.agent_session import SessionAgentRepository


def test_alias_expansion_recovers_english_technical_term_without_vector_service():
    record = KnowledgeRecord(
            review_status="reviewed", source_locator="synthetic test fixture",
            review_note="Synthetic retrieval fixture; not source-verified knowledge.",
            reviewed_at="2026-10-22", reviewer="test-fixture", applicability="test only",id="gore", title="GORE-TEX", content="GORE-TEX garments should follow the original care label before washing.",
                             source_url="https://example.com/care", source_name="Guide",
                             topic="care", retrieved_at=date(2026, 10, 22))
    retriever = HybridRetriever([record], SessionAgentRepository({}), None, create_chroma_client("demo"))
    hits = retriever.search("冲锋衣怎么洗护", "owner", "thread", mode="bm25")
    assert hits and hits[0].record_id == "gore"
    assert lexical_queries("冲锋衣不要用柔顺剂")[0] == "冲锋衣不要用柔顺剂"
    assert all("不要用柔顺剂" in q for q in lexical_queries("冲锋衣不要用柔顺剂"))
