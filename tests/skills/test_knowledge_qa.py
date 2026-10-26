from stylemate.rag.models import RetrievalHit
from stylemate.skills.knowledge_qa import KnowledgeQASkill, KnowledgeQuery
from stylemate.skills.outfit_planning import OutfitPlanningSkill
from stylemate.skills.wardrobe_onboarding import WardrobeOnboardingSkill


def hit(*, source_url: str = "https://example.test/care") -> RetrievalHit:
    return RetrievalHit(
        title="功能外套护理",
        snippet="避免使用柔顺剂。",
        source_name="Care Guide",
        source_url=source_url,
        topic="care",
        score=0.9,
        record_id="care-shell-liquid-detergent",
    )


class SequenceRetriever:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def search(self, query, owner_id, conversation_id, top_k=4):
        self.calls.append((query, owner_id, conversation_id, top_k))
        return self.responses.pop(0)


def test_knowledge_skill_returns_cited_result_without_rewrite():
    retriever = SequenceRetriever([[hit()]])

    outcome = KnowledgeQASkill(retriever).run(
        "owner-a",
        "thread-a",
        KnowledgeQuery(query="GORE-TEX 能用柔顺剂吗"),
    )

    assert outcome.status == "success"
    assert outcome.data["attempts"] == 1
    assert outcome.data["query_rewritten"] is False
    assert outcome.data["sources"][0]["url"].startswith("https://")
    assert len(retriever.calls) == 1


def test_knowledge_skill_rewrites_once_after_empty_retrieval():
    retriever = SequenceRetriever([[], [hit()]])

    outcome = KnowledgeQASkill(retriever).run(
        "owner-a",
        "thread-a",
        KnowledgeQuery(query="冲锋衣防泼水变差怎么办"),
    )

    assert outcome.status == "success"
    assert outcome.data["attempts"] == 2
    assert outcome.data["query_rewritten"] is True
    assert "功能外套" in retriever.calls[1][0]
    assert "GORE-TEX" not in retriever.calls[1][0]
    assert "耐久拒水" in retriever.calls[1][0]
    assert len(outcome.trace.steps) == KnowledgeQASkill.spec.max_steps


def test_knowledge_skill_rejects_uncited_results_and_stops_after_one_retry():
    retriever = SequenceRetriever(
        [[hit(source_url="")], [hit(source_url="")]]
    )

    outcome = KnowledgeQASkill(retriever).run(
        "owner-a", "thread-a", KnowledgeQuery(query="没有来源的回答")
    )

    assert outcome.status == "fallback"
    assert outcome.data["results"] == []
    assert len(retriever.calls) == 2
    assert len(outcome.trace.steps) <= KnowledgeQASkill.spec.max_steps


def test_all_domain_skills_publish_bounded_typed_specs():
    specs = [
        WardrobeOnboardingSkill.spec,
        OutfitPlanningSkill.spec,
        KnowledgeQASkill.spec,
    ]

    assert {spec.name for spec in specs} == {
        "wardrobe_onboarding",
        "outfit_planning",
        "knowledge_qa",
    }
    assert all(spec.input_model.model_fields for spec in specs)
    assert all(spec.output_model.__name__ == "SkillOutcome" for spec in specs)
    assert all(len(spec.allowed_tools) <= spec.max_steps for spec in specs)
