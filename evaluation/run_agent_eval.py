"""Run deterministic Agent, RAG, memory, and safety evaluations."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import AIMessage

from stylemate.agent.graph import MAX_MODEL_CALLS, MAX_TOOL_CALLS, build_agent_graph
from stylemate.agent.memory import update_conversation_facts
from stylemate.agent.service import AgentService
from stylemate.agent.state import initial_state
from stylemate.agent.tools.wardrobe import recommend_inventory_outfit
from stylemate.config.runtime import RuntimeSettings
from stylemate.demo.sample_data import sample_garments
from stylemate.domain.models import ConversationFacts, ConversationMessage, Garment
from stylemate.evaluation.reporting import text_fingerprint
from stylemate.rag.corpus import load_builtin_records
from stylemate.rag.query_planning import knowledge_compatible
from stylemate.rag.retriever import (
    DashScopeEmbeddingAdapter,
    HybridRetriever,
    OpenAICompatibleEmbeddingAdapter,
    create_chroma_client,
)
from stylemate.repositories.agent_session import SessionAgentRepository
from stylemate.repositories.session import SessionWardrobeRepository
from stylemate.services.wardrobe_service import WardrobeService
from stylemate.storage.images import SessionImageStore

CASES_PATH = Path(__file__).with_name("agent_cases.json")
RAG_CASES_PATH = Path(__file__).with_name("rag_cases.json")
GRAPH_CASES_PATH = Path(__file__).with_name("graph_cases.json")
KNOWLEDGE_PATH = Path(__file__).resolve().parents[1] / "data" / "knowledge" / "records.jsonl"


class EmbeddingEvaluationError(RuntimeError):
    """Report an unusable online embedding setup without leaking provider details."""


class ScriptedToolCallModel:
    """Emit native LangChain tool calls while keeping evaluation deterministic."""

    def __init__(self, tool_calls: list[dict[str, Any]]):
        self.tool_calls = tool_calls
        self.invoke_count = 0

    def bind_tools(self, tools):
        self.bound_tool_names = {tool.name for tool in tools}
        return self

    def invoke(self, _messages):
        self.invoke_count += 1
        if self.invoke_count == 1:
            calls = [
                {
                    "name": call["name"],
                    "args": call.get("args", {}),
                    "id": f"eval-call-{index}",
                }
                for index, call in enumerate(self.tool_calls, start=1)
            ]
            return AIMessage(content="", tool_calls=calls)
        return AIMessage(content="已根据工具结果完成。")


class RepeatingToolCallModel:
    """Keep requesting a tool so the graph's own bounds must terminate the turn."""

    def __init__(self):
        self.invoke_count = 0

    def bind_tools(self, _tools):
        return self

    def invoke(self, _messages):
        self.invoke_count += 1
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "get_user_location",
                    "args": {},
                    "id": f"loop-call-{self.invoke_count}",
                }
            ],
        )


class OfflineHashEmbedding:
    """Deterministic local embedding used only for repeatable retrieval ablation."""

    model = "stylemate-offline-hash-v1"

    def __init__(self, dimensions: int = 384):
        self.dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in _evaluation_tokens(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            vector[int.from_bytes(digest[:4], "big") % self.dimensions] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


def run_agent_evaluation(
    output_path: Path,
    *,
    embedding=None,
    embedding_label: str = "offline_hash",
) -> dict[str, Any]:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    rag_cases = json.loads(RAG_CASES_PATH.read_text(encoding="utf-8"))
    graph_cases = json.loads(GRAPH_CASES_PATH.read_text(encoding="utf-8"))
    indexing_started = time.perf_counter()
    service, retriever = _build_harness(embedding or OfflineHashEmbedding())
    index_build_ms = (time.perf_counter() - indexing_started) * 1000
    if (
        embedding_label != "offline_hash"
        and retriever.stats().get("builtin_sync_failures", 0) > 0
    ):
        raise EmbeddingEvaluationError(
            "Online embedding index build failed; check account balance, "
            "credentials, endpoint, and network before running online evaluation."
        )
    passed = {"routing": 0, "memory": 0, "safety": 0}
    totals = {key: 0 for key in passed}

    for case in cases:
        category = case["category"]
        totals[category] += 1
        if category == "routing":
            reply = service.chat(
                "evaluation-user", f"route-{case['id']}", case["input"]
            )
            tool_names = [trace.name for trace in reply.traces]
            passed[category] += int(case["expected_tool"] in tool_names)
        elif category == "memory":
            facts = update_conversation_facts(
                ConversationFacts(),
                ConversationMessage(role="user", content=case["input"]),
            )
            passed[category] += int(_contains_expected(facts.model_dump(), case["expected"]))
        elif category == "safety":
            passed[category] += int(_safety_case(service, case["kind"]))

    retrieval_ablation = {
        mode: _evaluate_retrieval(retriever, rag_cases, mode)
        for mode in ("bm25", "vector", "hybrid")
    }
    graph_metrics = _evaluate_graph(service, graph_cases)
    hybrid_metrics = retrieval_ablation["hybrid"]
    published_ids = {record.id for record in retriever.records}
    fully_covered = [case for case in rag_cases if set(case["relevant_ids"]) <= published_ids]
    published = {record.id: record for record in retriever.records}
    incompatible_cases = [case["id"] for case in fully_covered if not all(
        knowledge_compatible(case["query"], title=published[key].title, content=published[key].content,
                             topic=published[key].topic) for key in case["relevant_ids"]
    )]
    partial_count = sum(bool(set(case["relevant_ids"]) & published_ids)
                        and not set(case["relevant_ids"]) <= published_ids for case in rag_cases)
    metrics: dict[str, Any] = {
        "case_count": len(cases) + len(rag_cases) + len(graph_cases),
        "retrieval_case_count": len(rag_cases),
        "knowledge_coverage": {
            "published_records": len(published_ids),
            "fully_covered_cases": len(fully_covered),
            "partially_covered_cases": partial_count,
            "uncovered_cases": len(rag_cases) - len(fully_covered) - partial_count,
            "complete_coverage_rate": _rate(len(fully_covered), len(rag_cases)),
            "scope_compatible_fully_covered_cases": len(fully_covered) - len(incompatible_cases),
            "scope_incompatible_case_ids": incompatible_cases,
            "note": "ID availability of historical labels, not semantic support. Scope-incompatible labels are reported separately; raw metrics retain all cases.",
        },
        "conditional_retrieval_ablation": {
            mode: _evaluate_retrieval(retriever, fully_covered, mode)
            for mode in ("bm25", "vector", "hybrid")
        },
        "fingerprint_schema": "utf8-normalized-newlines-v1",
        "knowledge_fingerprint": text_fingerprint(KNOWLEDGE_PATH),
        "dataset_fingerprints": {
            name: text_fingerprint(path)
            for name, path in (("retrieval", RAG_CASES_PATH), ("graph", GRAPH_CASES_PATH),
                               ("routing_memory_safety", CASES_PATH))
        },
        "graph_case_count": len(graph_cases),
        "tool_selection_accuracy": _rate(passed["routing"], totals["routing"]),
        **graph_metrics,
        "rag_recall_at_3": hybrid_metrics["recall_at_3"],
        "rag_recall_at_5": hybrid_metrics["recall_at_5"],
        "rag_mrr_at_5": hybrid_metrics["mrr_at_5"],
        "rag_ndcg_at_5": hybrid_metrics["ndcg_at_5"],
        "rag_hard_negative_avoidance_at_3": hybrid_metrics[
            "hard_negative_avoidance_at_3"
        ],
        "retrieval_ablation": retrieval_ablation,
        "embedding_evaluation": {
            "label": embedding_label,
            "index_build_ms": round(index_build_ms, 3),
            "usage": retriever.stats(),
        },
        "memory_fact_recall": _rate(passed["memory"], totals["memory"]),
        "safety_pass_rate": _rate(passed["safety"], totals["safety"]),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return metrics


def _evaluate_graph(
    service: AgentService, cases: list[dict[str, Any]]
) -> dict[str, float]:
    path_passed = 0
    contract_passed = 0
    write_passed = 0
    write_total = 0
    owner_id = "evaluation-user"

    for case in cases:
        conversation_id = f"graph-{case['id']}"
        toolkit = service._toolkit(owner_id, conversation_id)
        before = [
            garment.model_dump(mode="json")
            for garment in toolkit.wardrobe.list_garments(owner_id)
        ]
        model = ScriptedToolCallModel(case["tool_calls"])
        result = build_agent_graph(model, toolkit.tools).invoke(
            initial_state(
                case["input"],
                owner_id=owner_id,
                conversation_id=conversation_id,
            )
        )
        # Routing decisions are audited separately from actual tool execution.
        traces = [trace for trace in result.get("traces", []) if trace.get("name") != "skill_router"]
        trace_names = [trace.get("name") for trace in traces]
        path_passed += int(trace_names == case["expected_tools"])

        statuses = [trace.get("status") for trace in traces]
        contract_ok = (
            bool(statuses)
            and (
                all(status != "failed" for status in statuses)
                if case["contract"] == "accepted"
                else all(status == "failed" for status in statuses)
            )
        )
        if "expect_sources" in case:
            contract_ok = contract_ok and bool(result.get("sources")) == case["expect_sources"]
        if case.get("expect_empty_knowledge"):
            knowledge_results = [json.loads(message.content).get("result", {})
                                 for message in result.get("messages", [])
                                 if getattr(message, "type", "") == "tool"
                                 and getattr(message, "name", "") in {"rag_search", "care_guide"}]
            contract_ok = contract_ok and bool(knowledge_results) and all(
                item.get("results") == [] and item.get("sources") == [] for item in knowledge_results
            )
        contract_passed += int(contract_ok)

        if operation := case.get("write_operation"):
            write_total += 1
            pending = service.repository.get_pending(owner_id, conversation_id)
            after = [
                garment.model_dump(mode="json")
                for garment in toolkit.wardrobe.list_garments(owner_id)
            ]
            write_passed += int(
                pending is not None
                and pending.operation == operation
                and (result.get("pending_action") or {}).get("operation") == operation
                and before == after
            )

    loop_model = RepeatingToolCallModel()
    loop_toolkit = service._toolkit(owner_id, "graph-loop-bound")
    loop_result = build_agent_graph(loop_model, loop_toolkit.tools).invoke(
        initial_state(
            "持续调用工具",
            owner_id=owner_id,
            conversation_id="graph-loop-bound",
        )
    )
    last_message = loop_result["messages"][-1]
    loop_passed = int(
        loop_model.invoke_count <= MAX_MODEL_CALLS
        and loop_result.get("model_calls", 0) <= MAX_MODEL_CALLS
        and loop_result.get("tool_calls", 0) <= MAX_TOOL_CALLS
        and "上限" in str(getattr(last_message, "content", ""))
        and not getattr(last_message, "tool_calls", None)
    )
    return {
        "graph_tool_path_accuracy": _rate(path_passed, len(cases)),
        "graph_contract_accuracy": _rate(contract_passed, len(cases)),
        "graph_write_confirmation_rate": _rate(write_passed, write_total),
        "graph_loop_bound_pass_rate": _rate(loop_passed, 1),
    }


def _evaluate_retrieval(
    retriever: HybridRetriever,
    cases: list[dict[str, Any]],
    mode: str,
) -> dict[str, float | int | None]:
    recall_3 = 0.0
    recall_5 = 0.0
    reciprocal_ranks = 0.0
    ndcg = 0.0
    hard_negative_passed = 0
    hard_negative_total = 0
    latencies_ms: list[float] = []
    for case in cases:
        started = time.perf_counter()
        hits = retriever.search(
            case["query"],
            "evaluation-user",
            "rag-evaluation",
            top_k=5,
            mode=mode,
        )
        latencies_ms.append((time.perf_counter() - started) * 1000)
        relevant = set(case["relevant_ids"])
        ranked_ids = [hit.record_id for hit in hits if hit.record_id]
        recall_3 += len(relevant.intersection(ranked_ids[:3])) / len(relevant)
        recall_5 += len(relevant.intersection(ranked_ids[:5])) / len(relevant)
        first_rank = next(
            (index for index, record_id in enumerate(ranked_ids[:5], start=1) if record_id in relevant),
            None,
        )
        if first_rank is not None:
            reciprocal_ranks += 1.0 / first_rank
        dcg = sum(
            1.0 / math.log2(index + 1)
            for index, record_id in enumerate(ranked_ids[:5], start=1)
            if record_id in relevant
        )
        ideal = sum(
            1.0 / math.log2(index + 1)
            for index in range(1, min(5, len(relevant)) + 1)
        )
        ndcg += dcg / ideal if ideal else 0.0
        hard_negatives = set(case.get("hard_negative_ids", []))
        if hard_negatives:
            hard_negative_total += 1
            hard_negative_passed += int(
                not hard_negatives.intersection(ranked_ids[:3])
            )
    total = len(cases)
    return {
        "case_count": total,
        "recall_at_3": round(recall_3 / total, 4) if total else None,
        "recall_at_5": round(recall_5 / total, 4) if total else None,
        "mrr_at_5": round(reciprocal_ranks / total, 4) if total else None,
        "ndcg_at_5": round(ndcg / total, 4) if total else None,
        "hard_negative_avoidance_at_3": _rate(
            hard_negative_passed, hard_negative_total
        ),
        "latency_p50_ms": _percentile(latencies_ms, 0.50),
        "latency_p95_ms": _percentile(latencies_ms, 0.95),
    }


def _evaluation_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for segment in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", text.lower()):
        if "\u4e00" <= segment[0] <= "\u9fff":
            characters = list(segment)
            tokens.extend(characters)
            tokens.extend(
                "".join(characters[index : index + 2])
                for index in range(len(characters) - 1)
            )
        else:
            tokens.append(segment)
    return tokens


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * percentile) - 1)
    return round(ordered[index], 3)


def _build_harness(embedding) -> tuple[AgentService, HybridRetriever]:
    agent_repository = SessionAgentRepository({})
    wardrobe_repository = SessionWardrobeRepository({})
    for garment in sample_garments():
        wardrobe_repository.save_garment("evaluation-user", garment)
    retriever = HybridRetriever(
        load_builtin_records(KNOWLEDGE_PATH),
        agent_repository,
        embedding=embedding,
        chroma_client=create_chroma_client("demo"),
    )
    service = AgentService(
        settings=RuntimeSettings(
            app_mode="demo", vision_model_name="vision", text_model_name="text"
        ),
        agent_repository=agent_repository,
        wardrobe_repository=wardrobe_repository,
        wardrobe_service=WardrobeService(
            wardrobe_repository, SessionImageStore({}), 1024
        ),
        retriever=retriever,
        model=None,
    )
    return service, retriever


def _contains_expected(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if isinstance(expected_value, list):
            if not set(expected_value) <= set(actual_value or []):
                return False
        elif actual_value != expected_value:
            return False
    return True


def _safety_case(service: AgentService, kind: str) -> bool:
    if kind == "owner_isolation":
        service.wardrobe_repository.save_garment(
            "other-user",
            Garment(
                id="private-top",
                name="其他用户上衣",
                category="上装",
                primary_color="黑色",
                seasons=["四季"],
                styles=["日常"],
                source="manual",
            ),
        )
        toolkit = service._toolkit("evaluation-user", "safety-owner")
        result = recommend_inventory_outfit({"scene": "日常"}, toolkit.context)
        returned_ids = {
            garment_id
            for recommendation in result["recommendations"]
            for garment_id in recommendation["garment_ids"]
        }
        return "private-top" not in returned_ids
    if kind == "write_confirmation":
        garment_id = "sample-shirt-white"
        reply = service.chat(
            "evaluation-user", "safety-write", f"删除衣物 ID: {garment_id}"
        )
        pending = service.repository.get_pending("evaluation-user", "safety-write")
        current = service.wardrobe_repository.get_garment("evaluation-user", garment_id)
        return bool(reply.traces and pending is not None and current is not None)
    return False


def _rate(passed: int, total: int) -> float:
    return round(passed / total, 4) if total else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run StyleMate Agent evaluation.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/agent_evaluation.json"),
    )
    parser.add_argument(
        "--embedding-mode",
        choices=("offline", "configured", "dashscope"),
        default="offline",
        help="use deterministic vectors, configured OpenAI-compatible embeddings, or DashScope",
    )
    args = parser.parse_args()
    embedding = None
    label = "offline_hash"
    if args.embedding_mode == "dashscope":
        load_dotenv()
        if not os.getenv("DASHSCOPE_API_KEY", "").strip():
            parser.error("DASHSCOPE_API_KEY is required for --embedding-mode dashscope")
        embedding = DashScopeEmbeddingAdapter()
        label = "dashscope_text_embedding_v4"
    elif args.embedding_mode == "configured":
        load_dotenv()
        api_key = os.getenv("EMBEDDING_API_KEY", "").strip()
        base_url = os.getenv("EMBEDDING_BASE_URL", "").strip()
        model_name = os.getenv("EMBEDDING_MODEL_NAME", "").strip()
        if not api_key or not base_url or not model_name:
            parser.error(
                "EMBEDDING_API_KEY, EMBEDDING_BASE_URL, and "
                "EMBEDDING_MODEL_NAME are required for --embedding-mode configured"
            )
        embedding = OpenAICompatibleEmbeddingAdapter(
            api_key,
            base_url,
            model_name,
        )
        label = f"configured_{model_name}"
    try:
        metrics = run_agent_evaluation(
            args.output,
            embedding=embedding,
            embedding_label=label,
        )
    except EmbeddingEvaluationError as exc:
        parser.error(str(exc))
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
