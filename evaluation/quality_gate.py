"""Deterministic regression gate against the reviewed, fingerprint-bound baseline."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from evaluation.run_agent_eval import run_agent_evaluation
from evaluation.run_eval import run_evaluation
from stylemate.evaluation.reporting import load_evaluation_summary

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_METRICS = (
    "tool_selection_accuracy", "graph_tool_path_accuracy", "graph_contract_accuracy",
    "graph_write_confirmation_rate", "graph_loop_bound_pass_rate", "memory_fact_recall", "safety_pass_rate",
)
RETRIEVAL_METRICS = ("rag_recall_at_5", "rag_mrr_at_5", "rag_ndcg_at_5", "rag_hard_negative_avoidance_at_3")


def valid_rate(value):
    return not isinstance(value, bool) and isinstance(value, (float, int)) and math.isfinite(value) and 0 <= value <= 1


def check_reports(current, baseline, rules):
    failures = []
    for key in ("fingerprint_schema", "knowledge_fingerprint", "dataset_fingerprints"):
        if not baseline.get(key) or current.get(key) != baseline[key]:
            failures.append("incomparable:" + key)
    for key in ("case_count", "retrieval_case_count", "graph_case_count"):
        expected = baseline.get(key)
        if type(expected) is not int or expected < 1 or type(current.get(key)) is not int or current[key] != expected:
            failures.append("denominator_changed:" + key)
    for report in (current, baseline):
        if report.get("embedding_evaluation", {}).get("label") != "offline_hash":
            failures.append("offline_embedding_required")
    for key in CONTRACT_METRICS:
        if not valid_rate(current.get(key)) or current[key] != 1.0:
            failures.append("contract_failed:" + key)
    for key in RETRIEVAL_METRICS:
        if not valid_rate(current.get(key)) or not valid_rate(baseline.get(key)):
            failures.append("invalid_metric:" + key)
        elif current[key] + 0.0001 < baseline[key]:
            failures.append("retrieval_regression:" + key)
    if type(rules.get("case_count")) is not int or rules["case_count"] < 1:
        failures.append("rules_cases_missing")
    for key in ("inventory_valid_rate", "constraint_pass_rate", "fallback_success_rate"):
        if not valid_rate(rules.get(key)) or rules[key] != 1.0:
            failures.append("rules_failed:" + key)
    return {"passed": not failures, "failures": failures,
            "scope": "fixed offline regression only; not an online-model quality claim"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts/validation")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    baseline = load_evaluation_summary(ROOT)
    if baseline.status != "current":
        result = {"passed": False, "failures": ["baseline_not_current:" + baseline.status]}
    else:
        current = run_agent_evaluation(args.output_dir / "agent.json")
        rules = run_evaluation(args.output_dir / "rules.json")
        result = check_reports(current, baseline.metrics, rules)
        result["baseline"] = baseline.report_name
    (args.output_dir / "quality-gate.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
