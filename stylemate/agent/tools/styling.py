"""Read-only location, size, and retrieval-backed styling tools."""

from __future__ import annotations

from typing import Any

import requests

from stylemate.agent.middleware import ToolContext
from stylemate.agent.tool_schemas import (
    CareArguments,
    OpenOutfitArguments,
    PurchaseArguments,
    RagSearchArguments,
    SizeArguments,
    TravelArguments,
    WeatherArguments,
)
from stylemate.rag.query_planning import material_clarification
from stylemate.rules.guidance import outfit_categories
from stylemate.skills.knowledge_qa import KnowledgeQASkill, KnowledgeQuery


def get_user_location(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Delegate location lookup exclusively to the configured AmapClient."""
    del arguments
    if context.amap_client is None:
        return {"available": False, "reason": "location_service_unavailable"}
    result = context.amap_client.locate()
    _raise_retryable_amap_result(result)
    return {
        "available": result.available,
        "city": result.city,
        "province": result.province,
        "adcode": result.adcode,
        "reason": result.reason,
    }


def get_weather(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Delegate weather lookup exclusively to the configured AmapClient."""
    city = WeatherArguments.model_validate(arguments).city
    if context.amap_client is None:
        return {"available": False, "reason": "weather_service_unavailable"}
    result = context.amap_client.weather(city)
    _raise_retryable_amap_result(result)
    return {
        "available": result.available,
        "city": result.city,
        "summary": result.summary,
        "temperature_c": result.temperature_c,
        "humidity": result.humidity,
        "reason": result.reason,
    }


def recommend_size(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Return a bounded size reference, never a universal brand-size claim."""
    del context
    values = SizeArguments.model_validate(arguments)
    size = _size_for(values.height_cm, values.weight_kg)
    size = _shift_size(size, values.fit_preference)
    return {
        "recommended_size": size,
        "height_cm": values.height_cm,
        "weight_kg": values.weight_kg,
        "fit_preference": values.fit_preference,
        "reference_note": "尺码建议仅供参考，请以具体品牌的尺码表和试穿感受为准。",
    }


def care_guide(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Find care guidance through RAG and retain each source citation."""
    material = CareArguments.model_validate(arguments).material
    clarification = material_clarification(material)
    if clarification:
        return {"query": material, "answer_status": "needs_clarification", "message": clarification,
                "missing_conditions": ["material_or_care_label"], "results": [], "sources": []}
    return _rag_result(f"{material} 衣物洗护注意事项", context)


def rag_search(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Search the retrieval corpus in the caller's owner/conversation scope."""
    query = RagSearchArguments.model_validate(arguments).query
    return _rag_result(query, context)


def recommend_open_outfit(
    arguments: dict[str, Any], context: ToolContext
) -> dict[str, Any]:
    """Generate explicitly heuristic guidance without unrelated citations."""
    values = OpenOutfitArguments.model_validate(arguments)
    temperature = values.temperature_c
    scene = values.scene or "日常"
    categories = outfit_categories(temperature)
    top, bottom, shoes, avoid = categories.top, categories.bottom, categories.shoes, categories.avoid
    if "通勤" in scene:
        color = "白、藏蓝、灰、卡其等低饱和色"
    elif "约会" in scene:
        color = "米白、浅蓝或低饱和暖色"
    else:
        color = "白、浅蓝、灰绿等清爽配色"
    del context
    missing = ["temperature_c"] if temperature is None else []
    temperature_note = "当前温度未知，以下仅提供类别建议；请补充温度后再判断厚薄。\n" if missing else ""
    return {
        "recommendation": (
            "通用穿搭建议（搭配规则启发，可按个人喜好调整）：\n"
            f"{temperature_note}"
            f"- 上装：{top}\n"
            f"- 下装：{bottom}\n"
            f"- 鞋履：{shoes}\n"
            f"- 配色：{color}\n"
            f"- 注意：避免{avoid}。"
        ),
        "alternatives": [
            "如果不想上传衣物，可按以上类别选择已有同类单品。",
            "出门前结合实际天气、活动量和个人体感调整衣物。",
        ],
        "sources": [],
        "recommendation_basis": "project_heuristic",
        "conditions": {"temperature_c": temperature, "scene": scene,
                       "weather_condition": values.weather_condition},
        "missing_conditions": missing,
        "rule_explanations": ["依据场景选择类别与配色；温度已提供时使用分段搭配规则。"],
    }


def recommend_purchases(
    arguments: dict[str, Any], context: ToolContext
) -> dict[str, Any]:
    """Suggest purchase priorities from season/weather and current category gaps."""
    values = PurchaseArguments.model_validate(arguments)
    temperature = values.temperature_c
    season = values.season or (_season_for_temperature(temperature) if temperature is not None else "")
    owned = context.wardrobe_repository.list_garments(context.owner_id)
    categories = {garment.category for garment in owned}
    if not season:
        return {
            "season": "", "priorities": [], "sources": [],
            "recommendation_basis": "project_heuristic", "temperature_c": temperature,
            "missing_conditions": ["season_or_temperature"],
            "message": "请补充季节或实际温度，再结合已有衣物判断购买缺口。",
        }
    basics = _purchase_basics(season, temperature)
    missing = [item for item in basics if item["category"] not in categories]
    priorities = missing
    return {
        "season": season,
        "priorities": priorities[:4],
        "message": ("按基础品类规则发现的候选缺口（请先核对已有衣物）：" + "、".join(item["item"] for item in priorities[:4])
                    if priorities else "当前基础品类没有明显缺口，无需仅为补齐品类而购买。"),
        "sources": [],
        "recommendation_basis": "project_heuristic",
        "temperature_c": temperature,
        "missing_conditions": [],
        "rule_explanations": ["仅按季节与已有品类检查缺口，不代表必须购买或个性化适配。"],
    }


def travel_packing(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Create a weather- and activity-aware packing list without requiring inventory."""
    values = TravelArguments.model_validate(arguments)
    activities = values.activities or ["城市观光"]
    weather_summary = ""
    if values.weather_condition:
        weather_summary = values.weather_condition
        if values.temperature_c is not None:
            weather_summary += f"，{values.temperature_c:g}°C"
    packing = [
        f"上衣 {min(values.days + 1, 4)} 件（按{weather_summary or '目的地天气'}准备）",
        f"下装 {min(max(2, values.days), 4)} 条",
        "舒适步行鞋 1 双，必要时增加备用鞋",
        "轻薄外套 1 件，应对早晚温差和室内空调",
        "充电器、证件和常用洗护用品",
    ]
    if values.temperature_c is not None and values.temperature_c <= 12:
        packing.extend(["保暖内层 1 件", "围巾或帽子 1 件"])
    elif values.temperature_c is not None and values.temperature_c >= 28:
        packing.extend(["防晒用品", "透气替换上衣 1 件"])
    if any(keyword in (values.weather_condition or "") for keyword in ("雨", "阵雨", "雷")):
        packing.append("轻量雨具或防水收纳袋")
    if any("户外" in activity for activity in activities):
        packing.extend(["防晒用品", "轻量雨具或防水收纳袋"])
    return {
        "destination": values.destination,
        "days": values.days,
        "activities": activities,
        "packing_list": packing,
        "message": f"{values.destination}{values.days}天行程行李清单：",
        "weather_summary": weather_summary,
        "sources": [],
    }


def _season_for_temperature(temperature: float) -> str:
    if temperature >= 28:
        return "夏"
    if temperature <= 12:
        return "冬"
    return "春秋"


def _purchase_basics(season: str, temperature: float | None) -> list[dict[str, str]]:
    if season == "夏" or (temperature is not None and temperature >= 28):
        return [
            {"item": "透气短袖或亚麻衬衫", "category": "上装", "reason": "应对高温并减少闷热"},
            {"item": "轻薄长裤或五分裤", "category": "下装", "reason": "保持活动度和透气性"},
            {"item": "透气运动鞋或凉鞋", "category": "鞋履", "reason": "适合日常步行"},
        ]
    if season == "冬" or (temperature is not None and temperature <= 12):
        return [
            {"item": "保暖内层", "category": "上装", "reason": "提高核心保暖"},
            {"item": "羽绒服或保暖外套", "category": "外套", "reason": "应对低温和风寒"},
            {"item": "防滑短靴", "category": "鞋履", "reason": "兼顾保暖与通勤"},
        ]
    return [
        {"item": "薄外套或风衣", "category": "外套", "reason": "应对昼夜温差"},
        {"item": "长袖衬衫或薄针织", "category": "上装", "reason": "适合分层穿着"},
        {"item": "直筒长裤", "category": "下装", "reason": "覆盖通勤和日常场景"},
    ]


def _raise_retryable_amap_result(result: Any) -> None:
    """Turn safe typed transient failures back into executor-retryable errors."""
    if getattr(result, "available", False):
        return
    reason = getattr(result, "reason", "")
    if reason == "timeout":
        raise requests.Timeout("amap request timed out")
    if reason == "upstream_error":
        raise requests.ConnectionError("amap service unavailable")


def _rag_result(query: str, context: ToolContext) -> dict[str, Any]:
    configured_top_k = getattr(context.settings, "rag_top_k", 4)
    top_k = min(6, max(1, int(configured_top_k)))
    outcome = KnowledgeQASkill(context.retriever).run(
        context.owner_id,
        context.conversation_id,
        KnowledgeQuery(query=query, top_k=top_k),
    )
    return {
        **outcome.data,
        "skill_trace": outcome.trace.model_dump(mode="json"),
    }


def _size_for(height_cm: float, weight_kg: float) -> str:
    rules = [
        (165, 47.5, "S"),
        (170, 57.5, "M"),
        (175, 67.5, "L"),
        (178, 75, "XL"),
        (182, 82.5, "2XL"),
        (185, 90, "3XL"),
        (190, 105, "4XL"),
    ]
    for max_height, max_weight, size in rules:
        if height_cm <= max_height and weight_kg <= max_weight:
            return size
    return "5XL"


def _shift_size(size: str, preference: str) -> str:
    sizes = ["S", "M", "L", "XL", "2XL", "3XL", "4XL", "5XL"]
    index = sizes.index(size)
    if any(word in preference for word in ("宽松", "偏松")):
        index += 1
    elif any(word in preference for word in ("修身", "偏紧")):
        index -= 1
    return sizes[max(0, min(index, len(sizes) - 1))]
