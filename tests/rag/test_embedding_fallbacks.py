from datetime import date

import pytest

from stylemate.rag.models import KnowledgeRecord
from stylemate.rag.retriever import DashScopeEmbeddingAdapter, HybridRetriever, create_chroma_client
from stylemate.repositories.agent_session import SessionAgentRepository


def _fallback_record():
    return KnowledgeRecord(
            review_status="reviewed", source_locator="synthetic test fixture",
            review_note="Synthetic retrieval fixture; not source-verified knowledge.",
            reviewed_at="2026-10-22", reviewer="test-fixture", applicability="test only",
        id="sdk-fallback",
        title="SDK fallback note",
        content="wool care should follow the garment label before choosing any cleaning cycle",
        source_url="https://www.woolmark.com/care/care-for-wool/",
        source_name="Woolmark",
        topic="care",
        retrieved_at=date(2026, 8, 13),
    )


@pytest.mark.parametrize("failure", ["connection", "status", "vectors"])
def test_dashscope_failures_fall_back_to_keyword_hits(monkeypatch, failure):
    import dashscope

    class Response:
        status_code = 503 if failure == "status" else 200
        output = {"embeddings": []}

    def fake_call(**kwargs):
        if failure == "connection":
            raise ConnectionError("secret endpoint failure")
        return Response()

    monkeypatch.setattr(dashscope.TextEmbedding, "call", fake_call)
    retriever = HybridRetriever(
        [_fallback_record()],
        SessionAgentRepository({}),
        DashScopeEmbeddingAdapter(request_timeout_seconds=0.01),
        create_chroma_client("demo"),
    )

    hits = retriever.search("wool", "owner-a", "thread-a", top_k=1)

    assert hits[0].source_name == "Woolmark"
