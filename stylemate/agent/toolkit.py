"""Owner- and conversation-bound LangChain tools with strict argument schemas."""

from __future__ import annotations

import json
from dataclasses import dataclass
from time import monotonic
from typing import Any, Callable

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel

from stylemate.agent.middleware import ToolContext, ToolExecutor
from stylemate.agent.policy import denied_tool_payload, record_outfits
from stylemate.agent.tool_schemas import (
    READ_TOOL_SCHEMAS,
    WRITE_TOOL_SCHEMAS,
    plain_arguments,
)
from stylemate.agent.tools import styling
from stylemate.agent.tools import wardrobe as wardrobe_tools
from stylemate.agent.tools.write_actions import ActionPreparationError
from stylemate.agent.write_toolkit import WriteActionToolkit, build_write_action_toolkit
from stylemate.domain.models import AgentTraceStep, ToolSpec

_TOOL_DESCRIPTIONS = {
    "get_user_location": "获取当前用户所在城市；没有城市参数。",
    "get_weather": "查询指定城市的实时天气；城市为空时尝试定位。",
    "recommend_size": "根据身高、体重和版型偏好给出参考尺码。",
    "care_guide": "按衣物材质检索有来源引用的洗护知识。",
    "rag_search": "检索内置知识库和当前会话上传的文档。",
    "recommend_open_outfit": "不依赖用户衣橱，先根据天气、季节和场景生成通用穿搭建议。",
    "recommend_purchases": "根据季节、天气和当前衣橱缺口给出购买优先级。",
    "travel_packing": "根据目的地、天数和活动场景生成旅行穿搭与行李清单。",
    "search_wardrobe": "按名称、品类、颜色、季节或风格查询当前用户衣橱；用户明确给出的筛选条件必须逐项传入，不得改为空参数。",
    "recommend_inventory_outfit": "只使用当前用户真实库存，按场景、天气和偏好生成穿搭。",
    "wardrobe_gap_check": "检查当前用户衣橱在指定季节缺少的基础品类。",
    "item_style_analysis": "根据准确衣物编号分析当前用户的一件衣物。",
    "add_garment": "准备手工新增衣物操作；只生成预览，必须等待用户确认。",
    "update_garment": "准备修改指定衣物操作；只生成预览，必须等待用户确认。",
    "delete_garment": "准备删除指定衣物操作；只生成预览，必须等待用户确认。",
}


@dataclass
class AgentToolkit:
    tools: list[BaseTool]
    wardrobe: Any
    context: ToolContext


def build_toolkit(
    *,
    owner_id: str,
    conversation_id: str,
    app_mode: str,
    wardrobe_repository,
    agent_repository,
    wardrobe_service,
    retriever=None,
    weather_client=None,
    settings=None,
) -> AgentToolkit:
    """Build closures for exactly one caller; no global identity is retained."""
    context = ToolContext(
        owner_id,
        app_mode,
        wardrobe_repository,
        retriever,
        weather_client,
        settings,
        conversation_id,
    )
    executor = ToolExecutor()
    writes = build_write_action_toolkit(
        owner_id=owner_id,
        conversation_id=conversation_id,
        agent_repository=agent_repository,
        wardrobe_repository=wardrobe_repository,
        wardrobe_service=wardrobe_service,
    )
    read_handlers: dict[str, tuple[Callable, bool, bool]] = {
        "get_user_location": (styling.get_user_location, True, False),
        "get_weather": (styling.get_weather, True, False),
        "recommend_size": (styling.recommend_size, False, False),
        "care_guide": (styling.care_guide, False, False),
        "rag_search": (styling.rag_search, False, False),
        "recommend_open_outfit": (styling.recommend_open_outfit, False, False),
        "recommend_purchases": (styling.recommend_purchases, False, False),
        "travel_packing": (styling.travel_packing, False, False),
        "search_wardrobe": (wardrobe_tools.search_wardrobe, False, False),
        "recommend_inventory_outfit": (
            wardrobe_tools.recommend_inventory_outfit,
            False,
            True,
        ),
        "wardrobe_gap_check": (wardrobe_tools.wardrobe_gap_check, False, False),
        "item_style_analysis": (wardrobe_tools.item_style_analysis, False, False),
    }
    tools = [
        _read_tool(
            name,
            handler,
            READ_TOOL_SCHEMAS[name],
            retry,
            validate,
            executor,
            context,
        )
        for name, (handler, retry, validate) in read_handlers.items()
    ]
    tools.extend(_write_tools(writes))
    return AgentToolkit(tools=tools, wardrobe=wardrobe_repository, context=context)


def _read_tool(
    name: str,
    handler: Callable,
    arguments_model: type[BaseModel],
    retry_once: bool,
    validates_inventory: bool,
    executor: ToolExecutor,
    context: ToolContext,
) -> BaseTool:
    def call(**arguments: Any) -> str:
        denied = denied_tool_payload(name, context.owner_id, context.conversation_id)
        if denied:
            return denied
        safe_arguments = plain_arguments(arguments)
        result = executor.execute(
            ToolSpec(
                name=name,
                permission="read",
                timeout_seconds=getattr(context.settings, "tool_timeout_seconds", 5),
                retry_once=retry_once,
                validates_inventory_ids=validates_inventory,
                arguments_model=arguments_model,
            ),
            safe_arguments,
            context,
            handler,
        )
        if name == "recommend_inventory_outfit" and result.status != "failed" and isinstance(result.data, dict):
            record_outfits(context.owner_id, context.conversation_id, result.data, context.wardrobe_repository)
        payload = {
            "result": result.data,
            "trace": result.trace.model_dump(mode="json"),
            "sources": (result.data or {}).get("sources", [])
            if isinstance(result.data, dict)
            else [],
        }
        return json.dumps(
            payload, ensure_ascii=False, default=str, separators=(",", ":")
        )

    call.__name__ = name
    call.__doc__ = _TOOL_DESCRIPTIONS[name]
    return StructuredTool.from_function(
        call,
        name=name,
        description=call.__doc__,
        args_schema=arguments_model,
    )


def _write_tools(writes: WriteActionToolkit) -> list[BaseTool]:
    operations: dict[str, Callable[[dict[str, Any]], Any]] = {
        "add_garment": lambda args: writes.prepare_add_garment(args["metadata"]),
        "update_garment": lambda args: writes.prepare_update_garment(
            args["garment_id"], args["changes"]
        ),
        "delete_garment": lambda args: writes.prepare_delete_garment(
            args["garment_id"]
        ),
    }

    def prepared(
        name: str,
        operation: Callable[[dict[str, Any]], Any],
        arguments_model: type[BaseModel],
    ) -> BaseTool:
        def call(**arguments: Any) -> str:
            denied = denied_tool_payload(name, writes.owner_id, writes.conversation_id)
            if denied:
                return denied
            started = monotonic()
            try:
                action = operation(plain_arguments(arguments))
                payload: dict[str, Any] = {
                    "pending_action": action.model_dump(mode="json"),
                    "result": {"operation": action.operation, "action_id": action.id},
                }
                status, summary = (
                    "success",
                    f"已准备{action.operation}操作，等待用户确认。",
                )
            except (ActionPreparationError, TypeError, ValueError, KeyError) as exc:
                payload = {
                    "result": {"message": "无法准备衣橱修改，请检查衣物编号和字段。"}
                }
                status, summary = "failed", type(exc).__name__
            payload["trace"] = AgentTraceStep(
                name=name,
                status=status,
                summary=summary,
                duration_ms=max(0, round((monotonic() - started) * 1000)),
            ).model_dump(mode="json")
            return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

        call.__name__ = name
        call.__doc__ = _TOOL_DESCRIPTIONS[name]
        return StructuredTool.from_function(
            call,
            name=name,
            description=call.__doc__,
            args_schema=arguments_model,
        )

    return [
        prepared(name, operation, WRITE_TOOL_SCHEMAS[name])
        for name, operation in operations.items()
    ]


__all__ = [
    "AgentToolkit",
    "WriteActionToolkit",
    "build_toolkit",
    "build_write_action_toolkit",
]
