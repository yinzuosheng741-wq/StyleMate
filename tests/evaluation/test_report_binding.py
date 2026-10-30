import hashlib
import json
from pathlib import Path

import pytest

import scripts.build_portable as packaging
from scripts.build_portable import selected_files
from stylemate.evaluation.reporting import load_evaluation_summary


def make_report(root):
    for directory in ("artifacts", "data/knowledge", "evaluation"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    corpus = root / "data/knowledge/records.jsonl"
    corpus.write_bytes(b"corpus-version-one\n")
    datasets = {}
    for key, name in (("retrieval", "rag_cases.json"), ("graph", "graph_cases.json"), ("routing_memory_safety", "agent_cases.json")):
        path = root / "evaluation" / name
        path.write_bytes(b"[]\n")
        datasets[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    report = {"fingerprint_schema": "utf8-normalized-newlines-v1",
              "knowledge_fingerprint": hashlib.sha256(corpus.read_bytes()).hexdigest(),
              "dataset_fingerprints": datasets, "rag_recall_at_5": 0.2, "rag_mrr_at_5": 0.3,
              "rag_ndcg_at_5": 0.4, "knowledge_coverage": {"published_records": 2, "fully_covered_cases": 1,
                                                          "partially_covered_cases": 0, "uncovered_cases": 1},
              "retrieval_case_count": 2, "case_count": 2, "graph_case_count": 0,
              "embedding_evaluation": {"label": "offline_hash"}}
    (root / "artifacts/report.json").write_text(json.dumps(report), encoding="utf-8")
    (root / "artifacts/evaluation_manifest.json").write_text(json.dumps({"schema_version": 1, "report": "report.json"}), encoding="utf-8")
    return report


@pytest.mark.parametrize("changed", ["data/knowledge/records.jsonl", "evaluation/rag_cases.json", "evaluation/graph_cases.json"])
def test_version_mismatch_hides_metrics_instead_of_displaying_historical_success(tmp_path, changed):
    make_report(tmp_path)
    assert load_evaluation_summary(tmp_path).status == "current"
    (tmp_path / changed).write_text("new-version", encoding="utf-8")
    summary = load_evaluation_summary(tmp_path)
    assert summary.status == "stale"
    assert summary.metrics == {}


@pytest.mark.parametrize("value", [float("nan"), 2.0, -0.1, True, "95%"])
def test_invalid_metrics_are_not_shown(tmp_path, value):
    report = make_report(tmp_path)
    report["rag_recall_at_5"] = value
    (tmp_path / "artifacts/report.json").write_text(json.dumps(report), encoding="utf-8")
    assert load_evaluation_summary(tmp_path).status == "unavailable"


def test_portable_snapshot_includes_active_report_and_dataset_versions():
    root = Path(__file__).resolve().parents[2]
    names = {path.relative_to(root).as_posix() for path in selected_files(root)}
    assert "artifacts/evaluation_manifest.json" in names
    manifest = json.loads((root / "artifacts/evaluation_manifest.json").read_text("utf-8"))
    assert "artifacts/" + manifest["report"] in names
    assert "evaluation/rag_cases.json" in names
    assert "requirements-common.txt" in names


def test_inconsistent_coverage_denominator_is_not_presented_as_current(tmp_path):
    report = make_report(tmp_path)
    report["knowledge_coverage"]["fully_covered_cases"] = 20
    (tmp_path / "artifacts/report.json").write_text(json.dumps(report), encoding="utf-8")
    assert load_evaluation_summary(tmp_path).status == "unavailable"


def test_git_ignored_local_notes_cannot_enter_source_snapshot(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/private-notes.md").write_text("private fixture", encoding="utf-8")
    (tmp_path / "docs/public.md").write_text("public fixture", encoding="utf-8")
    monkeypatch.setattr(packaging.subprocess, "check_output", lambda *_a, **_k: b"docs/public.md\0")
    names = {path.relative_to(tmp_path).as_posix() for path in selected_files(tmp_path)}
    assert "docs/public.md" in names
    assert "docs/private-notes.md" not in names


def test_git_checkout_newline_conversion_does_not_invalidate_content_versions(tmp_path):
    make_report(tmp_path)
    (tmp_path / "data/knowledge/records.jsonl").write_bytes(b"corpus-version-one\r\n")
    (tmp_path / "evaluation/rag_cases.json").write_bytes(b"[]\r\n")
    assert load_evaluation_summary(tmp_path).status == "current"
