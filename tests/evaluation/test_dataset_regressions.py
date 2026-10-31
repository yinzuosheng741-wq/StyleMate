"""Freeze measured functional contracts while retaining the known validation gap."""

from pathlib import Path

from evaluation.benchmark import load_cases, offline_tasks


def test_measured_task_contracts_do_not_regress():
    data, _ = load_cases(Path(__file__).resolve().parents[2] / "evaluation/benchmark_validation_cases.json")
    report = offline_tasks(data["tasks"], repeats=1)
    known_gap = {"v-outfit-colloquial"}
    failures = {row["id"]: [key for key, passed in row["checks"].items()
                            if not passed and key != "exact_tool_set"] for row in report["rows"]}
    failures = {key: value for key, value in failures.items() if value}
    assert not (set(failures) - known_gap), failures
    assert len(report["rows"]) == len(data["tasks"])
