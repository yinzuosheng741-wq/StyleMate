"""Stage-level RAG diagnostics: evidence coverage, retrieval and context retention."""

import argparse
import hashlib
import json
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from evaluation.benchmark import load_cases, retrieval
from evaluation.run_agent_eval import OfflineHashEmbedding
from stylemate.domain.models import UserDocument
from stylemate.rag.corpus import load_builtin_records
from stylemate.rag.query_planning import SUBJECTS
from stylemate.rag.retriever import HybridRetriever, create_chroma_client
from stylemate.rag.user_docs import chunk_user_document
from stylemate.repositories.agent_session import SessionAgentRepository
from stylemate.skills.knowledge_qa import KnowledgeQASkill, KnowledgeQuery

ROOT = Path(__file__).resolve().parents[1]
CASES = Path(__file__).with_name("rag_audit_cases.json")


def make_document(case):
    if "pages" in case:
        pages = case["pages"]
        text = "\n".join(pages)
        mime = "application/pdf"
    else:
        separator = "\n\n" if case["headings_with_blank_lines"] else "\n"
        text = separator.join(f"## {s['title']}\n{s['prefix'] * s['repeat']}{s['text']}" for s in case["sections"])
        pages, mime = [], "text/markdown"
    return UserDocument(owner_id="audit-owner", conversation_id="audit-thread", document_id=case["id"],
                        filename=f"{case['id']}.{'pdf' if pages else 'md'}", mime_type=mime,
                        text=text, pages=pages, created_at=datetime(2026, 10, 31))


def document_audit(cases, embedding=None):
    rows = []
    for case in cases:
        document = make_document(case)
        repository = SessionAgentRepository({})
        repository.save_document(document)
        chunks = chunk_user_document(document)
        retriever = HybridRetriever([], repository, embedding, create_chroma_client("demo"))
        retriever.sync_user_documents("audit-owner", "audit-thread", [document])
        hits = retriever.search(case["query"], "audit-owner", "audit-thread", top_k=4)
        outcome = KnowledgeQASkill(retriever).run("audit-owner", "audit-thread", KnowledgeQuery(query=case["query"]))
        spans = case["expected"]
        rows.append({"id": case["id"], "chunks": len(chunks),
                     "chunk_span_coverage": sum(any(span in c.text for c in chunks) for span in spans) / len(spans),
                     "retrieval_span_coverage": sum(any(span in h.snippet for h in hits) for span in spans) / len(spans),
                     "skill_context_span_coverage": sum(any(span in h["snippet"] for h in outcome.data["results"]) for span in spans) / len(spans),
                     "expected_section_titles": [s["title"] for s in case.get("sections", [])],
                     "actual_section_titles": sorted({c.section_title for c in chunks if c.section_title}),
                     "hits": [h.model_dump(mode="json") for h in hits],
                     "isolated_from_other_owner": not retriever.search(case["query"], "other-owner", "audit-thread"),
                     "isolated_from_other_conversation": not retriever.search(case["query"], "audit-owner", "other-thread")})
    return {"summary": {key: round(statistics.mean(row[key] for row in rows), 4) for key in
                        ("chunk_span_coverage", "retrieval_span_coverage", "skill_context_span_coverage")}, "rows": rows,
            "scope": "synthetic exact-span retention checks, not PDF OCR quality or semantic answer correctness"}


def query_audit(cases, embedding=None):
    records = load_builtin_records(ROOT / "data/knowledge/records.jsonl")
    retriever = HybridRetriever(records, SessionAgentRepository({}), embedding, create_chroma_client("demo"))
    modes = {}
    for mode in (("bm25", "vector", "hybrid") if embedding else ("bm25",)):
        rows = []
        for case in cases:
            hits = retriever.search(case["query"], "audit-owner", "audit-thread", top_k=5, mode=mode)
            wanted = set(case.get("relevant", []))
            actual = [h.record_id for h in hits]
            rows.append({**case, "retrieved_ids": actual,
                         "recall_at_5": len(wanted.intersection(actual)) / len(wanted) if wanted else None,
                         "top1_relevant": actual[0] in wanted if actual and wanted else False,
                         "returned_any": bool(hits), "audit": dict(retriever.last_audit)})
        positive = [row for row in rows if row["kind"] == "supported"]
        negative = [row for row in rows if row["kind"] in {"out_of_scope", "unsupported_specific"}]
        modes[mode] = {"supported_recall_at_5": round(statistics.mean(row["recall_at_5"] for row in positive), 4),
                       "supported_hit_at_1": round(statistics.mean(row["top1_relevant"] for row in positive), 4),
                       "negative_abstention": {"passed": sum(not row["returned_any"] for row in negative), "total": len(negative)},
                       "coverage_requirements_with_any_hits": sum(row["returned_any"] for row in rows if row["kind"] == "coverage_requirement"),
                       "coverage_warning": "any retrieved hit is not proof the requested capability is supported", "rows": rows}
    return modes


def inventory():
    import re

    records = load_builtin_records(ROOT / "data/knowledge/records.jsonl")
    published = [r for r in records if r.is_published_evidence]
    lengths = [len(r.content) for r in published]
    return {"all_records": len(records), "published": len(published),
            "statuses": dict(Counter(r.review_status for r in records)),
            "published_topics": dict(Counter(r.topic for r in published)),
            "summary_characters": {"min": min(lengths), "median": statistics.median(lengths), "max": max(lengths)},
            "material_evidence": {name: [r.id for r in published if re.search(pattern, f"{r.title} {r.content}", re.I)]
                                  for name, pattern in SUBJECTS.items()},
            "duplicate_contents": len(published) - len({r.content for r in published})}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--online", action="store_true")
    parser.add_argument("--config-root", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("retain previous evidence; choose a new output filename")
    if args.online and not args.config_root:
        parser.error("online run needs an explicit config root")
    dataset = json.loads(CASES.read_text(encoding="utf-8"))
    from scripts.validate import source_fingerprint

    paths = [CASES, ROOT / "data/knowledge/records.jsonl", ROOT / "evaluation/benchmark_cases.json",
             ROOT / "evaluation/benchmark_validation_cases.json"]
    report = {"version": dataset["version"], "source_fingerprint": source_fingerprint(),
              "fingerprints": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
              "inventory": inventory(), "diagnostic_queries": query_audit(dataset["queries"]),
              "documents": document_audit(dataset["documents"]),
              "scope": "project-authored cases; no independent answer-faithfulness grade; no source HTML copied"}
    regression, _ = load_cases(ROOT / "evaluation/benchmark_validation_cases.json")
    report["fixed_40_retrieval_cases"] = retrieval(regression["retrieval"], OfflineHashEmbedding(), "offline_hash")
    if args.online:
        from stylemate.config.portable import ServiceConfigStore, apply_environment
        from stylemate.config.runtime import RuntimeSettings
        from stylemate.services.context import _build_embedding

        apply_environment(ServiceConfigStore(args.config_root).load())
        settings = RuntimeSettings.from_env()
        embedding = _build_embedding(settings)
        if embedding is None:
            raise ValueError("embedding is not configured")
        report["embedding_model"] = settings.embedding_model_name
        report["real_embedding_fixed_40"] = retrieval(regression["retrieval"], embedding, "configured_real_embedding")
        report["real_embedding_diagnostics"] = query_audit(dataset["queries"], embedding)
        report["real_embedding_documents"] = document_audit(dataset["documents"], embedding)
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
