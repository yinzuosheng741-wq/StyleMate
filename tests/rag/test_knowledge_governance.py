from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.build_knowledge import audit
from stylemate.rag.corpus import load_builtin_records
from stylemate.rag.models import KnowledgeRecord
from stylemate.rag.retriever import HybridRetriever, create_chroma_client
from stylemate.repositories.agent_session import SessionAgentRepository


def _record(**changes):
    values = dict(id="review", title="洗护知识草稿", content="这是一条尚待验证的衣物护理摘要，必须核对具体来源和适用条件后才能进入默认的事实检索流程。",
                  source_name="Fixture", source_url="https://example.test/care", topic="care", retrieved_at="2026-10-22")
    return KnowledgeRecord(**(values | changes))


def test_pending_and_project_rules_cannot_enter_factual_retrieval():
    pending = _record()
    heuristic = _record(id="rule", content_kind="heuristic", review_status="project_rule", source_url=None)
    retriever = HybridRetriever([pending, heuristic], SessionAgentRepository({}), None, create_chroma_client("demo"))
    assert retriever.search("洗护 衣物", "owner", "thread") == []


def test_reviewed_record_requires_scope_locator_and_review_provenance():
    with pytest.raises(ValidationError, match="provenance"):
        _record(review_status="reviewed")
    with pytest.raises(ValidationError, match="heuristics"):
        _record(content_kind="heuristic", review_status="reviewed")


def test_reviewed_hits_retain_product_scope_and_special_case_limitations():
    record = _record(review_status="reviewed", source_locator="Special Care", reviewer="fixture",
                     reviewed_at="2026-10-22", review_note="Synthetic fixture", applicability="普通 GORE-TEX",
                     limitations="SHAKEDRY 除外")
    retriever = HybridRetriever([record], SessionAgentRepository({}), None, create_chroma_client("demo"))
    hit = retriever.search("衣物护理", "owner", "thread")[0]
    assert hit.source_locator == "Special Care"
    assert hit.limitations == "SHAKEDRY 除外"
    assert hit.review_status == "reviewed"


def test_corpus_audit_accepts_expansion_beyond_64_records(tmp_path):
    import json

    records = load_builtin_records(Path("data/knowledge/records.jsonl"))
    extra = records[0].model_copy(update={"id": "extra-reviewed-record"})
    path = tmp_path / "expanded.jsonl"
    path.write_text("".join(json.dumps(r.model_dump(mode="json"), ensure_ascii=False) + "\n"
                            for r in [*records, extra]), encoding="utf-8")
    assert audit(path, Path("data/knowledge/sources.json")) == []
