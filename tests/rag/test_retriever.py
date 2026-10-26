from datetime import date, datetime

from stylemate.domain.models import UserDocument
from stylemate.rag.models import KnowledgeRecord
from stylemate.rag.retriever import HybridRetriever, create_chroma_client, owner_collection_name, reciprocal_rank_fusion
from stylemate.repositories.agent_session import SessionAgentRepository


class CountingEmbedding:
    def __init__(self):
        self.document_calls = 0
        self.query_calls = 0

    def embed_documents(self, texts):
        self.document_calls += 1
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text):
        self.query_calls += 1
        return [1.0, 0.0]


def test_bm25_fallback_returns_cited_source_without_embedding_key():
    records = [
        KnowledgeRecord(
            review_status="reviewed", source_locator="synthetic test fixture",
            review_note="Synthetic retrieval fixture; not source-verified knowledge.",
            reviewed_at="2026-10-22", reviewer="test-fixture", applicability="test only",
            id="wool-care",
            title="羊毛基础洗护",
            content="羊毛衣物应先读取洗标，使用适合羊毛的温和程序并避免高温、强力脱水和长时间烘干，必要时交由专业护理。",
            source_url="https://www.woolmark.com/care/care-for-wool/",
            source_name="Woolmark",
            topic="care",
            retrieved_at=date(2026, 8, 13),
        )
    ]
    retriever = HybridRetriever(
        records=records,
        repository=SessionAgentRepository({}),
        embedding=None,
        chroma_client=create_chroma_client("demo"),
    )

    hits = retriever.search("羊毛大衣怎么洗", "owner-a", "thread-a", top_k=3)

    assert hits[0].source_name == "Woolmark"
    assert str(hits[0].source_url).startswith("https://")


def test_keyword_fallback_keeps_user_documents_owner_and_conversation_scoped():
    repository = SessionAgentRepository({})
    repository.save_document(
        UserDocument(
            owner_id="owner-a",
            conversation_id="thread-a",
            document_id="doc-a",
            filename="我的羊毛清单.md",
            mime_type="text/markdown",
            text="我的羊毛大衣只能低温轻柔洗涤，并且需要平铺晾干。",
            created_at=datetime(2026, 8, 13),
        )
    )
    repository.save_document(
        UserDocument(
            owner_id="owner-b",
            conversation_id="thread-a",
            document_id="doc-b",
            filename="别人的笔记.md",
            mime_type="text/markdown",
            text="别人的私密衣物说明。",
            created_at=datetime(2026, 8, 13),
        )
    )
    retriever = HybridRetriever([], repository, embedding=None, chroma_client=create_chroma_client("demo"))

    hits = retriever.search("羊毛大衣洗涤", "owner-a", "thread-a", top_k=3)

    assert [hit.source_url for hit in hits] == ["user-document://doc-a"]
    assert hits[0].source_name == "我的羊毛清单.md"


def test_owner_collection_name_does_not_expose_raw_owner_id():
    name = owner_collection_name("alice@example.com")

    assert name.startswith("user_")
    assert name != "user_alice@example.com"
    assert "alice" not in name


def test_reciprocal_rank_fusion_rewards_results_found_by_both_retrievers():
    scores = reciprocal_rank_fusion([["lexical", "shared"], ["shared", "semantic"]])

    assert scores["shared"] > scores["lexical"]
    assert scores["shared"] > scores["semantic"]


def test_document_embeddings_are_reused_across_queries():
    embedding = CountingEmbedding()
    records = [
        KnowledgeRecord(
            review_status="reviewed", source_locator="synthetic test fixture",
            review_note="Synthetic retrieval fixture; not source-verified knowledge.",
            reviewed_at="2026-10-22", reviewer="test-fixture", applicability="test only",
            id="indexed-once",
            title="Indexed care guide",
            content="GORE-TEX outerwear should avoid fabric softener during washing.",
            source_url="https://example.com/care",
            source_name="Care Guide",
            topic="care",
            retrieved_at=date(2026, 8, 17),
        )
    ]
    retriever = HybridRetriever(
        records,
        SessionAgentRepository({}),
        embedding,
        create_chroma_client("demo"),
    )

    retriever.search("fabric softener", "owner-a", "thread-a")
    retriever.search("outerwear washing", "owner-a", "thread-a")

    assert embedding.document_calls == 1
    assert embedding.query_calls == 2
    assert retriever.stats() == {
        "builtin_sync_requests": 1,
        "builtin_sync_successes": 1,
        "document_embedding_requests": 1,
        "document_texts_submitted": 1,
        "query_embedding_requests": 2,
        "search_mode_hybrid": 2,
        "search_requests": 2,
    }
    assert not {
        "query",
        "vector",
        "api_key",
        "credential",
    }.intersection(retriever.stats())


def test_user_document_vectors_update_only_when_documents_change():
    repository = SessionAgentRepository({})
    embedding = CountingEmbedding()
    client = create_chroma_client("demo")
    retriever = HybridRetriever([], repository, embedding, client)
    document = UserDocument(
        owner_id="owner-a",
        conversation_id="thread-a",
        document_id="guide",
        filename="care.md",
        mime_type="text/markdown",
        text="# 功能外套\n\n清洗时避免使用柔顺剂。",
        created_at=datetime(2026, 8, 17),
    )
    repository.save_document(document)

    assert retriever.sync_user_documents(
        "owner-a", "thread-a", [document]
    )
    assert retriever.sync_user_documents(
        "owner-a", "thread-a", [document]
    )
    retriever.search("柔顺剂", "owner-a", "thread-a")

    collection = client.get_collection(
        owner_collection_name("owner-a", retriever.embedding_namespace)
    )
    assert collection.count() == 1
    assert embedding.document_calls == 1
    assert embedding.query_calls == 1

    repository.delete_document("owner-a", "thread-a", "guide")
    retriever.sync_user_documents("owner-a", "thread-a", [])

    assert collection.count() == 0


def test_user_document_chunks_return_page_metadata_and_deduplicate_one_document():
    repository = SessionAgentRepository({})
    repository.save_document(
        UserDocument(
            owner_id="owner-a",
            conversation_id="thread-a",
            document_id="guide",
            filename="面料指南.pdf",
            mime_type="application/pdf",
            text="第一页是普通介绍。\n第二页说明羊毛需要低温洗涤并平铺晾干。",
            pages=["第一页是普通介绍。", "第二页说明羊毛需要低温洗涤并平铺晾干。"],
            created_at=datetime(2026, 8, 17),
        )
    )
    retriever = HybridRetriever(
        [], repository, embedding=None, chroma_client=create_chroma_client("demo")
    )

    hits = retriever.search("羊毛低温平铺", "owner-a", "thread-a", top_k=4)

    assert len(hits) == 1
    assert hits[0].document_id == "guide"
    assert hits[0].page_number == 2
    assert "第 2 页" in hits[0].title
