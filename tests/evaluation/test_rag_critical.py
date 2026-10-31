"""The diagnostic evaluator must expose failures rather than reward empty/error outputs."""

import copy
import json

import pytest

from evaluation import rag_critical


@pytest.mark.parametrize("payload", [
    {},
    {"answer_status": "error", "results": [], "sources": []},
    {"answer_status": "evidence_found", "results": [{"snippet": "背景"}], "sources": [{"url": "https://example.org"}]},
    {"answer_status": "not_found", "results": [], "sources": [{"url": "https://example.org"}]},
])
def test_withhold_contract_rejects_errors_and_unsupported_source_exposure(payload):
    assert not rag_critical.assess_payload({"expect": "withhold"}, payload)


def test_positive_control_prevents_always_empty_system_from_passing():
    assert not rag_critical.assess_payload({"expect": "evidence"}, {
        "answer_status": "needs_clarification", "results": [], "sources": [],
    })
    assert rag_critical.assess_payload({"expect": "withhold"}, {
        "answer_status": "needs_clarification", "results": [], "sources": [],
    })


def test_dataset_rejects_duplicate_ids_across_automatic_and_manual_cases(tmp_path):
    data = copy.deepcopy(rag_critical.load_dataset())
    data["manual_review"][0]["id"] = data["contracts"][0]["id"]
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        rag_critical.load_dataset(path)


def test_report_keeps_contract_failures_distinct_from_unrun_semantic_review():
    dataset = rag_critical.load_dataset()
    report = rag_critical.run_audit(dataset)
    assert report["contracts"]["total"] == len(dataset["contracts"])
    assert report["contracts"]["passed"] == sum(row["passed"] for row in report["contracts"]["rows"])
    assert report["manual_review"]["status"] == "not_run"
    assert report["split"] == "development_diagnostic"
    assert report["inventory"]["published"] > 0
    assert set(report["retrieval"]["summary"]) == {"at_4", "at_5"}
    for metrics in report["retrieval"]["summary"].values():
        assert metrics["positive_count"] > 0
        assert metrics["negative_count"] > 0
        assert 0 <= metrics["recall"] <= 1
    assert all(r["isolated_from_other_owner"] and r["isolated_from_other_conversation"]
               for r in report["documents"]["rows"])


def test_strict_cli_writes_findings_then_exits_nonzero(monkeypatch, tmp_path):
    report = {"contracts": {"passed": 0, "total": 1, "rows": [{"passed": False}]},
              "retrieval": {"summary": {}}}
    monkeypatch.setattr(rag_critical, "run_audit", lambda _data: report)
    output = tmp_path / "findings.json"
    monkeypatch.setattr("sys.argv", ["rag_critical", "--output", str(output), "--require-pass"])
    with pytest.raises(SystemExit) as exc:
        rag_critical.main()
    assert exc.value.code == 1
    assert json.loads(output.read_text(encoding="utf-8")) == report
    with pytest.raises(SystemExit) as duplicate:
        rag_critical.main()
    assert duplicate.value.code == 2
