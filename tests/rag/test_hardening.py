from datetime import date, datetime
from time import sleep

import pytest
from pydantic import ValidationError

from stylemate.domain.models import UserDocument
from stylemate.rag.models import KnowledgeRecord
from stylemate.rag.retriever import (
    DashScopeEmbeddingAdapter,
    EmbeddingUnavailableError,
    HybridRetriever,
    OpenAICompatibleEmbeddingAdapter,
    create_chroma_client,
)
from stylemate.repositories.agent_session import SessionAgentRepository


class ConstantEmbedding:
    def embed_documents(self, texts):
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text):
        return [1.0, 0.0]


class ConnectionFailingEmbedding(ConstantEmbedding):
    def embed_query(self, text):
        raise ConnectionError("private API key must not appear")


class SlowEmbedding(ConstantEmbedding):
    def embed_query(self, text):
        sleep(0.05)
        return [1.0, 0.0]


def _record():
    return KnowledgeRecord(
            review_status="reviewed", source_locator="synthetic test fixture",
            review_note="Synthetic retrieval fixture; not source-verified knowledge.",
            reviewed_at="2026-10-22", reviewer="test-fixture", applicability="test only",
        id="fallback-care",
        title="Fallback care note",
        content="wool care should follow the garment label before any wash cycle begins",
        source_url="https://www.woolmark.com/care/care-for-wool/",
        source_name="Woolmark",
        topic="care",
        retrieved_at=date(2026, 8, 13),
    )


def _document(conversation_id, document_id, filename, text):
    return UserDocument(
        owner_id="same-owner",
        conversation_id=conversation_id,
        document_id=document_id,
        filename=filename,
        mime_type="text/markdown",
        text=text,
        created_at=datetime(2026, 8, 13),
    )


def test_knowledge_record_keeps_the_formal_minimum_content_length():
    with pytest.raises(ValidationError):
        KnowledgeRecord(
            review_status="reviewed", source_locator="synthetic test fixture",
            review_note="Synthetic retrieval fixture; not source-verified knowledge.",
            reviewed_at="2026-10-22", reviewer="test-fixture", applicability="test only",
            id="short", title="Short title", content="short",
            source_url="https://www.woolmark.com/care/care-for-wool/",
            source_name="Woolmark", topic="care", retrieved_at=date(2026, 8, 13),
        )


def test_owner_semantic_collection_keeps_same_document_ids_separate_by_conversation():
    repository = SessionAgentRepository({})
    repository.save_document(_document("thread-a", "shared", "A note", "alpha private wardrobe note"))
    repository.save_document(_document("thread-b", "shared", "B note", "beta private wardrobe note"))
    retriever = HybridRetriever([], repository, ConstantEmbedding(), create_chroma_client("demo"))

    hits_a = retriever.search("note", "same-owner", "thread-a", top_k=3)
    hits_b = retriever.search("note", "same-owner", "thread-b", top_k=3)

    assert [hit.source_name for hit in hits_a] == ["A note"]
    assert [hit.source_name for hit in hits_b] == ["B note"]


def test_user_collection_removes_stale_vectors_for_the_current_conversation():
    repository = SessionAgentRepository({})
    repository.save_document(_document("thread-a", "old", "Old note", "stale wardrobe note"))
    retriever = HybridRetriever([], repository, ConstantEmbedding(), create_chroma_client("demo"))
    assert retriever.search("note", "same-owner", "thread-a", top_k=3)
    repository.state["stylemate_agent"]["same-owner"]["documents"]["thread-a"] = {}

    assert retriever.search("note", "same-owner", "thread-a", top_k=3) == []


@pytest.mark.parametrize("embedding", [ConnectionFailingEmbedding(), SlowEmbedding()])
def test_semantic_sdk_errors_and_timeouts_fall_back_without_exposing_details(embedding):
    retriever = HybridRetriever([_record()], SessionAgentRepository({}), embedding, create_chroma_client("demo"), embedding_timeout_seconds=0.001)

    hits = retriever.search("wool", "owner-a", "thread-a", top_k=1)

    assert hits[0].source_name == "Woolmark"


def test_dashscope_adapter_wraps_bad_responses_and_passes_configured_timeout(monkeypatch):
    calls = []

    class BadResponse:
        status_code = 503
        output = {}

    def fake_call(**kwargs):
        calls.append(kwargs)
        return BadResponse()

    import dashscope

    monkeypatch.setattr(dashscope.TextEmbedding, "call", fake_call)
    adapter = DashScopeEmbeddingAdapter(request_timeout_seconds=2.5)
    with pytest.raises(EmbeddingUnavailableError, match="embedding service unavailable"):
        adapter.embed_documents(["one"])

    assert calls[0]["timeout"] == 2.5


def test_embedding_namespace_separates_providers_with_the_same_model_name():
    from stylemate.rag.retriever import embedding_namespace

    first = OpenAICompatibleEmbeddingAdapter("key", "https://one.example/v1", "shared-name")
    second = OpenAICompatibleEmbeddingAdapter("key", "https://two.example/v1", "shared-name")
    assert embedding_namespace(first) != embedding_namespace(second)


def test_dashscope_embedding_uses_the_explicit_key_and_model(monkeypatch):
    import dashscope

    calls = []
    class Response:
        status_code = 200
        output = {"embeddings": [{"embedding": [1.0, 0.0]}]}

    monkeypatch.setattr(dashscope.TextEmbedding, "call", lambda **kwargs: calls.append(kwargs) or Response())
    adapter = DashScopeEmbeddingAdapter(api_key="test-embedding-key", model_name="test-embedding-model")
    assert adapter.embed_query("example") == [1.0, 0.0]
    assert calls[0]["api_key"] == "test-embedding-key"
    assert calls[0]["model"] == "test-embedding-model"


def test_failed_builtin_embedding_sync_can_be_retried():
    class RecoveringEmbedding:
        model = "test-recovery"
        attempts = 0

        def embed_documents(self, texts):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("temporary failure")
            return [[1.0, 0.0] for _ in texts]

        def embed_query(self, _text):
            return [1.0, 0.0]

    embedding = RecoveringEmbedding()
    retriever = HybridRetriever([_record()], SessionAgentRepository({}), embedding, create_chroma_client("demo"))
    assert not retriever._builtin_sync_result
    assert retriever.sync_builtin_index()
    assert embedding.attempts == 2


def test_dashscope_adapter_wraps_vector_count_mismatch(monkeypatch):
    class BadResponse:
        status_code = 200
        output = {"embeddings": [{"embedding": [1.0, 0.0]}]}

    import dashscope

    monkeypatch.setattr(dashscope.TextEmbedding, "call", lambda **kwargs: BadResponse())
    with pytest.raises(EmbeddingUnavailableError, match="embedding service unavailable"):
        DashScopeEmbeddingAdapter().embed_documents(["one", "two"])


def test_openai_compatible_embedding_adapter_preserves_input_order():
    calls = []

    class Embeddings:
        def create(self, **kwargs):
            calls.append(kwargs)
            item_one = type("Item", (), {"index": 1, "embedding": [0.0, 1.0]})()
            item_zero = type("Item", (), {"index": 0, "embedding": [1.0, 0.0]})()
            return type("Response", (), {"data": [item_one, item_zero]})()

    client = type("Client", (), {"embeddings": Embeddings()})()
    adapter = OpenAICompatibleEmbeddingAdapter(
        "test-key",
        "https://embedding.example/v1",
        "embedding-model",
        request_timeout_seconds=2.5,
        client=client,
    )

    vectors = adapter.embed_documents(["first", "second"])

    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert calls[0]["timeout"] == 2.5
