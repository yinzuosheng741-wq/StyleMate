"""Small deterministic outfit-planning workflow."""

import time
from collections.abc import Callable

from stylemate.agent.tools.location_weather import WeatherResult
from stylemate.domain.models import (
    AgentTrace,
    AgentTraceStep,
    OutfitRequest,
    SkillOutcome,
    SkillSpec,
)
from stylemate.repositories.base import WardrobeRepository
from stylemate.rules.outfit_rules import plan_outfits


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
        started = time.perf_counter()
        steps: list[AgentTraceStep] = []
        garments = self.repository.list_garments(owner_id)
        profile = self.repository.get_profile(owner_id)
        request = request.model_copy(
            update={
                "style_preference": request.style_preference
                or profile.get("style_preference")
                or None,
                "color_preference": request.color_preference
                or profile.get("color_preference")
                or None,
                "fit_preference": request.fit_preference
                or profile.get("fit_preference")
                or None,
            }
        )
        steps.append(self._step("load_wardrobe", "success", "Wardrobe loaded"))

        weather_available = True
        weather_note = ""
        if self.weather_loader is not None and request.city:
            try:
                weather = self.weather_loader(request.city)
            except Exception:
                weather_available = False
                steps.append(self._step("weather", "fallback", "Weather unavailable"))
            else:
                weather_available = weather.available
                if weather.available:
                    weather_note = self._weather_note(weather)
                    request = request.model_copy(
                        update={
                            "temperature_c": weather.temperature_c,
                            "weather_condition": weather.summary,
                        }
                    )
                    steps.append(self._step("weather", "success", "Weather checked"))
                else:
                    steps.append(self._step("weather", "fallback", "Weather unavailable"))

        recommendations = plan_outfits(request, garments)
        if weather_note:
            recommendations = [
                recommendation.model_copy(update={"weather_note": weather_note})
                for recommendation in recommendations
            ]
        steps.append(self._step("plan_outfits", "success", "Outfits planned"))
        status = "success" if recommendations and weather_available else "fallback"
        if not recommendations:
            message = "未找到满足当前天气、季节和排除条件的组合；请检查上装与下装或连衣裙，雨雪天还需鞋履，低温时需外套。"
        elif not weather_available:
            message = "天气信息暂不可用，已根据衣柜生成穿搭建议。"
        else:
            message = "已根据你的衣柜生成穿搭建议。"
        return SkillOutcome(
            status=status,
            data={
                "recommendations": [
                    item.model_dump(mode="json") for item in recommendations
                ]
            },
            trace=self._trace(steps, started, status),
            user_message=message,
        )

    @staticmethod
    def _step(name: str, status: str, summary: str) -> AgentTraceStep:
        return AgentTraceStep(name=name, status=status, summary=summary, duration_ms=0)

    @staticmethod
    def _weather_note(weather: WeatherResult) -> str:
        note = weather.summary
        if weather.temperature_c is not None:
            note = f"{note}，{weather.temperature_c:g}°C"
        return note

    @staticmethod
    def _trace(steps: list[AgentTraceStep], started: float, status: str) -> AgentTrace:
        return AgentTrace(
            skill_name="OutfitPlanningSkill",
            steps=steps,
            duration_ms=int((time.perf_counter() - started) * 1000),
            status=status,
        )
