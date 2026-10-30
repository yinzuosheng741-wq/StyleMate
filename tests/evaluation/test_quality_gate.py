import copy
import json
from pathlib import Path

import pytest

from evaluation.quality_gate import check_reports


@pytest.fixture
def reports():
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "artifacts/evaluation_manifest.json").read_text("utf-8"))
    baseline = json.loads((root / "artifacts" / manifest["report"]).read_text("utf-8"))
    rules = {"case_count": 10, "inventory_valid_rate": 1., "constraint_pass_rate": 1., "fallback_success_rate": 1.}
    return copy.deepcopy(baseline), baseline, rules


def test_identical_offline_results_pass(reports):
    assert check_reports(*reports)["passed"]


@pytest.mark.parametrize("key,value", [
    ("safety_pass_rate", 0.99), ("graph_write_confirmation_rate", 0.99),
    ("rag_recall_at_5", 0.01), ("rag_mrr_at_5", float("nan")), ("safety_pass_rate", True),
    ("graph_case_count", 0), ("case_count", 100), ("knowledge_fingerprint", "changed"),
    ("dataset_fingerprints", {}), ("embedding_evaluation", {"label": "online"}),
])
def test_regression_or_incomparable_data_fails(reports, key, value):
    current, baseline, rules = reports
    current[key] = value
    assert not check_reports(current, baseline, rules)["passed"]


def test_missing_rules_or_contract_metrics_cannot_pass(reports):
    current, baseline, rules = reports
    del current["graph_contract_accuracy"]
    rules["case_count"] = 0
    result = check_reports(current, baseline, rules)
    assert "contract_failed:graph_contract_accuracy" in result["failures"]
    assert "rules_cases_missing" in result["failures"]
