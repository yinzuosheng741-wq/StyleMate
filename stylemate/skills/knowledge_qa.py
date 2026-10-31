"""Bounded retrieval, validation, and one-shot query recovery workflow."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from stylemate.domain.models import SkillOutcome, SkillSpec
from stylemate.rag.models import RetrievalHit
from stylemate.rag.query_planning import knowledge_compatible, requests_exact_product_measurement
from stylemate.skills.runtime import SkillRun


class KnowledgeQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=4, ge=1, le=6)


class KnowledgeQASkill:
    spec = SkillSpec(
        name="knowledge_qa",
        description="混合检索已审核知识与用户资料，检查来源格式并在空召回时最多改写一次。",
        input_model=KnowledgeQuery,
        output_model=SkillOutcome,
        allowed_tools=("hybrid_retrieval", "source_validation", "query_rewrite"),
        max_steps=3,
        fallback_strategy="一次改写后仍无带来源结果时明确返回未找到答案。",
    )

    def __init__(self, retriever):
        self.retriever = retriever

    def run(
        self,
        owner_id: str,
        conversation_id: str,
        request: KnowledgeQuery,
    ) -> SkillOutcome:
        run = SkillRun(self.spec, request, trace_name="KnowledgeQASkill")
        request = run.request
        query = _normalize_query(request.query)
        with run.step("hybrid_retrieval") as step:
            hits = self.retriever.search(query, owner_id, conversation_id, top_k=request.top_k) if self.retriever else []
            if not hits:
                step.status = "fallback"
        if self.retriever is None:
            return self._outcome(request.query, query, [], run, attempts=0, rewritten=False)
        with run.step("source_validation") as step:
            valid_hits = _valid_cited_hits(hits, request.query)
            if not valid_hits:
                step.status = "fallback"
        attempts = 1
        rewritten = False
        effective_query = query
        if not valid_hits:
            rewritten = True
            attempts = 2
            with run.step("query_rewrite") as step:
                effective_query = _rewrite_query(query)
                retry_hits = self.retriever.search(effective_query, owner_id, conversation_id, top_k=request.top_k)
                valid_hits = _valid_cited_hits(retry_hits, request.query)
                if not valid_hits:
                    step.status = "fallback"
        return self._outcome(request.query, effective_query, valid_hits, run,
                             attempts=attempts, rewritten=rewritten)

    def _outcome(
        self,
        original_query: str,
        effective_query: str,
        hits: list[RetrievalHit],
        run: SkillRun,
        *,
        attempts: int,
        rewritten: bool,
    ) -> SkillOutcome:
        results = [_result_payload(hit) for hit in hits]
        # Built-in size entries describe measurement concepts, not per-product
        # dimensions. A user-supplied size chart may still contain the answer.
        if requests_exact_product_measurement(original_query) and not any(hit.document_id for hit in hits):
            return run.finish(status="fallback", data={
                "query": original_query, "effective_query": effective_query,
                "query_rewritten": rewritten, "attempts": attempts,
                "answer_status": "needs_clarification", "missing_conditions": ["product_size_chart"],
                "results": [], "sources": [],
                "message": "当前知识库没有这款产品的具体尺寸数据。请提供准确品牌、款号及官方尺码表；通用测量方法不能代替该款实测尺寸。",
            }, message="请提供这款产品的官方尺码表或测量数据。")
        status = "success" if results else "fallback"
        return run.finish(
            status=status,
            data={
                "query": original_query,
                "effective_query": effective_query,
                "query_rewritten": rewritten,
                "attempts": attempts,
                "validation_scope": "source_format_and_finite_scope_not_answer_entailment",
                "answer_status": "evidence_found" if results else "not_found",
                "results": results,
                "sources": [
                    {
                        "title": item["title"],
                        "url": item["source_url"],
                        "source_name": item["source_name"],
                    }
                    for item in results
                ],
            },
            message=(
                "已找到带来源的相关知识。"
                if results
                else "知识库暂未找到带有效来源格式的相关资料。"
            ),
        )


def _normalize_query(query: str) -> str:
    return " ".join(query.strip().split())


def _rewrite_query(query: str) -> str:
    aliases = {
        "冲锋衣": "功能外套",
        "防泼水": "耐久拒水",
        "尺码号": "品牌尺码表",
    }
    rewritten = query
    for source, target in aliases.items():
        rewritten = rewritten.replace(source, target)
    rewritten = re.sub(r"[吗呢么？?]+$", "", rewritten).strip()
    if rewritten == query:
        # Do not introduce a new task (e.g. care) that can override the user's
        # original size/color intent or make unrelated records appear relevant.
        rewritten = f"{rewritten} 相关资料"
    return rewritten[:4000]


def _valid_cited_hits(hits: list[RetrievalHit], original_query: str) -> list[RetrievalHit]:
    return [
        hit
        for hit in hits
        if hit.snippet.strip()
        and hit.source_url.startswith(("https://", "http://", "user-document://"))
        and (hit.document_id or hit.source_url.startswith("user-document://") or knowledge_compatible(
            original_query, title=hit.title, content=hit.snippet, topic=hit.topic,
        ))
    ]


def _result_payload(hit: RetrievalHit) -> dict:
    return {
        "title": hit.title,
        "snippet": hit.snippet[:400],
        "source_name": hit.source_name,
        "source_url": str(hit.source_url),
        "topic": hit.topic,
        "score": hit.score,
        "record_id": hit.record_id,
        "document_id": hit.document_id,
        "chunk_id": hit.chunk_id,
        "page_number": hit.page_number,
        "section_title": hit.section_title,
        "source_locator": hit.source_locator,
        "review_status": hit.review_status,
        "applicability": hit.applicability,
        "limitations": hit.limitations,
    }
