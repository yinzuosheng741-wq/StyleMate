"""Small deterministic outfit-planning workflow."""

from collections.abc import Callable

from stylemate.agent.tools.location_weather import WeatherResult
from stylemate.domain.models import (
    OutfitRequest,
    SkillOutcome,
    SkillSpec,
)
from stylemate.repositories.base import WardrobeRepository
from stylemate.rules.outfit_rules import plan_outfits
from stylemate.skills.runtime import SkillRun


class OutfitPlanningSkill:
    spec = SkillSpec(
        name="outfit_planning",
        description="根据当前用户衣橱、天气和显式约束生成确定性穿搭。",
        input_model=OutfitRequest,
        output_model=SkillOutcome,
        allowed_tools=("load_wardrobe", "weather", "plan_outfits"),
        max_steps=3,
        fallback_strategy="天气不可用时保留库存约束推荐；库存不完整时返回缺口。",
    )

    def __init__(
        self,
        repository: WardrobeRepository,
        weather_loader: Callable[[str], WeatherResult] | None = None,
    ):
        self.repository = repository
        self.weather_loader = weather_loader

    def run(self, owner_id: str, request: OutfitRequest) -> SkillOutcome:
        run = SkillRun(self.spec, request, trace_name="OutfitPlanningSkill")
        request = run.request
        with run.step("load_wardrobe"):
            garments = self.repository.list_garments(owner_id)
            profile = self.repository.get_profile(owner_id)
            request = request.model_copy(update={
                key: getattr(request, key) or profile.get(key) or None
                for key in ("style_preference", "color_preference", "fit_preference")
            })
            owned_ids = {garment.id for garment in garments}
            candidate_ids = [key for key in request.candidate_garment_ids if key in owned_ids]
        if request.candidate_garment_ids and not candidate_ids:
            return run.finish(status="fallback", data={"recommendations": []},
                              message="指定的候选衣物当前不可用，请重新选择衣橱中的单品；本次未扩大候选范围。")
        request = request.model_copy(update={"candidate_garment_ids": candidate_ids})

        weather_available = True
        weather_note = ""
        # Explicit weather already supplied by the caller wins. The agent tool
        # uses no loader: weather remains an explicit, separately budgeted tool.
        if self.weather_loader is not None and request.city and request.temperature_c is None and not request.weather_condition:
            with run.step("weather") as step:
                try:
                    weather = self.weather_loader(request.city)
                except Exception:
                    weather_available = False
                else:
                    weather_available = weather.available
                    if weather.available:
                        weather_note = self._weather_note(weather)
                        request = request.model_copy(update={
                            "temperature_c": weather.temperature_c,
                            "weather_condition": weather.summary,
                        })
                if not weather_available:
                    step.status = "fallback"

        with run.step("plan_outfits"):
            recommendations = plan_outfits(request, garments, limit=3)
            if weather_note:
                recommendations = [item.model_copy(update={"weather_note": weather_note}) for item in recommendations]
        status = "success" if recommendations and weather_available else "fallback"
        if not recommendations:
            message = "未找到满足当前天气、季节和排除条件的组合；请检查上装与下装或连衣裙，雨雪天还需鞋履，低温时需外套。"
        elif not weather_available:
            message = "天气信息暂不可用，已根据衣柜生成穿搭建议。"
        else:
            message = "已根据你的衣柜生成穿搭建议。"
        return run.finish(
            status=status,
            data={"recommendations": [item.model_dump(mode="json") for item in recommendations]},
            message=message,
        )

    @staticmethod
    def _weather_note(weather: WeatherResult) -> str:
        note = weather.summary
        if weather.temperature_c is not None:
            note = f"{note}，{weather.temperature_c:g}°C"
        return note
