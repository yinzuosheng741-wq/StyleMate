"""Bind displayed metrics to both corpus and task-set fingerprints."""

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class EvaluationSummary:
    status: str
    message: str
    metrics: dict = field(default_factory=dict)
    report_name: str = ""


def text_fingerprint(path: Path) -> str:
    """Hash UTF-8 content with universal newlines, stable across Git checkouts."""
    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def load_evaluation_summary(root: Path) -> EvaluationSummary:
    try:
        manifest = json.loads((root / "artifacts/evaluation_manifest.json").read_text("utf-8"))
        name = manifest["report"]
        if manifest.get("schema_version") != 1 or not isinstance(name, str) or Path(name).name != name or not name.endswith(".json"):
            raise ValueError("invalid_report_manifest")
        path = (root / "artifacts" / name).resolve()
        path.relative_to((root / "artifacts").resolve())
        report = json.loads(path.read_text("utf-8"))
        if not isinstance(report, dict) or not isinstance(report.get("dataset_fingerprints"), dict):
            raise ValueError("invalid_report")
        if report.get("fingerprint_schema") != "utf8-normalized-newlines-v1":
            return EvaluationSummary("stale", "报告的版本指纹格式已过期；请重新评测。")
        knowledge_hash = text_fingerprint(root / "data/knowledge/records.jsonl")
        if report.get("knowledge_fingerprint") != knowledge_hash:
            return EvaluationSummary("stale", "知识库已变更，当前报告不能代表这版知识库；请重新评测。")
        datasets = {"retrieval": "rag_cases.json", "graph": "graph_cases.json", "routing_memory_safety": "agent_cases.json"}
        for key, filename in datasets.items():
            expected = text_fingerprint(root / "evaluation" / filename)
            if report.get("dataset_fingerprints", {}).get(key) != expected:
                return EvaluationSummary("stale", "评测题集已变更或缺少版本指纹；请重新评测。")
        for key in ("rag_recall_at_5", "rag_mrr_at_5", "rag_ndcg_at_5"):
            value = report.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("invalid_metric")
        if not isinstance(report.get("knowledge_coverage"), dict) or not isinstance(report.get("embedding_evaluation"), dict):
            raise ValueError("invalid_report_metadata")
        coverage = report["knowledge_coverage"]
        counts = [report.get("retrieval_case_count"), report.get("case_count"), report.get("graph_case_count")]
        counts += [coverage.get(key) for key in ("published_records", "fully_covered_cases", "partially_covered_cases", "uncovered_cases")]
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts):
            raise ValueError("invalid_report_count")
        if sum(coverage[key] for key in ("fully_covered_cases", "partially_covered_cases", "uncovered_cases")) != report["retrieval_case_count"]:
            raise ValueError("coverage_denominator_mismatch")
        return EvaluationSummary("current", "语料与题集版本匹配；结果仅代表该离线回归集。", report, name)
    except (OSError, ValueError, KeyError, TypeError):
        return EvaluationSummary("unavailable", "暂时没有可核验的评测报告。")
