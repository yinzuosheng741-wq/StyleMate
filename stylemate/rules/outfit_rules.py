"""Inventory-grounded outfit recommendation with explicit constraints and scoring."""

from __future__ import annotations

import hashlib
import logging
from datetime import date
from itertools import product

from stylemate.domain.models import Garment, OutfitRecommendation, OutfitRequest
from stylemate.rules.constraints import excludes_color

logger = logging.getLogger(__name__)

_SCENE_STYLES = {
    "面试": {"通勤", "正式", "简约", "优雅"},
    "通勤": {"通勤", "正式", "简约"},
    "约会": {"温柔", "优雅", "简约"},
    "在家": {"休闲", "简约", "舒适"},
    "运动": {"运动", "休闲", "简约"},
    "聚会": {"优雅", "休闲", "简约"},
    "户外": {"运动", "休闲", "简约"},
    "旅行": {"休闲", "简约", "运动"},
    "出游": {"休闲", "简约", "运动"},
    "周末": {"休闲", "简约"},
    "日常": {"休闲", "简约", "通勤"},
}
_SEASON_ALIASES = {
    "spring": "春",
    "summer": "夏",
    "autumn": "秋",
    "fall": "秋",
    "winter": "冬",
    "春季": "春",
    "夏季": "夏",
    "秋季": "秋",
    "冬季": "冬",
}
_NEUTRAL_COLORS = (
    "黑",
    "白",
    "灰",
    "米",
    "奶油",
    "卡其",
    "棕",
    "驼",
    "navy",
    "black",
    "white",
    "gray",
    "grey",
    "beige",
)


def plan_outfits(
    request: OutfitRequest,
    garments: list[Garment],
    limit: int = 3,
) -> list[OutfitRecommendation]:
    """Filter hard constraints, score soft preferences, and return diverse outfits."""
    if limit <= 0:
        return []
    limit = min(limit, 3)

    allowed_ids = set(request.candidate_garment_ids)
    target_season = _target_season(request)
    inventory = sorted(
        (
            garment
            for garment in garments
            if (not allowed_ids or garment.id in allowed_ids)
            and not _excluded(garment, request.extra_constraints)
            and (not target_season or _supports_season(garment, target_season))
            and not (request.temperature_c is not None and request.temperature_c >= 28
                     and any(token in f"{garment.name} {garment.material or ''}".lower()
                             for token in ("针织", "毛衣", "羊毛", "羊绒", "呢料", "wool", "cashmere")))
        ),
        key=lambda garment: garment.id,
    )
    tops = [garment for garment in inventory if _matches_category(garment, "上装")]
    bottoms = [garment for garment in inventory if _matches_category(garment, "下装")]
    shoes = [garment for garment in inventory if _matches_category(garment, "鞋履")]
    outerwear = [garment for garment in inventory if _matches_category(garment, "外套")]
    dresses = [garment for garment in inventory if _matches_category(garment, "连衣裙")]
    if (not tops or not bottoms) and not dresses:
        return []

    # Equivalent accessory candidates have identical hard/soft rule outcomes;
    # the smallest ID always wins the existing deterministic tie-breaker.
    shoes = _equivalent_options(shoes, request)
    outerwear = _equivalent_options(outerwear, request)
    shoe_options: list[Garment | None] = shoes or [None]
    outerwear_options: list[Garment | None] = [None, *outerwear]
    if _needs_outerwear(request):
        outerwear_options = outerwear
    elif request.temperature_c is not None and request.temperature_c >= 28:
        outerwear_options = [None]
    # A dress is an alternative complete base, never an extra top/bottom layer.
    bases = [list(pair) for pair in product(tops, bottoms)] + [[dress] for dress in dresses]
    best_by_core_pair: dict[tuple[str, ...], OutfitRecommendation] = {}
    logger.info("outfit_planning_started inventory=%d bases=%d", len(inventory), len(bases))
    for base, shoe, outer in product(bases, shoe_options, outerwear_options):
        selected = [*base, *(item for item in (shoe, outer) if item is not None)]
        if len({item.id for item in selected}) != len(selected):
            continue
        checks = _hard_constraint_checks(request, selected, allowed_ids)
        if not all(checks.values()):
            continue
        breakdown = _score_breakdown(request, selected, shoe, outer)
        score = min(100, sum(breakdown.values()))
        garment_ids = [item.id for item in selected]
        core_pair = tuple(item.id for item in base)
        current = best_by_core_pair.get(core_pair)
        # Construct and explain only a better candidate for this base outfit.
        if current is not None and (-score, tuple(sorted(garment_ids))) >= _recommendation_sort_key(current):
            continue
        recommendation = OutfitRecommendation(
            id=_recommendation_id(request.scene, garment_ids),
            garment_ids=garment_ids,
            score=score,
            reason=_reason(request, selected),
            constraint_checks=checks,
            score_breakdown=breakdown,
        )
        best_by_core_pair[core_pair] = recommendation

    ranked = sorted(best_by_core_pair.values(), key=_recommendation_sort_key)
    logger.info("outfit_planning_finished valid_bases=%d selected=%d", len(ranked), min(limit, len(ranked)))
    return ranked[:limit]


def _hard_constraint_checks(
    request: OutfitRequest,
    selected: list[Garment],
    allowed_ids: set[str],
) -> dict[str, bool]:
    ids = {item.id for item in selected}
    target_season = _target_season(request)
    return {
        "inventory": not allowed_ids or ids <= allowed_ids,
        "top_bottom": (_has_category(selected, "上装") and _has_category(selected, "下装"))
        or _has_category(selected, "连衣裙"),
        "season": not target_season
        or all(_supports_season(item, target_season) for item in selected),
        "weather": _weather_compatible(request, selected),
        "exclusions": not any(
            _excluded(item, request.extra_constraints) for item in selected
        ),
    }


def _equivalent_options(garments: list[Garment], request: OutfitRequest) -> list[Garment]:
    representatives: dict[tuple, Garment] = {}
    for garment in sorted(garments, key=lambda item: item.id):
        # Ambiguous multi-role categories retain their identity for uniqueness checks.
        identity = "" if garment.category in {"鞋履", "外套"} else garment.id
        key = (garment.category, _color_family(garment.primary_color), tuple(sorted(garment.styles)),
               bool(request.color_preference and request.color_preference in garment.primary_color), identity)
        representatives.setdefault(key, garment)
    return list(representatives.values())


def _score_breakdown(
    request: OutfitRequest,
    selected: list[Garment],
    shoe: Garment | None,
    outer: Garment | None,
) -> dict[str, int]:
    styles = {style for item in selected for style in item.styles}
    scene_styles = _SCENE_STYLES.get(request.scene, {request.scene})
    scene_match = bool(styles & scene_styles)
    style_match = bool(
        request.style_preference
        and any(request.style_preference in style for style in styles)
    )
    color_match = bool(
        request.color_preference
        and any(request.color_preference in item.primary_color for item in selected)
    )
    fit_match = bool(
        request.fit_preference
        and any(request.fit_preference in style for style in styles)
    )
    target_season = _target_season(request)
    condition = (request.weather_condition or "").lower()
    weather_bonus = 5 if request.temperature_c is not None or any(
        word in condition for word in ("雨", "雪", "rain", "snow")
    ) else 0
    return {
        "base": 35,
        "completeness": 10 if shoe is not None else 5,
        "scene": 15 if scene_match else 0,
        "style": 10 if style_match else 0,
        "color_harmony": 10 if _colors_are_harmonious(selected) else 0,
        "color_preference": 5 if color_match else 0,
        "fit_preference": 5 if fit_match else 0,
        "season": 5 if target_season else 0,
        "weather": weather_bonus
        + (5 if outer is not None and _needs_outerwear(request) else 0),
    }


def _reason(request: OutfitRequest, selected: list[Garment]) -> str:
    reasons = [f"符合{request.scene}场景"]
    styles = {style for item in selected for style in item.styles}
    if request.style_preference and any(
        request.style_preference in style for style in styles
    ):
        reasons.append(f"匹配{request.style_preference}风格")
    if request.color_preference and any(
        request.color_preference in item.primary_color for item in selected
    ):
        reasons.append(f"包含偏好的{request.color_preference}")
    if _colors_are_harmonious(selected):
        reasons.append("整体颜色数量克制")
    target_season = _target_season(request)
    if target_season:
        reasons.append(f"衣物均适合{target_season}季")
    if request.temperature_c is not None:
        reasons.append(f"已按{request.temperature_c:g}°C校验层次")
    return "；".join(reasons) + "。"


def _target_season(request: OutfitRequest) -> str:
    if request.target_season:
        return _normalize_season(request.target_season)
    if not request.target_date:
        return ""
    try:
        month = date.fromisoformat(request.target_date).month
    except ValueError:
        return ""
    if month in {3, 4, 5}:
        return "春"
    if month in {6, 7, 8}:
        return "夏"
    if month in {9, 10, 11}:
        return "秋"
    return "冬"


def _supports_season(garment: Garment, target_season: str) -> bool:
    seasons = {_normalize_season(season) for season in garment.seasons}
    return target_season in seasons or bool(seasons & {"四季", "全年"})


def _weather_compatible(request: OutfitRequest, selected: list[Garment]) -> bool:
    temperature = request.temperature_c
    has_outerwear = _has_category(selected, "外套")
    has_shoes = _has_category(selected, "鞋履")
    garment_text = " ".join(
        f"{item.name} {item.material or ''}" for item in selected
    ).lower()
    if temperature is not None and temperature <= 15 and not has_outerwear:
        return False
    if temperature is not None and temperature >= 28 and has_outerwear:
        return False
    if temperature is not None and temperature >= 28 and any(
        token in garment_text
        for token in ("针织", "毛衣", "羊毛", "羊绒", "呢料", "wool", "cashmere")
    ):
        return False
    condition = (request.weather_condition or "").lower()
    if any(word in condition for word in ("雨", "雪", "rain", "snow")) and not has_shoes:
        return False
    return True


def _needs_outerwear(request: OutfitRequest) -> bool:
    return request.temperature_c is not None and request.temperature_c <= 15


def _excluded(garment: Garment, constraints: list[str]) -> bool:
    if excludes_color(garment.primary_color, garment.category, constraints):
        return True
    text = (
        f"{garment.name} {garment.category} {garment.primary_color} "
        f"{' '.join(garment.styles)}"
    )
    if any(constraint in {"不穿裙子", "不要裙子"} for constraint in constraints):
        if "裙" in text:
            return True
    if any(constraint in {"不穿高跟鞋", "不要高跟鞋"} for constraint in constraints):
        if "高跟" in text:
            return True
    return False


def _colors_are_harmonious(selected: list[Garment]) -> bool:
    chromatic = {
        _color_family(item.primary_color)
        for item in selected
        if _color_family(item.primary_color) != "neutral"
    }
    return len(chromatic) <= 2


def _color_family(color: str) -> str:
    normalized = color.lower()
    if any(token in normalized for token in _NEUTRAL_COLORS):
        return "neutral"
    for family, tokens in {
        "red": ("红", "粉", "紫", "red", "pink", "purple"),
        "blue": ("蓝", "青", "blue", "cyan"),
        "green": ("绿", "green"),
        "yellow": ("黄", "橙", "yellow", "orange"),
    }.items():
        if any(token in normalized for token in tokens):
            return family
    return normalized


def _normalize_season(season: str) -> str:
    normalized = season.strip().lower()
    return _SEASON_ALIASES.get(normalized, season.strip().replace("季", ""))


def _has_category(garments: list[Garment], label: str) -> bool:
    return any(_matches_category(garment, label) for garment in garments)


def _matches_category(garment: Garment, label: str) -> bool:
    return label in garment.category


def _recommendation_sort_key(recommendation: OutfitRecommendation) -> tuple:
    return (-recommendation.score, tuple(sorted(recommendation.garment_ids)))


def _recommendation_id(scene: str, garment_ids: list[str]) -> str:
    payload = "|".join([scene, *sorted(garment_ids)])
    return "outfit-" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
