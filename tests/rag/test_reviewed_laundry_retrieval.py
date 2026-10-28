"""Reviewed care sections reach actual BM25 retrieval with source boundaries."""

from pathlib import Path

import pytest

from stylemate.evaluation.reporting import load_evaluation_summary
from stylemate.rag.corpus import load_builtin_records
from stylemate.rag.retriever import HybridRetriever, create_chroma_client
from stylemate.repositories.agent_session import SessionAgentRepository


@pytest.mark.parametrize("query,expected", [
    ("五类洗护符号水洗漂白干燥熨烫专业护理", "care-symbol-sequence"),
    ("深色鲜艳衣物第一次怎么清洗分类", "care-sort-before-wash"),
    ("污渍没有洗掉可以直接烘干吗", "care-stain-before-dry"),
    ("衣服还没完全干能叠好收进衣柜吗", "storage-dry-before-fold"),
    ("洗后干燥的衣服应该何时折叠", "storage-fold-promptly"),
    ("洗涤剂用量是越多越好吗", "care-wash-detergent-dose"),
    ("水洗符号数字和单横线双横线是什么意思", "care-wash-symbol-temperature"),
])
def test_reviewed_laundry_question_returns_the_compared_section(query, expected):
    records = load_builtin_records(Path("data/knowledge/records.jsonl"))
    retriever = HybridRetriever(records, SessionAgentRepository({}), None, create_chroma_client("demo"))
    hits = retriever.search(query, "review-user", "review-conversation", top_k=3)
    assert hits[0].record_id == expected
    assert hits[0].review_status == "reviewed"
    assert hits[0].source_locator and hits[0].applicability and hits[0].limitations


def test_displayed_evaluation_matches_the_checked_in_corpus_and_full_denominator():
    summary = load_evaluation_summary(Path("."))
    assert summary.status == "current"
    assert summary.metrics["retrieval_case_count"] == 60
    assert summary.metrics["embedding_evaluation"]["label"] == "offline_hash"
    coverage = summary.metrics["knowledge_coverage"]
    assert coverage["published_records"] == sum(r.is_published_evidence for r in load_builtin_records(Path("data/knowledge/records.jsonl")))
    assert sum(coverage[k] for k in ("fully_covered_cases", "partially_covered_cases", "uncovered_cases")) == 60
