"""Offline diagnostics for critical RAG contracts; failures are findings, not relabelled passes."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage

from evaluation.benchmark import distribution, harness, load_cases
from evaluation.rag_audit import document_audit, inventory
from stylemate.agent.graph import build_agent_graph
from stylemate.agent.policy import request_policy
from stylemate.agent.routing import route_skills
from stylemate.agent.state import initial_state
from stylemate.agent.tools.styling import care_guide
from stylemate.skills.knowledge_qa import KnowledgeQASkill, KnowledgeQuery

ROOT = Path(__file__).resolve().parents[1]
CASES = Path(__file__).with_name("rag_critical_cases.json")


class ScriptedToolModel:
    """Inject exactly one model argument rewrite, without calling any model/API."""

    def __init__(self, name, arguments):
        self.name, self.arguments = name, arguments
        self.calls = 0

    def bind_tools(self, tools):
        self.visible = {tool.name for tool in tools}
        return self

    def invoke(self, _messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(content="", tool_calls=[{
                "name": self.name, "args": self.arguments, "id": "critical-contract-call",
            }])
        return AIMessage(content="脚本结束；本用例只检查工具边界，不评价模型自然语言回复。")


def load_dataset(path=CASES):
    data = json.loads(path.read_text(encoding="utf-8"))
    all_cases = data["contracts"] + data["manual_review"]
    ids = [case["id"] for case in all_cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case IDs")
    for case in data["contracts"]:
        if case["path"] not in {"care_tool", "skill", "graph", "selected_item"}:
            raise ValueError("unknown contract path")
        if case["expect"] not in {"evidence", "withhold"} or not case["query"].strip():
            raise ValueError("invalid contract label")
    return data


def assess_payload(case, payload):
    """Withhold means no result is exposed as direct evidence by today's schema.

    A future partial-support result needs an explicit new contract/version; do
    not count generic evidence_found as a verified safe partial answer.
    """
    results = payload.get("results", [])
    sources = payload.get("sources", [])
    if case["expect"] == "evidence":
        return bool(results and sources and payload.get("answer_status") == "evidence_found")
    return (not results and not sources
            and payload.get("answer_status") in {"needs_clarification", "not_found"})


def contract_case(case):
    app = harness()
    toolkit = app._toolkit("benchmark-owner", "critical-thread")
    path = case["path"]
    started = time.perf_counter()
    if path == "care_tool":
        payload = care_guide({"material": case["query"]}, toolkit.context)
    elif path == "skill":
        payload = KnowledgeQASkill(app.retriever).run(
            "benchmark-owner", "critical-thread", KnowledgeQuery(query=case["query"]),
        ).data
    elif path == "graph":
        model = ScriptedToolModel(case["tool"], case["arguments"])
        allowed = route_skills(case["query"], {tool.name for tool in toolkit.tools}).allowed_tools
        with request_policy("benchmark-owner", "critical-thread", set(allowed)):
            state = build_agent_graph(model, toolkit.tools).invoke(initial_state(
                case["query"], owner_id="benchmark-owner", conversation_id="critical-thread",
            ))
        messages = [m for m in state["messages"] if isinstance(m, ToolMessage)]
        payload = json.loads(messages[-1].content).get("result", {}) if messages else {}
    else:
        base = app.wardrobe_repository.get_garment("benchmark-owner", "benchmark-wool")
        garment = base.model_copy(update={"id": "critical-selected", "name": "测试上衣",
                                          "material": case["material"], "source": "manual"})
        app.wardrobe_repository.save_garment("benchmark-owner", garment)
        reply = app.chat("benchmark-owner", "critical-thread", case["query"], garment_id=garment.id)
        # Selected-item presenter has no structured support state. This is a
        # source-exposure proxy only, not proof of the reply's semantic safety.
        payload = {"answer_status": "evidence_found" if reply.sources else "needs_clarification",
                   "results": [{"url": source.url} for source in reply.sources],
                   "sources": [source.model_dump(mode="json") for source in reply.sources],
                   "reply": reply.content, "assessment_scope": "source_exposure_proxy"}
    return {**case, "passed": assess_payload(case, payload), "observed": payload,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3)}


def retrieval_audit():
    dataset, paths = load_cases(ROOT / "evaluation/benchmark_validation_cases.json")
    app = harness()
    rows = []
    for top_k in (4, 5):
        for case in dataset["retrieval"]:
            started = time.perf_counter()
            hits = app.retriever.search(case["query"], "benchmark-owner", "critical-thread",
                                        top_k=top_k, mode="bm25")
            duration = (time.perf_counter() - started) * 1000
            actual, relevant = [h.record_id for h in hits], set(case["relevant"])
            ranks = [i for i, rid in enumerate(actual, 1) if rid in relevant]
            ideal = sum(1 / math.log2(i + 1) for i in range(1, min(top_k, len(relevant)) + 1))
            rows.append({"id": case["id"], "top_k": top_k, "retrieved_ids": actual,
                         "relevant": sorted(relevant), "duration_ms": round(duration, 3),
                         "recall": len(set(actual) & relevant) / len(relevant) if relevant else None,
                         "rr": 1 / min(ranks) if ranks else 0,
                         "ndcg": sum(1 / math.log2(r + 1) for r in ranks) / ideal if ideal else None})
    summary = {}
    for k in (4, 5):
        positives = [r for r in rows if r["top_k"] == k and r["relevant"]]
        negatives = [r for r in rows if r["top_k"] == k and not r["relevant"]]
        summary[f"at_{k}"] = {
            "positive_count": len(positives), "negative_count": len(negatives),
            **{metric: round(statistics.mean(r[metric] for r in positives), 4)
               for metric in ("recall", "rr", "ndcg")},
            "negative_no_hits": sum(not r["retrieved_ids"] for r in negatives),
            "warm_query_latency": distribution([r["duration_ms"] for r in rows if r["top_k"] == k]),
        }
    return {"mode": "bm25_offline_no_embedding", "summary": summary, "rows": rows,
            "scope": "Historical project-authored regression labels; warm single-run latency excludes setup, model and network.",
            "dataset_paths": [p.relative_to(ROOT).as_posix() for p in paths]}


def run_audit(dataset):
    contracts = [contract_case(case) for case in dataset["contracts"]]
    docs_path = ROOT / "evaluation/rag_audit_cases.json"
    documents = document_audit(json.loads(docs_path.read_text(encoding="utf-8"))["documents"])
    retrieval = retrieval_audit()
    paths = [CASES, docs_path, ROOT / "data/knowledge/records.jsonl",
             *[ROOT / path for path in retrieval["dataset_paths"]], Path(__file__)]
    from scripts.validate import source_fingerprint

    return {
        "version": dataset["version"], "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_fingerprint": source_fingerprint(),
        "sha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        "execution_mode": "offline_fixtures_no_external_models_or_embedding", "split": dataset["split"],
        "limitations": ["Development diagnostics, not held-out or independent human accuracy.",
                        "Scripted graph tests cover argument propagation, not real model behaviour.",
                        "No-results contract is conservative; generic evidence is not semantic support.",
                        "Selected-item checks measure source exposure only.",
                        "Synthetic document span coverage is not OCR/table or answer correctness."],
        "contracts": {"passed": sum(r["passed"] for r in contracts), "total": len(contracts),
                      "failures_by_path": dict(Counter(r["path"] for r in contracts if not r["passed"])),
                      "rows": contracts},
        "retrieval": retrieval, "documents": documents, "inventory": inventory(),
        "manual_review": {"status": "not_run", "count": len(dataset["manual_review"]),
                          "cases": dataset["manual_review"]},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-pass", action="store_true", help="Fail on any critical contract finding.")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("retain previous evidence; choose a new output filename")
    report = run_audit(load_dataset())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    checks = report["contracts"]
    print(json.dumps({"contracts": {k: v for k, v in checks.items() if k != "rows"},
                      "retrieval": report["retrieval"]["summary"], "output": str(args.output)}, ensure_ascii=False))
    if args.require_pass and checks["passed"] != checks["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
