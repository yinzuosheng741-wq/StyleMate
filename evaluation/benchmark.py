"""Repeatable task, retrieval and API measurements; never reads personal wardrobe data."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import statistics
import subprocess
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from evaluation.run_agent_eval import OfflineHashEmbedding
from stylemate.agent.graph import build_agent_graph
from stylemate.agent.policy import current_outfits, request_policy
from stylemate.agent.routing import route_skills
from stylemate.agent.service import AgentService
from stylemate.agent.state import initial_state
from stylemate.agent.tools.location_weather import LocationResult, WeatherResult
from stylemate.config.portable import ServiceConfigStore, apply_environment
from stylemate.config.runtime import RuntimeSettings
from stylemate.demo.sample_data import sample_garments
from stylemate.domain.models import ConversationMessage
from stylemate.model.factory import build_chat_model_from_env
from stylemate.rag.corpus import load_builtin_records
from stylemate.rag.retriever import HybridRetriever, create_chroma_client
from stylemate.repositories.agent_session import SessionAgentRepository
from stylemate.repositories.session import SessionWardrobeRepository
from stylemate.repositories.sqlite import SQLiteWardrobeRepository
from stylemate.services.connection_check import check_service
from stylemate.services.context import _build_embedding
from stylemate.services.wardrobe_service import WardrobeService
from stylemate.storage.images import SessionImageStore

ROOT = Path(__file__).resolve().parents[1]
CASES = Path(__file__).with_name("benchmark_cases.json")


def load_cases(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    paths = [path]
    if data.get("extends"):
        base_path = (path.parent / data["extends"]).resolve()
        if base_path.parent != path.parent.resolve():
            raise ValueError("dataset parent must be in the evaluation directory")
        base = json.loads(base_path.read_text(encoding="utf-8"))
        paths.append(base_path)
        for section in ("tasks", "retrieval"):
            data[section] = [dict(c, split="regression") for c in base[section]] + [dict(c, split="validation") for c in data[section]]
    published = {r.id for r in load_builtin_records(ROOT / "data/knowledge/records.jsonl") if r.is_published_evidence}
    for section, text_key in (("tasks", "input"), ("retrieval", "query")):
        ids = [c["id"] for c in data[section]]
        if len(set(ids)) != len(ids) or not all(c.get(text_key, "").strip() for c in data[section]):
            raise ValueError("duplicate IDs or blank questions")
    for case in data["retrieval"]:
        if not set(case["relevant"]) <= published:
            raise ValueError("new benchmark labels must reference published records")
    return data, paths


def distribution(values):
    if not values:
        return {"n": 0, "mean_ms": None, "p50_ms": None, "p95_ms": None, "p99_ms": None}
    ordered = sorted(values)
    return {"n": len(values), "mean_ms": round(statistics.mean(values), 3),
            **{f"p{q}_ms": round(ordered[max(0, math.ceil(len(values) * q / 100) - 1)], 3)
               for q in (50, 95, 99)}}


def proportion(passed, total):
    if not total:
        return {"passed": passed, "total": total, "rate": None, "wilson_95": None}
    p, z = passed / total, 1.96
    center = (p + z * z / (2 * total)) / (1 + z * z / total)
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return {"passed": passed, "total": total, "rate": round(p, 4),
            "wilson_95": [round(center - radius, 4), round(center + radius, 4)]}


class FixtureWeather:
    def __init__(self, unavailable=False):
        self.unavailable = unavailable

    def weather(self, city=""):
        return (WeatherResult(available=False, reason="timeout") if self.unavailable else
                WeatherResult(available=True, city=city or "杭州", summary="晴", temperature_c=22, humidity=60))

    def locate(self):
        return LocationResult(available=False, reason="location_disabled")


class BrokenModel:
    def bind_tools(self, _tools):
        raise ConnectionError("benchmark-injected-failure")


def harness(*, weather_failure=False, model=None):
    repo, agent = SessionWardrobeRepository({}), SessionAgentRepository({})
    for garment in sample_garments():
        repo.save_garment("benchmark-owner", garment)
    base = sample_garments()[0]
    repo.save_garment("benchmark-owner", base.model_copy(update={"id": "benchmark-wool", "name": "羊毛上衣", "material": "羊毛"}))
    for number in (1, 2):
        repo.save_garment("benchmark-owner", base.model_copy(update={"id": f"duplicate-{number}", "name": "同名上衣"}))
    repo.save_garment("other-owner", base.model_copy(update={"id": "private-other-item"}))
    settings = RuntimeSettings("demo", "offline", "offline")
    retriever = HybridRetriever(load_builtin_records(ROOT / "data/knowledge/records.jsonl"), agent, None,
                                create_chroma_client("demo"))
    return AgentService(settings=settings, agent_repository=agent, wardrobe_repository=repo,
                        wardrobe_service=WardrobeService(repo, SessionImageStore({}), 1024), retriever=retriever,
                        weather_client=FixtureWeather(weather_failure), model=model)


def snapshot(app):
    return [g.model_dump(mode="json") for g in app.wardrobe_repository.list_garments("benchmark-owner")]


def assess(case, reply, pending):
    names = [t.name for t in reply.traces if t.name not in {"skill_router", "model_fallback"}]
    checks = {"expected_tool_hit": set(case["tools"]) <= set(names),
              "exact_tool_set": set(case["tools"]) == set(names),
              "text": all(term in reply.content for term in case.get("contains", [])),
              "nonempty_reply": bool(reply.content.strip())}
    if case.get("any_contains"):
        checks["text"] &= any(term in reply.content for term in case["any_contains"])
    for key in ("sources", "outfits"):
        if key in case:
            checks[key] = bool(getattr(reply, key)) == case[key]
    if "pending" in case:
        checks["pending"] = bool(pending) == case["pending"]
    if case.get("anchor"):
        checks["anchor"] = bool(reply.outfits) and all(case["anchor"] in x.garment_ids for x in reply.outfits)
    return checks, names


def summarize_tasks(rows):
    tools = [status for row in rows for status in row.get("tool_statuses", [])]
    expected = [row for row in rows if row["expected_tools"]]
    f1_scores = []
    for row in rows:
        wanted, actual = set(row["expected_tools"]), set(row.get("actual_tools", []))
        f1_scores.append(2 * len(wanted & actual) / (len(wanted) + len(actual)) if wanted or actual else 1.0)
    # Text checks are finite acceptance contracts; they are not semantic grading.
    functional = [all(ok for key, ok in r["checks"].items() if key != "exact_tool_set") for r in rows]
    unique = {key: [functional[i] for i, row in enumerate(rows) if row['id'] == key] for key in {r['id'] for r in rows}}
    return {"trials": len(rows), "unique_cases": len({r['id'] for r in rows}),
            "functional_task_success": proportion(sum(functional), len(rows)),
            "all_repeats_successful_cases": proportion(sum(all(v) for v in unique.values()), len(unique)),
            "contract_task_success": proportion(sum(r["passed"] for r in rows), len(rows)),
            "expected_tool_hit": proportion(sum(r["checks"].get("expected_tool_hit", False) for r in expected), len(expected)),
            "exact_tool_set": proportion(sum(r["checks"].get("exact_tool_set", False) for r in rows), len(rows)),
            "tool_set_macro_f1": round(statistics.mean(f1_scores), 4) if f1_scores else None,
            "mean_logical_tool_calls": round(statistics.mean(len(r.get("actual_tools", [])) for r in rows), 3) if rows else None,
            "tool_execution_success": proportion(sum(s != "failed" for s in tools), len(tools)),
            "inventory_unchanged": proportion(sum(r["checks"].get("inventory_unchanged", False) for r in rows), len(rows)),
            "latency": distribution([r["duration_ms"] for r in rows]),
            "failure_categories": dict(Counter(key for r in rows for key, ok in r["checks"].items() if not ok)),
            "latency_scope": "task only; fixture creation and preceding setup turns excluded",
            "repeated_trials_are_not_independent_user_tasks": True}


def offline_tasks(cases, repeats):
    rows = []
    for repeat in range(repeats):
        for case in cases:
            observations = []
            app = harness(weather_failure=case.get("weather_failure", False),
                          model=BrokenModel() if case.get("model_failure") else None)
            app.observer = observations.append
            for text in case.get("setup", []):
                app.chat("benchmark-owner", "thread", text)
            before = snapshot(app)
            started = time.perf_counter()
            try:
                kwargs = {"garment_id": case["garment_id"]} if case.get("garment_id") else {}
                reply = app.chat("benchmark-owner", "thread", case["input"], **kwargs)
                checks, names = assess(case, reply, app.repository.get_pending("benchmark-owner", "thread"))
                checks["inventory_unchanged"] = before == snapshot(app)
                if not case.get("weather_failure"):
                    checks["tools_completed"] = all(t.status != "failed" for t in reply.traces if t.name != "model_fallback")
                rows.append({"id": case["id"], "repeat": repeat, "expected_tools": case["tools"],
                             "actual_tools": names, "checks": checks, "passed": all(checks.values()),
                             "tool_statuses": [t.status for t in reply.traces if t.name != "model_fallback"],
                             "duration_ms": (time.perf_counter() - started) * 1000,
                             "answer": reply.content, "diagnostics": observations[-1] if observations else {}})
            except Exception as exc:
                rows.append({"id": case["id"], "repeat": repeat, "expected_tools": case["tools"],
                             "checks": {"exception_free": False}, "passed": False,
                             "duration_ms": (time.perf_counter() - started) * 1000, "error_type": type(exc).__name__})
    return {"summary": summarize_tasks(rows), "rows": rows}


def retrieval(cases, embedding, label):
    app = harness()
    started = time.perf_counter()
    search = HybridRetriever(load_builtin_records(ROOT / "data/knowledge/records.jsonl"), app.repository,
                             embedding, create_chroma_client("demo"))
    build_ms = (time.perf_counter() - started) * 1000
    report = {"embedding": label, "index_build_ms": round(build_ms, 3), "modes": {}}
    for mode in ("bm25", "vector", "hybrid"):
        rows = []
        for case in cases:
            started = time.perf_counter()
            hits = search.search(case["query"], "benchmark-owner", "thread", top_k=5, mode=mode)
            ranked, relevant = [h.record_id for h in hits], set(case["relevant"])
            first = next((i for i, key in enumerate(ranked, 1) if key in relevant), None)
            dcg = sum(1 / math.log2(i + 1) for i, key in enumerate(ranked, 1) if key in relevant)
            ideal = sum(1 / math.log2(i + 1) for i in range(1, min(5, len(relevant)) + 1))
            rows.append({"id": case["id"], "retrieved_ids": ranked, "relevant_ids": case["relevant"],
                         "split": case.get("split", "regression"),
                         "recall_at_5": len(set(ranked) & relevant) / len(relevant) if relevant else None,
                         "precision_at_5": len(set(ranked) & relevant) / 5 if relevant else None,
                         "hit_at_1": bool(ranked and ranked[0] in relevant) if relevant else None,
                         "mrr_at_5": 1 / first if first else 0, "ndcg_at_5": dcg / ideal if ideal else None,
                         "abstained": not hits, "vector_failed": bool(search.last_audit.get("vector_failed")),
                         "duration_ms": (time.perf_counter() - started) * 1000})
        positive = [r for r in rows if r["relevant_ids"]]
        negative = [r for r in rows if not r["relevant_ids"]]
        means = {key: round(statistics.mean(r[key] for r in positive), 4) for key in
                 ("recall_at_5", "precision_at_5", "hit_at_1", "mrr_at_5", "ndcg_at_5")}
        report["modes"][mode] = {"positive_cases": len(positive), "negative_cases": len(negative), **means,
                                  "unsupported_query_abstention": proportion(sum(r["abstained"] for r in negative), len(negative)),
                                  "vector_failures": sum(r["vector_failed"] for r in rows),
                                  "latency": distribution([r["duration_ms"] for r in rows]), "rows": rows}
        print(f"retrieval {label} {mode} finished", flush=True)
    return report


class ObservedModel:
    def __init__(self, model, measurements):
        self.model, self.measurements = model, measurements

    def bind_tools(self, tools):
        return ObservedModel(self.model.bind_tools(tools), self.measurements)

    def invoke(self, messages):
        started = time.perf_counter()
        response = self.model.invoke(messages)
        self.measurements.append({"duration_ms": (time.perf_counter() - started) * 1000,
                                  "usage": getattr(response, "usage_metadata", None)})
        return response


def online_graph(cases, model, repeats):
    rows, calls = [], []
    for repeat in range(repeats):
        for case in cases:
            if not case.get("live_graph"):
                continue
            app = harness()
            toolkit = app._toolkit("benchmark-owner", "thread")
            route = route_skills(case["input"], {t.name for t in toolkit.tools})
            before, started = snapshot(app), time.perf_counter()
            previous_calls = len(calls)
            try:
                with request_policy("benchmark-owner", "thread", route.allowed_tools):
                    state = build_agent_graph(ObservedModel(model, calls), toolkit.tools).invoke(
                        initial_state(case["input"], owner_id="benchmark-owner", conversation_id="thread"))
                    outfits = current_outfits("benchmark-owner", "thread")
                traces = [t for t in state.get("traces", []) if t["name"] != "skill_router"]
                reply = ConversationMessage(role="assistant", content=str(state["messages"][-1].content) or " ",
                                            traces=traces, sources=[{"id": str(i), "title": s.get("title", "source"),
                                            "url": s.get("url") or s.get("source_url", "")} for i, s in enumerate(state.get("sources", []))],
                                            outfits=outfits)
                checks, names = assess(case, reply, app.repository.get_pending("benchmark-owner", "thread"))
                checks["inventory_unchanged"] = before == snapshot(app)
                checks["tools_completed"] = all(t["status"] != "failed" for t in traces)
                rows.append({"id": case["id"], "repeat": repeat, "expected_tools": case["tools"], "actual_tools": names,
                             "checks": checks, "passed": all(checks.values()), "answer": reply.content,
                             "tool_statuses": [t["status"] for t in traces],
                             "duration_ms": (time.perf_counter() - started) * 1000})
            except Exception as exc:
                rows.append({"id": case["id"], "repeat": repeat, "expected_tools": case["tools"],
                             "checks": {"exception_free": False}, "passed": False,
                             "duration_ms": (time.perf_counter() - started) * 1000, "error_type": type(exc).__name__})
            print(f"live graph {case['id']} repeat {repeat + 1}: {'pass' if rows[-1]['passed'] else 'fail'}", flush=True)
            rows[-1]["model_invocations"] = len(calls) - previous_calls
    usage = Counter()
    for call in calls:
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            usage[key] += (call["usage"] or {}).get(key, 0)
    return {"scope": "real model where permitted; deterministic precondition guards; synthetic inventory; mocked 22C weather; finite contract assertions, not human answer grading",
            "summary": summarize_tasks(rows), "model_call_latency": distribution([c["duration_ms"] for c in calls]),
            "provider_reported_tokens": dict(usage), "ttft_ms": None, "cost": None, "rows": rows}


def api_probes(values, repeats):
    reports = {}
    for kind in ("text", "vision", "embedding", "weather"):
        rows = []
        for repeat in range(repeats):
            # Explicit public sample city, preserving the user's saved config.
            configured = dict(values, WEATHER_CITY="杭州", ALLOW_IP_LOCATION="0")
            started = time.perf_counter()
            result = check_service(kind, configured)
            rows.append({"repeat": repeat, "ok": bool(result.get("ok")),
                         "reason": result.get("reason", ""),
                         "duration_ms": (time.perf_counter() - started) * 1000})
            print(f"api {kind} repeat {repeat + 1}: {'pass' if rows[-1]['ok'] else 'fail'}", flush=True)
        reports[kind] = {"success": proportion(sum(r["ok"] for r in rows), len(rows)),
                         "latency": distribution([r["duration_ms"] for r in rows]), "rows": rows}
    reports["location"] = {"status": "not_measured", "reason": "no IP location probe; configured opt-in remains unchanged"}
    return reports


def sqlite_consistency(output, trials=50):
    checks, durations = [], []
    with tempfile.TemporaryDirectory(prefix="consistency-", dir=output) as temporary:
        path = Path(temporary) / "wardrobe.db"
        for index in range(trials):
            started = time.perf_counter()
            repo = SQLiteWardrobeRepository(path)
            item = sample_garments()[0].model_copy(update={"id": f"item-{index}"})
            repo.save_garment("owner", item)
            checks.append(SQLiteWardrobeRepository(path).get_garment("owner", item.id) == item)
            checks.append(repo.get_garment("other-owner", item.id) is None)
            changed = item.model_copy(update={"name": "更新后"})
            repo.save_garment("owner", changed)
            checks.append(SQLiteWardrobeRepository(path).get_garment("owner", item.id) == changed)
            repo.delete_garment("owner", item.id)
            checks.append(SQLiteWardrobeRepository(path).get_garment("owner", item.id) is None)
            durations.append((time.perf_counter() - started) * 1000)
    return {"scenario_trials": trials, "checks": proportion(sum(checks), len(checks)), "latency": distribution(durations),
            "scope": "isolated SQLite CRUD, reload and owner isolation; excludes crash/power-loss and multi-writer testing"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--online", action="store_true")
    parser.add_argument("--config-root", type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--model-repeats", type=int, default=2)
    parser.add_argument("--api-repeats", type=int, default=3)
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--summarize-input", type=Path, help="recompute metrics from retained raw trials without new API calls")
    args = parser.parse_args()
    if min(args.repeats, args.model_repeats, args.api_repeats) < 1:
        parser.error("repeat counts must be positive")
    if args.output.exists():
        parser.error("output already exists; retain previous evidence and choose a new filename")
    if args.online and not args.config_root:
        parser.error("online runs require an explicit --config-root")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.summarize_input:
        report = json.loads(args.summarize_input.read_text(encoding="utf-8"))
        for section in ("offline_tasks", "online_graph"):
            if section in report:
                report[section]["summary"] = summarize_tasks(report[section]["rows"])
        report["analysis_revision"] = 2
        report["analysis_note"] = ("Functional success allows additional read tools when every other acceptance condition holds. "
                                   "Original strict contract success and exact tool-set agreement remain reported; no raw trials changed.")
        report["raw_report_sha256"] = hashlib.sha256(args.summarize_input.read_bytes()).hexdigest()
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0
    data, case_paths = load_cases(args.cases.resolve())
    from scripts.validate import source_fingerprint

    report = {"schema_version": 1, "dataset_version": data["version"], "environment": {"python": platform.python_version(),
              "platform": platform.system(), "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()},
              "fingerprints": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in (*case_paths, ROOT / "data/knowledge/records.jsonl")},
              "limits": ["small project-authored dataset, not held-out external user traffic",
                         "repeats share cases; Wilson intervals are descriptive per-trial approximations",
                         "P95/P99 from small samples are exploratory", "answer faithfulness needs human review",
                         "no comparable before/after baseline exists for the new dataset"]}
    report["started_at"] = datetime.now(timezone.utc).isoformat()
    report["source_fingerprint"] = source_fingerprint()
    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["offline_tasks"] = offline_tasks(data["tasks"], args.repeats)
    report["offline_task_partitions"] = {
        split: summarize_tasks([r for r in report["offline_tasks"]["rows"]
                                if r["id"] in {c["id"] for c in data["tasks"] if c.get("split", "regression") == split}])
        for split in sorted({c.get("split", "regression") for c in data["tasks"]})}
    report["sqlite_consistency"] = sqlite_consistency(args.output.parent)
    report["offline_retrieval"] = retrieval(data["retrieval"], OfflineHashEmbedding(), "offline_hash")
    save()
    if args.online:
        values = ServiceConfigStore(args.config_root).load()
        apply_environment(values)
        settings = RuntimeSettings.from_env()
        report["model_settings"] = {"model": settings.text_model_name, "temperature": 0.2, "max_tokens": 600,
                                    "embedding_model": settings.embedding_model_name}
        report["api_probes"] = api_probes(values, args.api_repeats)
        save()
        model = build_chat_model_from_env(settings)
        if model is not None:
            model.max_tokens = 600
            report["online_graph"] = online_graph(data["tasks"], model, args.model_repeats)
            save()
        embedding = _build_embedding(settings)
        if embedding is not None:
            report["online_retrieval"] = retrieval(data["retrieval"], embedding, "configured_real_embedding")
            save()
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    save()
    print(f"Benchmark saved: {args.output.name}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
