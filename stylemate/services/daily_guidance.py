"""Pure guidance helpers for today's outfit and travel packing flows."""

from dataclasses import dataclass
from math import ceil

from stylemate.agent.tools.location_weather import WeatherResult
from stylemate.domain.models import Garment
from stylemate.rules.guidance import outfit_categories


@dataclass(frozen=True)
class WeatherGuidance:
    headline: str
    detail: str


@dataclass(frozen=True)
class OpenOutfitGuidance:
    top: str
    bottom: str
    shoes: str
    color: str
    avoid: str


@dataclass(frozen=True)
class PackingPlan:
    garments: list[Garment]
    essentials: list[str]
    gaps: list[str]


def weather_guidance(weather: WeatherResult | None) -> WeatherGuidance:
    """Turn current weather into short, deterministic layering advice."""
    if weather is None or not weather.available:
        return WeatherGuidance(
            headline="天气未知，先确认实际温度",
            detail="暂时只提供衣物类别建议，不推定厚薄；出门前再确认降雨、温度和个人体感。",
        )

    temperature = weather.temperature_c
    if temperature is None:
        headline = "根据天气状况灵活叠穿"
        detail = "选择便于增减的外层，并留意出门前后的体感变化。"
    elif temperature >= 30:
        headline = "轻薄透气，减少层次"
        detail = "优先短袖或轻薄上装，搭配透气下装，避免厚重外套。"
    elif temperature >= 24:
        headline = "单层穿着为主"
        detail = "轻薄上装配长裤或半裙即可，空调环境可带一件薄开衫。"
    elif temperature >= 16:
        headline = "一层内搭加轻外套"
        detail = "早晚温差可能明显，选择方便穿脱的风衣或针织开衫。"
    elif temperature >= 8:
        headline = "针织内搭加保暖外层"
        detail = "覆盖颈部和脚踝，通勤时优先防风、方便活动的组合。"
    else:
        headline = "保暖打底加厚外套"
        detail = "采用贴身保暖层、蓄热中层和防风外层，减少皮肤暴露。"

    condition = weather.summary.lower()
    additions: list[str] = []
    if any(token in condition for token in ("雨", "阵雨", "rain")):
        additions.append("选择防泼水鞋履并随身带伞")
    if any(token in condition for token in ("雪", "snow")):
        additions.append("鞋底以防滑为先")
    if any(token in condition for token in ("风", "wind")):
        additions.append("外层优先选择防风材质")
    if additions:
        detail = f"{detail.rstrip('。')}；{'；'.join(additions)}。"
    return WeatherGuidance(headline=headline, detail=detail)


def open_outfit_guidance(weather: WeatherResult | None) -> OpenOutfitGuidance:
    """Provide a useful category-level outfit without relying on inventory."""
    temperature = weather.temperature_c if weather and weather.available else None
    categories = outfit_categories(temperature)
    return OpenOutfitGuidance(
        top=categories.top,
        bottom=categories.bottom,
        shoes=categories.shoes,
        color="白、藏蓝、灰、卡其等低饱和色",
        avoid=categories.avoid,
    )


def build_packing_plan(
    garments: list[Garment],
    recommendation_ids: list[str],
    duration_days: int,
    weather: WeatherResult | None,
) -> PackingPlan:
    """Select a small packing list from owned garments, then expose inventory gaps."""
    duration = max(1, min(duration_days, 30))
    ordered = [
        garment
        for garment in _recommended_first(garments, recommendation_ids)
        if _packing_weather_compatible(garment, weather)
    ]
    targets = {
        "上装": max(1, ceil(duration / 2)),
        "下装": max(1, ceil(duration / 3)),
        "鞋履": 1 if duration <= 4 else 2,
        "外套": 1 if _outerwear_worth_packing(weather) else 0,
    }
    selected: list[Garment] = []
    gaps: list[str] = []
    for category, target in targets.items():
        if target == 0:
            continue
        matches = [item for item in ordered if category in item.category]
        selected.extend(matches[:target])
        if not matches:
            gaps.append(f"衣橱中缺少可用于本次行程的{category}")
        elif len(matches) < target:
            gaps.append(
                f"适合当前天气的{category}数量不足（建议 {target} 件，现有 {len(matches)} 件）"
            )

    essentials = ["贴身衣物", "袜子", "洗漱用品", "充电设备"]
    condition = weather.summary.lower() if weather and weather.available else ""
    temperature = weather.temperature_c if weather and weather.available else None
    if any(token in condition for token in ("雨", "阵雨", "rain")):
        essentials.extend(["折叠伞", "防水收纳袋"])
    if temperature is not None and temperature >= 28:
        essentials.extend(["防晒用品", "便携水杯"])
    if temperature is not None and temperature <= 10:
        essentials.extend(["保暖配件", "润肤用品"])
    if duration >= 4:
        essentials.append("脏衣收纳袋")

    unique_selected = list({item.id: item for item in selected}.values())
    return PackingPlan(
        garments=unique_selected,
        essentials=list(dict.fromkeys(essentials)),
        gaps=gaps,
    )


def _recommended_first(
    garments: list[Garment], recommendation_ids: list[str]
) -> list[Garment]:
    priority = {garment_id: index for index, garment_id in enumerate(recommendation_ids)}
    return sorted(
        garments,
        key=lambda item: (priority.get(item.id, len(priority)), item.created_at, item.id),
    )


def _outerwear_worth_packing(weather: WeatherResult | None) -> bool:
    if weather is None or not weather.available:
        return True
    if weather.temperature_c is not None and weather.temperature_c <= 22:
        return True
    condition = weather.summary.lower()
    return any(token in condition for token in ("雨", "雪", "风", "rain", "snow", "wind"))


def _packing_weather_compatible(
    garment: Garment, weather: WeatherResult | None
) -> bool:
    if weather is None or not weather.available or weather.temperature_c is None:
        return True
    text = f"{garment.name} {garment.material or ''}".lower()
    if weather.temperature_c >= 28 and any(
        token in text
        for token in ("针织", "毛衣", "羊毛", "羊绒", "呢料", "wool", "cashmere")
    ):
        return False
    return not (weather.temperature_c >= 28 and "外套" in garment.category)
