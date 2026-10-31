"""Small, defensive execution boundary for the read-only agent tools."""

from __future__ import annotations

import json
import re
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from time import monotonic
from typing import Any, Callable

import requests
from pydantic import BaseModel, ValidationError

from stylemate.agent.execution import READ_TOOL_RUNNER, ToolCapacityExceeded
from stylemate.agent.policy import remaining_request_seconds
from stylemate.agent.telemetry import record_counter
from stylemate.agent.tool_results import business_metadata
from stylemate.domain.models import AgentTraceStep, ToolExecution, ToolSpec
from stylemate.repositories.base import WardrobeRepository


@dataclass(frozen=True)
class ToolContext:
    owner_id: str
    app_mode: str
    wardrobe_repository: WardrobeRepository
    retriever: Any | None
    amap_client: Any | None
    settings: Any | None
    conversation_id: str = ""


ToolHandler = Callable[[dict[str, Any], ToolContext], Any]


class ToolExecutor:
    """Validate, time-bound, and trace a single read tool call."""

    def __init__(self, runner=None):
        self.runner = runner if runner is not None else READ_TOOL_RUNNER

    def execute(self, spec, arguments, context, handler):
        result = self._execute(spec, arguments, context, handler)
        record_counter("tool_successes" if result.status == "success" else "tool_failures")
        record_counter(f"tool_outcome_{result.outcome}")
        return result

    def _execute(
        self,
        spec: ToolSpec,
        arguments: dict[str, Any],
        context: ToolContext,
        handler: ToolHandler,
    ) -> ToolExecution:
        started = monotonic()
        if spec.permission != "read":
            return self._failure(spec.name, started, "衣橱修改必须通过确认流程。", "read_executor_permission_denied")
        try:
            safe_arguments = self._validate_arguments(spec, arguments)
        except (ValidationError, TypeError, ValueError):
            return self._failure(spec.name, started, "输入参数无效，请检查后重试。", "invalid arguments")

        attempts = 2 if spec.retry_once else 1
        for attempt in range(attempts):
            remaining = remaining_request_seconds()
            if remaining is not None and remaining <= 0:
                return self._failure(spec.name, started, "本轮执行时间已用完，请重试。", "request_deadline_exceeded")
            wait_seconds = min(spec.timeout_seconds, remaining) if remaining is not None else spec.timeout_seconds
            try:
                data = self._call_with_timeout(
                    wait_seconds, handler, safe_arguments, context
                )
                remaining = remaining_request_seconds()
                if remaining is not None and remaining <= 0:
                    return self._failure(spec.name, started, "本轮执行时间已用完，请重试。", "request_deadline_exceeded")
                if spec.validates_inventory_ids and not self._owns_returned_garments(data, context):
                    return self._failure(
                        spec.name,
                        started,
                        "推荐结果包含无效衣物，已停止展示。",
                        "inventory ownership validation failed",
                    )
                if spec.result_model is not None:
                    try:
                        spec.result_model.model_validate(data)
                    except (ValidationError, TypeError, ValueError):
                        return self._failure(spec.name, started, "工具返回的数据格式无效，已停止展示。", "invalid_tool_result")
                return ToolExecution(
                    status="success",
                    data=data,
                    user_message="操作已完成。",
                    trace=AgentTraceStep(
                        name=spec.name,
                        status="success",
                        summary=_safe_summary(data),
                        duration_ms=_duration_ms(started),
                    ),
                    **business_metadata(spec.name, data),
                )
            except ToolCapacityExceeded:
                record_counter("capacity_rejections")
                return self._failure(spec.name, started, "后台工具繁忙，请稍后重试。", "tool_capacity_exhausted")
            except FutureTimeout:
                # A waiting timeout cannot kill a running Python thread. Never
                # overlap a retry with that worker or accept its eventual result.
                remaining = remaining_request_seconds()
                if remaining is not None and remaining <= 0:
                    return self._failure(spec.name, started, "本轮执行时间已用完，请重试。", "request_deadline_exceeded")
                return self._failure(spec.name, started, "服务响应超时，请稍后重试。", "tool_wait_timeout")
            except (requests.Timeout, requests.ConnectionError, ConnectionError):
                if attempt + 1 < attempts:
                    continue
                return self._failure(spec.name, started, "服务响应超时，请稍后重试。", "network timeout")
            except Exception as exc:
                return self._failure(
                    spec.name, started, "暂时无法完成请求，请稍后重试。", type(exc).__name__
                )
        return self._failure(spec.name, started, "暂时无法完成请求，请稍后重试。", "tool unavailable")

    @staticmethod
    def _validate_arguments(spec: ToolSpec, arguments: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise TypeError("arguments must be a dictionary")
        if spec.arguments_model is None:
            return dict(arguments)
        validated: BaseModel = spec.arguments_model.model_validate(arguments)
        return validated.model_dump(exclude_none=True)

    def _call_with_timeout(
        self,
        timeout_seconds: float,
        handler: ToolHandler,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> Any:
        def invoke():
            record_counter("tool_attempts")
            return handler(arguments, context)
        future = self.runner.submit(invoke)
        try:
            return future.result(timeout=timeout_seconds)
        finally:
            # Cancel work that has not started. Running reads retain their capacity
            # until the future finishes; timeout never frees a still-running slot.
            future.cancel()

    @staticmethod
    def _owns_returned_garments(data: Any, context: ToolContext) -> bool:
        owned_ids = {
            garment.id
            for garment in context.wardrobe_repository.list_garments(context.owner_id)
        }
        return _returned_garment_ids(data) <= owned_ids

    @staticmethod
    def _failure(name: str, started: float, user_message: str, reason: str) -> ToolExecution:
        return ToolExecution(
            status="failed",
            outcome="error",
            reason_code={"invalid arguments": "invalid_arguments",
                         "inventory ownership validation failed": "inventory_ownership_failed",
                         "network timeout": "network_timeout", "tool unavailable": "tool_unavailable"}.get(reason, reason)
            if reason in {"read_executor_permission_denied", "invalid arguments", "request_deadline_exceeded",
                          "inventory ownership validation failed", "tool_capacity_exhausted", "tool_wait_timeout",
                          "network timeout", "invalid_tool_result", "tool unavailable"} else "tool_exception",
            retryable=reason in {"tool_capacity_exhausted", "tool_wait_timeout", "network timeout"},
            data=None,
            user_message=user_message,
            trace=AgentTraceStep(
                name=name,
                status="failed",
                summary=_safe_summary(reason),
                duration_ms=_duration_ms(started),
            ),
        )


def _returned_garment_ids(value: Any) -> set[str]:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        ids: set[str] = set()
        for key, child in value.items():
            if key == "garment_ids" and isinstance(child, list):
                ids.update(item for item in child if isinstance(item, str))
            elif key == "garment_id" and isinstance(child, str):
                ids.add(child)
            else:
                ids.update(_returned_garment_ids(child))
        return ids
    if isinstance(value, (list, tuple)):
        return set().union(*(_returned_garment_ids(item) for item in value)) if value else set()
    return set()


def _duration_ms(started: float) -> int:
    return max(0, round((monotonic() - started) * 1000))


def _safe_summary(value: Any) -> str:
    try:
        text = (
            value
            if isinstance(value, str)
            else json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
        )
    except (TypeError, ValueError):
        text = type(value).__name__
    text = re.sub(r"(?i)sk-[a-z0-9_-]+", "[redacted-key]", text)
    text = re.sub(r"(?i)(api[_-]?key\s*[=:]\s*)[^\s,&;]+", r"\1[redacted]", text)
    text = re.sub(r"(?i)data:image/[^;\s]+;base64,[a-z0-9+/=]+", "[redacted-image]", text)
    text = re.sub(
        r"(?<![a-z0-9+/=])[a-z0-9+/]{80,}={0,2}(?![a-z0-9+/=])",
        "[redacted-image]",
        text,
    )
    return text[:157] + "..." if len(text) > 160 else text
