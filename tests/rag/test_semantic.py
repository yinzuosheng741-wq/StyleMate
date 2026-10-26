from datetime import date

from stylemate.rag.models import KnowledgeRecord
from stylemate.rag.retriever import (
    HybridRetriever,
    builtin_collection_name,
    create_chroma_client,
    owner_collection_name,
)
from stylemate.repositories.agent_session import SessionAgentRepository


class FakeEmbedding:
    def embed_documents(self, texts):
        return [[1.0, 0.0] if "wool" in text.lower() else [0.0, 1.0] for text in texts]

    def embed_query(self, text):
        return [1.0, 0.0] if "wool" in text.lower() else [0.0, 1.0]


class OpposingEmbedding:
    def embed_documents(self, texts):
        return [[0.0, 1.0] if "羊毛" in text else [1.0, 0.0] for text in texts]

    def embed_query(self, text):
        return [1.0, 0.0]


def test_semantic_branch_uses_selected_vector_backend_builtin_collection():
    records = [
        KnowledgeRecord(
            review_status="reviewed", source_locator="synthetic test fixture",
            review_note="Synthetic retrieval fixture; not source-verified knowledge.",
            reviewed_at="2026-10-22", reviewer="test-fixture", applicability="test only",
            id="semantic-wool",
            title="Wool care note",
            content="wool garments should follow the garment care label before washing",
            source_url="https://www.woolmark.com/care/care-for-wool/",
            source_name="Woolmark",
            topic="care",
            retrieved_at=date(2026, 8, 13),
        )
    ]
    client = create_chroma_client("demo")
    retriever = HybridRetriever(records, SessionAgentRepository({}), FakeEmbedding(), client)

    hits = retriever.search("wool cleaning", "private-owner", "thread-a", top_k=1)

    assert hits[0].source_name == "Woolmark"
    assert (
        client.get_collection(
            builtin_collection_name(retriever.embedding_namespace)
        ).count()
        == 1
    )
    assert owner_collection_name(
        "private-owner", retriever.embedding_namespace
    ) in [item.name for item in client.list_collections()]


def test_search_fuses_bm25_and_vector_rankings_instead_of_using_semantic_only():
    records = [
        KnowledgeRecord(
            review_status="reviewed", source_locator="synthetic test fixture",
            review_note="Synthetic retrieval fixture; not source-verified knowledge.",
            reviewed_at="2026-10-22", reviewer="test-fixture", applicability="test only",
            id="lexical-wool",
            title="羊毛洗护指南",
            content="羊毛大衣清洗前应查看洗标，使用低温轻柔程序，避免高温烘干并采用平铺方式自然晾干。",
            source_url="https://example.com/wool",
            source_name="Care Guide",
            topic="care",
            retrieved_at=date(2026, 8, 13),
        ),
        KnowledgeRecord(
            review_status="reviewed", source_locator="synthetic test fixture",
            review_note="Synthetic retrieval fixture; not source-verified knowledge.",
            reviewed_at="2026-10-22", reviewer="test-fixture", applicability="test only",
            id="semantic-distractor",
            title="Unrelated semantic note",
            content="This document is deliberately unrelated to garment cleaning but is closest in vector space for the test.",
            source_url="https://example.com/unrelated",
            source_name="Unrelated",
            topic="style",
            retrieved_at=date(2026, 8, 13),
        ),
    ]
    retriever = HybridRetriever(
        records, SessionAgentRepository({}), OpposingEmbedding(), create_chroma_client("demo")
    )

    hits = retriever.search("羊毛大衣怎么清洗", "owner-a", "thread-a", top_k=1)

    assert hits[0].source_name == "Care Guide"
