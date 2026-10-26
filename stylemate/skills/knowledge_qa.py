"""Bounded retrieval, validation, and one-shot query recovery workflow."""

from __future__ import annotations

import re
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field

from stylemate.domain.models import AgentTrace, AgentTraceStep, SkillOutcome, SkillSpec
from stylemate.rag.models import RetrievalHit


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
        started = perf_counter()
        steps: list[AgentTraceStep] = []
        query = _normalize_query(request.query)
        if self.retriever is None:
            steps.append(_step("hybrid_retrieval", "fallback", "retriever unavailable"))
            return self._outcome(
                request.query,
                query,
                [],
                steps,
                started,
                attempts=0,
                rewritten=False,
            )

        hits = self.retriever.search(
            query, owner_id, conversation_id, top_k=request.top_k
        )
        valid_hits = _valid_cited_hits(hits)
        steps.append(
            _step(
                "hybrid_retrieval",
                "success" if hits else "fallback",
                f"retrieved {len(hits)} candidates",
            )
        )
        steps.append(
            _step(
                "source_validation",
                "success" if valid_hits else "fallback",
                f"checked source URL format for {len(valid_hits)} results; semantic support not verified",
            )
        )
        attempts = 1
        rewritten = False
        effective_query = query
        if not valid_hits:
            rewritten = True
            attempts = 2
            effective_query = _rewrite_query(query)
            retry_hits = self.retriever.search(
                effective_query,
                owner_id,
                conversation_id,
                top_k=request.top_k,
            )
            valid_hits = _valid_cited_hits(retry_hits)
            steps.append(
                _step(
                    "query_rewrite",
                    "success" if valid_hits else "fallback",
                    "one bounded retrieval retry completed",
                )
            )
        return self._outcome(
            request.query,
            effective_query,
            valid_hits,
            steps,
            started,
            attempts=attempts,
            rewritten=rewritten,
        )

    def _outcome(
        self,
        original_query: str,
        effective_query: str,
        hits: list[RetrievalHit],
        steps: list[AgentTraceStep],
        started: float,
        *,
        attempts: int,
        rewritten: bool,
    ) -> SkillOutcome:
        results = [_result_payload(hit) for hit in hits]
        status = "success" if results else "fallback"
        return SkillOutcome(
            status=status,
            data={
                "query": original_query,
                "effective_query": effective_query,
                "query_rewritten": rewritten,
                "attempts": attempts,
                "validation_scope": "source_format_only_not_answer_entailment",
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
            trace=AgentTrace(
                skill_name="KnowledgeQASkill",
                steps=steps[: self.spec.max_steps],
                duration_ms=max(0, round((perf_counter() - started) * 1000)),
                status=status,
            ),
            user_message=(
                "已找到带来源的相关知识。"
                if results
                else "知识库暂未找到带有效来源格式的相关资料。"
            ),
        )


def _normalize_query(query: str) -> str:
    return " ".join(query.strip().split())


def _rewrite_query(query: str) -> str:
    aliases = {
        "冲锋衣": "GORE-TEX 功能外套",
        "毛衣": "羊毛衣物",
        "防泼水": "耐久拒水",
        "尺码号": "品牌尺码表",
    }
    rewritten = query
    for source, target in aliases.items():
        rewritten = rewritten.replace(source, target)
    rewritten = re.sub(r"[吗呢么？?]+$", "", rewritten).strip()
    if rewritten == query:
        rewritten = f"{rewritten} 衣物穿搭洗护知识"
    return rewritten[:4000]


def _valid_cited_hits(hits: list[RetrievalHit]) -> list[RetrievalHit]:
    return [
        hit
        for hit in hits
        if hit.snippet.strip()
        and hit.source_url.startswith(("https://", "http://", "user-document://"))
    ]


def _result_payload(hit: RetrievalHit) -> dict:
    return {
        "title": hit.title,
        "snippet": hit.snippet[:240],
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


def _step(name: str, status: str, summary: str) -> AgentTraceStep:
    return AgentTraceStep(
        name=name,
        status=status,
        summary=summary,
        duration_ms=0,
    )


__all__ = ["KnowledgeQASkill", "KnowledgeQuery"]
