import json
from pathlib import Path

import pytest

from evaluation.run_agent_eval import EmbeddingEvaluationError, _evaluate_retrieval, run_agent_evaluation
from stylemate.rag.corpus import load_builtin_records
from stylemate.rag.models import RetrievalHit


def test_retrieval_metrics_keep_unavailable_labels_in_the_raw_denominator():
    class Retriever:
        def search(self, *_args, **_kwargs):
            return [RetrievalHit(title="Fixture", snippet="fixture", source_name="fixture",
                                 source_url="https://example.test", topic="care", score=1, record_id="available")]

    cases = [{"query": "test", "relevant_ids": ["available"]},
             {"query": "test", "relevant_ids": ["quarantined"]}]
    report = _evaluate_retrieval(Retriever(), cases, "bm25")
    assert report["case_count"] == 2
    assert report["recall_at_5"] == 0.5
    assert report["mrr_at_5"] == 0.5


def test_empty_conditional_subset_is_unavailable_not_zero_quality():
    report = _evaluate_retrieval(None, [], "hybrid")
    assert report["case_count"] == 0
    assert report["recall_at_5"] is None


def test_agent_evaluation_runs_document_level_retrieval_cases(tmp_path):
    target = tmp_path / "agent-evaluation.json"

    result = run_agent_evaluation(target)

    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved == result
    assert saved["case_count"] == 101
    assert saved["retrieval_case_count"] == 60
    assert saved["graph_case_count"] == 20
    assert saved["tool_selection_accuracy"] >= 0.9
    assert saved["graph_tool_path_accuracy"] == 1.0
    assert saved["graph_contract_accuracy"] == 1.0
    assert saved["graph_write_confirmation_rate"] == 1.0
    assert saved["graph_loop_bound_pass_rate"] == 1.0
    coverage = saved["knowledge_coverage"]
    assert coverage["published_records"] > 0
    assert coverage["uncovered_cases"] >= 0
    assert sum(coverage[k] for k in ("fully_covered_cases", "partially_covered_cases", "uncovered_cases")) == 60
    covered_upper_bound = (coverage["fully_covered_cases"] + coverage["partially_covered_cases"]) / 60
    assert 0 <= saved["rag_recall_at_3"] <= covered_upper_bound
    for mode, raw in saved["retrieval_ablation"].items():
        assert raw["case_count"] == 60
        conditional = saved["conditional_retrieval_ablation"][mode]
        assert conditional["case_count"] == coverage["fully_covered_cases"]
        assert 0 <= conditional["recall_at_5"] <= 1
    assert set(saved["retrieval_ablation"]) == {"bm25", "vector", "hybrid"}
    assert saved["retrieval_ablation"]["hybrid"]["latency_p95_ms"] > 0
    assert saved["memory_fact_recall"] >= 0.9
    assert saved["safety_pass_rate"] == 1.0


def test_rag_judgments_reference_existing_records():
    project_root = Path(__file__).resolve().parents[2]
    record_ids = {
        record.id
        for record in load_builtin_records(
            project_root / "data" / "knowledge" / "records.jsonl"
        )
    }
    cases = json.loads(
        (project_root / "evaluation" / "rag_cases.json").read_text(
            encoding="utf-8"
        )
    )

    assert len(cases) == 60
    assert len({case["id"] for case in cases}) == 60
    for case in cases:
        relevant = set(case["relevant_ids"])
        hard_negatives = set(case.get("hard_negative_ids", []))
        assert relevant
        assert relevant <= record_ids
        assert hard_negatives <= record_ids
        assert relevant.isdisjoint(hard_negatives)


class FailingEmbedding:
    model = "failing-online-evaluation"

    def embed_documents(self, _texts):
        raise RuntimeError("provider payload must not be exposed")

    def embed_query(self, _text):
        raise RuntimeError("provider payload must not be exposed")


def test_online_evaluation_fails_clearly_when_index_build_fails(tmp_path):
    target = tmp_path / "online-evaluation.json"

    with pytest.raises(EmbeddingEvaluationError, match="index build failed"):
        run_agent_evaluation(
            target,
            embedding=FailingEmbedding(),
            embedding_label="dashscope_text_embedding_v4",
        )

    assert not target.exists()
