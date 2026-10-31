from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from stylemate.agent.middleware import ToolContext
from stylemate.agent.tools.wardrobe import recommend_inventory_outfit
from stylemate.domain.models import OutfitRequest
from stylemate.skills.outfit_planning import OutfitPlanningSkill
from stylemate.skills.runtime import SkillContractError, SkillRun


def test_budget_and_allowlist_block_before_action_body():
    spec = OutfitPlanningSkill.spec.model_copy(update={"max_steps": 1})
    run = SkillRun(spec, OutfitRequest(scene="通勤"), trace_name="test")
    action = Mock()
    with pytest.raises(SkillContractError), run.step("undeclared"):
        action()
    with run.step("load_wardrobe"):
        pass
    with pytest.raises(SkillContractError), run.step("plan_outfits"):
        action()
    action.assert_not_called()
    assert len(run.steps) == 1


def test_input_revalidated_and_trace_does_not_include_exception_content():
    with pytest.raises(ValidationError):
        SkillRun(OutfitPlanningSkill.spec, OutfitRequest.model_construct(scene=""), trace_name="test")
    run = SkillRun(OutfitPlanningSkill.spec, OutfitRequest(scene="通勤"), trace_name="test")
    with pytest.raises(RuntimeError), run.step("load_wardrobe"):
        raise RuntimeError("private-content")
    assert run.steps[0].status == "failed"
    assert "private-content" not in run.steps[0].summary


def test_output_contract_is_validated():
    from pydantic import BaseModel

    class RequiredOutput(BaseModel):
        required_field: str

    spec = OutfitPlanningSkill.spec.model_copy(update={"output_model": RequiredOutput})
    run = SkillRun(spec, OutfitRequest(scene="通勤"), trace_name="test")
    with pytest.raises(ValidationError):
        run.finish(status="success", data={}, message="done")


@pytest.mark.parametrize("candidates", [[], ["foreign-id"], ["g-1", "foreign-id"]])
def test_desktop_skill_and_agent_tool_share_identical_planning(repo, sample_garments, candidates):
    for garment in sample_garments:
        repo.save_garment("owner", garment)
    repo.save_profile("owner", {"style_preference": "通勤", "color_preference": "蓝"})
    request = OutfitRequest(scene="通勤", candidate_garment_ids=candidates)
    outcome = OutfitPlanningSkill(repo).run("owner", request)
    context = ToolContext("owner", "demo", repo, None, None, None)
    result = recommend_inventory_outfit(request.model_dump(exclude_none=True), context)
    def strip(rows):
        return [{k: v for k, v in row.items() if k != "created_at"} for row in rows]
    assert strip(result["recommendations"]) == strip(outcome.data["recommendations"])
    assert result["message"] == outcome.user_message
    if candidates == ["foreign-id"]:
        assert result["recommendations"] == []


def test_explicit_weather_is_not_overwritten_or_fetched_again(repo, sample_garments):
    for garment in sample_garments:
        repo.save_garment("owner", garment)
    loader = Mock(side_effect=AssertionError("must not fetch again"))
    outcome = OutfitPlanningSkill(repo, loader).run(
        "owner", OutfitRequest(scene="通勤", city="杭州", temperature_c=22, weather_condition="晴"),
    )
    loader.assert_not_called()
    assert outcome.data["recommendations"]


def test_actual_outfit_skill_stops_planner_before_exceeding_budget(repo, monkeypatch):
    planner = Mock(side_effect=AssertionError("planner must be blocked"))
    monkeypatch.setattr("stylemate.skills.outfit_planning.plan_outfits", planner)
    skill = OutfitPlanningSkill(repo)
    skill.spec = skill.spec.model_copy(update={"max_steps": 1})
    with pytest.raises(SkillContractError):
        skill.run("owner", OutfitRequest(scene="通勤"))
    planner.assert_not_called()


def test_actual_knowledge_skill_stops_retry_at_budget():
    from stylemate.skills.knowledge_qa import KnowledgeQASkill, KnowledgeQuery

    retriever = Mock()
    retriever.search.return_value = []
    skill = KnowledgeQASkill(retriever)
    skill.spec = skill.spec.model_copy(update={"max_steps": 2})
    with pytest.raises(SkillContractError):
        skill.run("owner", "thread", KnowledgeQuery(query="羊毛洗护"))
    assert retriever.search.call_count == 1


def test_actual_onboarding_skill_stops_vision_at_budget(repo, jpeg_bytes):
    from tests.skills.test_wardrobe_onboarding import make_skill

    vision = Mock()
    skill = make_skill(repo, vision)
    skill.spec = skill.spec.model_copy(update={"max_steps": 2})
    with pytest.raises(SkillContractError):
        skill.run("owner", jpeg_bytes, "image/jpeg", "item.jpg", "")
    vision.analyze.assert_not_called()
    assert repo.list_garments("owner") == []
