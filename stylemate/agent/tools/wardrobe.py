"""Read-only tools that operate on the caller's wardrobe only."""

from __future__ import annotations

from typing import Any

from stylemate.agent.middleware import ToolContext
from stylemate.agent.tool_schemas import (
    ItemStyleArguments,
    OutfitArguments,
    WardrobeGapArguments,
    WardrobeSearchArguments,
)
from stylemate.domain.models import OutfitRequest
from stylemate.rules.outfit_rules import plan_outfits


def search_wardrobe(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Return at most twenty matching records owned by the current caller."""
    filters = WardrobeSearchArguments.model_validate(arguments)
    garments = context.wardrobe_repository.list_garments(context.owner_id)
    matched = [garment for garment in garments if _matches(garment, filters)]
    return {"garments": [_garment_data(garment) for garment in matched[:20]]}


def recommend_inventory_outfit(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Use the deterministic planner with inventory from this owner only."""
    values = OutfitArguments.model_validate(arguments)
    garments = context.wardrobe_repository.list_garments(context.owner_id)
    profile = context.wardrobe_repository.get_profile(context.owner_id)
    owned_ids = {garment.id for garment in garments}
    candidate_ids = [
        garment_id
        for garment_id in values.candidate_garment_ids
        if garment_id in owned_ids
    ]
    if values.candidate_garment_ids and not candidate_ids:
        return {"recommendations": [], "message": "指定的候选衣物当前不可用，请重新选择衣橱中的单品；本次未扩大候选范围。"}
    request = OutfitRequest(
        scene=values.scene,
        target_date=values.target_date,
        city=values.city,
        target_season=values.target_season,
        temperature_c=values.temperature_c,
        weather_condition=values.weather_condition,
        style_preference=values.style_preference
        or profile.get("style_preference")
        or None,
        color_preference=values.color_preference
        or profile.get("color_preference")
        or None,
        fit_preference=values.fit_preference
        or profile.get("fit_preference")
        or None,
        extra_constraints=values.extra_constraints,
        candidate_garment_ids=candidate_ids,
    )
    recommendations = plan_outfits(request, garments, limit=3)
    return {
        "recommendations": [
            recommendation.model_dump(mode="json") for recommendation in recommendations[:3]
        ]
    }


def wardrobe_gap_check(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Identify category gaps from actual owned wardrobe records."""
    season = WardrobeGapArguments.model_validate(arguments).season.strip()
    garments = context.wardrobe_repository.list_garments(context.owner_id)
    categories = sorted({garment.category for garment in garments})
    styles = sorted({style for garment in garments for style in garment.styles})
    needed = _season_basics(season)
    missing = [
        category for category in needed if not any(category in owned for owned in categories)
    ]
    return {
        "season": season or "通用",
        "owned_categories": categories,
        "owned_styles": styles,
        "missing_categories": missing,
        "suggestions": [f"可考虑补充{category}" for category in missing],
    }


def item_style_analysis(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Describe one owned garment using its stored, grounded labels."""
    garment_id = ItemStyleArguments.model_validate(arguments).garment_id
    garment = context.wardrobe_repository.get_garment(context.owner_id, garment_id)
    if garment is None:
        return {"found": False, "message": "未在您的衣橱中找到该衣物。"}
    return {
        "found": True,
        "garment_id": garment.id,
        "name": garment.name,
        "category": garment.category,
        "styles": garment.styles,
        "seasons": garment.seasons,
        "primary_color": garment.primary_color,
        "analysis": f"这件{garment.category}的已记录风格为：{'、'.join(garment.styles)}。",
    }


def _matches(garment: Any, filters: WardrobeSearchArguments) -> bool:
    checks = (
        (filters.name, garment.name),
        (filters.category, garment.category),
        (filters.color, garment.primary_color),
    )
    if any(expected and expected.casefold() not in actual.casefold() for expected, actual in checks):
        return False
    if filters.season and not any(
        filters.season.casefold() in season.casefold() for season in garment.seasons
    ):
        return False
    return not filters.style or any(
        filters.style.casefold() in style.casefold() for style in garment.styles
    )


def _garment_data(garment: Any) -> dict[str, Any]:
    return garment.model_dump(mode="json", exclude={"image_ref"})


def _season_basics(season: str) -> list[str]:
    normalized = season.replace("季", "")
    season_specific = {
        "春": ["上装", "下装", "鞋履", "外套"],
        "夏": ["上装", "下装", "鞋履"],
        "秋": ["上装", "下装", "鞋履", "外套"],
        "冬": ["上装", "下装", "鞋履", "外套"],
    }
    return season_specific.get(normalized, ["上装", "下装", "鞋履"])
