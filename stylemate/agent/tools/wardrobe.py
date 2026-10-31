"""Read-only tools that operate on the caller's wardrobe only."""

from __future__ import annotations

from typing import Any

from stylemate.agent.middleware import ToolContext
from stylemate.agent.tool_schemas import (
    GetGarmentArguments,
    ItemStyleArguments,
    OutfitArguments,
    WardrobeGapArguments,
    WardrobeSearchArguments,
)
from stylemate.domain.models import OutfitRequest
from stylemate.skills.outfit_planning import OutfitPlanningSkill


def search_wardrobe(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Return at most twenty matching records owned by the current caller."""
    filters = WardrobeSearchArguments.model_validate(arguments)
    garments = context.wardrobe_repository.list_garments(context.owner_id)
    matched = [garment for garment in garments if _matches(garment, filters)]
    return {"garments": [_garment_data(garment) for garment in matched[:20]]}


def get_garment(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Read one exact owned item; never expose another owner's records or images."""
    garment_id = GetGarmentArguments.model_validate(arguments).garment_id
    garment = context.wardrobe_repository.get_garment(context.owner_id, garment_id)
    return {"found": True, "garment": _garment_data(garment)} if garment else {"found": False, "message": "未找到这件衣物，请重新选择。"}


def recommend_inventory_outfit(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Use the deterministic planner with inventory from this owner only."""
    values = OutfitArguments.model_validate(arguments)
    request = OutfitRequest(**values.model_dump())
    outcome = OutfitPlanningSkill(context.wardrobe_repository).run(context.owner_id, request)
    return {**outcome.data, "message": outcome.user_message}


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
    return garment.model_dump(mode="json", exclude={"image_ref", "image_hash"})


def _season_basics(season: str) -> list[str]:
    normalized = season.replace("季", "")
    season_specific = {
        "春": ["上装", "下装", "鞋履", "外套"],
        "夏": ["上装", "下装", "鞋履"],
        "秋": ["上装", "下装", "鞋履", "外套"],
        "冬": ["上装", "下装", "鞋履", "外套"],
    }
    return season_specific.get(normalized, ["上装", "下装", "鞋履"])
