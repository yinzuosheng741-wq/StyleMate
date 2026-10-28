"""Conversation persistence and deterministic no-key routing."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from httpx import HTTPError
from langchain_core.messages import AIMessage, HumanMessage
from openai import APIError

from stylemate.agent.graph import build_agent_graph
from stylemate.agent.memory import migrate_legacy_summary, update_conversation_facts
from stylemate.agent.policy import (
    RequestExecutionDenied,
    discard_request_outfits,
    remaining_request_seconds,
)
from stylemate.agent.state import initial_state
from stylemate.agent.toolkit import build_toolkit
from stylemate.agent.tools.write_actions import cancel_action, confirm_action
from stylemate.domain.models import (
    AgentTraceStep,
    ConversationMessage,
    ConversationState,
    KnowledgeSource,
    UserDocument,
)
from stylemate.rag.user_docs import DocumentLimits, extract_user_document
from stylemate.services.profile_service import PROFILE_KEYS, ProfileService

NO_KEY_MESSAGE = "AI 对话需要配置 LLM_API_KEY；当前仍可使用天气、尺码、衣橱和知识库工具。"
MODEL_FALLBACK_MESSAGE = "模型服务当前不可用；仍可使用天气、尺码、衣橱和知识库工具。"
CARE_INTENT_TERMS = (
    "洗",
    "清洁",
    "护理",
    "保养",
    "柔顺剂",
    "漂白",
    "去渍",
    "烘干",
    "晾晒",
    "熨烫",
    "洗标",
    "洗涤剂",
)
KNOWLEDGE_INTENT_TERMS = CARE_INTENT_TERMS + (
    "知识库",
    "羊毛",
    "材质",
    "面料",
    "gore-tex",
    "功能外套",
    "拒水",
    "防水",
    "紫外线",
    "防晒",
    "高温",
    "寒冷",
    "温差",
    "分层",
    "尺码表",
    "色轮",
    "配色",
    "收纳",
    "污渍",
)


def _deadline_result():
    discard_request_outfits()
    return (
        "本轮处理超过时间预算，已停止接受结果。请缩小问题后重试。",
        [AgentTraceStep(name="request_policy", status="failed",
                        summary="request_deadline_exceeded", duration_ms=0)],
        [],
    )


class AgentService:
    def __init__(self, *, settings, agent_repository, wardrobe_repository, wardrobe_service, retriever=None, model=None, weather_client=None):
        self.settings = settings
        self.repository = agent_repository
        self.wardrobe_repository = wardrobe_repository
        self.wardrobe_service = wardrobe_service
        self.retriever = retriever
        self.model = model
        self.weather_client = weather_client
        self.profile_service = ProfileService(wardrobe_repository)

    def chat(self, owner_id: str, conversation_id: str, text: str) -> ConversationMessage:
        from stylemate.agent.policy import request_policy
        from stylemate.agent.routing import route_skills
        from stylemate.agent.tool_schemas import READ_TOOL_SCHEMAS, WRITE_TOOL_SCHEMAS

        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise ValueError("消息不能为空且不能超过 4000 个字符")
        route = route_skills(text, set(READ_TOOL_SCHEMAS) | set(WRITE_TOOL_SCHEMAS))
        with request_policy(owner_id, conversation_id, route.allowed_tools):
            return self._chat(owner_id, conversation_id, text)

    def _chat(self, owner_id: str, conversation_id: str, text: str) -> ConversationMessage:
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise ValueError("消息不能为空且不能超过 4000 个字符")
        state = self.repository.load_conversation(owner_id, conversation_id)
        shortcut = self._shortcut_route(owner_id, conversation_id, text, state=state)
        if shortcut is not None:
            content, traces, sources = shortcut
        elif _is_deterministic_intent(text) or _is_travel_follow_up(state, text):
            content, traces, sources = self._route_without_model(
                owner_id, conversation_id, text, state=state
            )
        elif self.model is None:
            content, traces, sources = self._route_without_model(
                owner_id, conversation_id, text, state=state
            )
        else:
            try:
                toolkit = self._toolkit(owner_id, conversation_id)
                history = [HumanMessage(content=m.content) if m.role == "user" else AIMessage(content=m.content) for m in state.messages]
                result = build_agent_graph(self.model, toolkit.tools).invoke(initial_state(text, owner_id=owner_id, conversation_id=conversation_id, facts=state.facts, summary=state.summary, app_mode=self.settings.app_mode, profile=self.profile_service.get(owner_id), messages=history))
                latest = result["messages"][-1]
                content = str(getattr(latest, "content", "") or "我暂时没有生成回复，请重试。")
                traces = [_trace(item) for item in result.get("traces", [])]
                sources = [_source(item) for item in result.get("sources", []) if _source(item) is not None]
            except (
                RequestExecutionDenied,
                APIError,
                HTTPError,
                TimeoutError,
                ConnectionError,
            ) as exc:
                remaining = remaining_request_seconds()
                if isinstance(exc, RequestExecutionDenied) or (remaining is not None and remaining <= 0):
                    content, traces, sources = _deadline_result()
                else:
                    content, traces, sources = self._route_without_model(
                        owner_id, conversation_id, text, state=state
                    )
                    if content == NO_KEY_MESSAGE:
                        content = MODEL_FALLBACK_MESSAGE
                    traces.insert(
                        0,
                        AgentTraceStep(
                            name="model_fallback",
                            status="fallback",
                            summary="模型服务不可用，已切换确定性路由。",
                            duration_ms=0,
                        ),
                    )
        # Shortcuts and deterministic fallbacks share the same acceptance boundary.
        remaining = remaining_request_seconds()
        if remaining is not None and remaining <= 0:
            content, traces, sources = _deadline_result()
        from stylemate.agent.policy import current_outfits

        reply = ConversationMessage(role="assistant", content=content, traces=traces, sources=sources,
                                    outfits=current_outfits(owner_id, conversation_id))
        self._save_turn(state, text.strip(), reply)
        return reply

    def _shortcut_route(
        self,
        owner_id: str,
        conversation_id: str,
        text: str,
        *,
        state: ConversationState,
    ) -> tuple[str, list[AgentTraceStep], list[KnowledgeSource]] | None:
        """Keep UI presets bounded and useful when a provider loops on tools."""
        normalized = text.strip()
        if normalized not in {
            "根据今天的天气推荐穿搭",
            "天气穿搭",
            "洗护帮助",
            "推荐购买",
            "旅游出行",
        }:
            return None
        if normalized == "旅游出行":
            return (
                "旅行规划需要三个信息：目的地、行程天数和主要活动。"
                "例如：去成都4天，主要城市观光。",
                [],
                [],
            )
        toolkit = self._toolkit(owner_id, conversation_id)
        if normalized in {"根据今天的天气推荐穿搭", "天气穿搭"}:
            weather_payload = self._invoke_named(toolkit, "get_weather", {"city": ""})
            weather = self._present_named("get_weather", weather_payload)
            live_weather = _successful_result(weather_payload)
            outfit_arguments = _outfit_arguments(text)
            if live_weather.get("available"):
                outfit_arguments.update(
                    {
                        "city": live_weather.get("city") or None,
                        "temperature_c": live_weather.get("temperature_c"),
                        "weather_condition": live_weather.get("summary") or None,
                    }
                )
            outfit = self._outfit_route(
                toolkit, owner_id, text, arguments=outfit_arguments
            )
            return (
                f"{weather[0]}\n\n{outfit[0]}",
                [*weather[1], *outfit[1]],
                [*weather[2], *outfit[2]],
            )
        route_name, arguments = {
            "洗护帮助": ("care_guide", {"material": "衣物"}),
            "推荐购买": ("recommend_purchases", {"scene": "日常"}),
        }[normalized]
        return self._call_named(toolkit, route_name, arguments)

    def confirm(self, owner_id: str, conversation_id: str, action_id: str):
        return confirm_action(action_id=action_id, owner_id=owner_id, conversation_id=conversation_id, agent_repository=self.repository, wardrobe_repository=self.wardrobe_repository, wardrobe_service=self.wardrobe_service)

    def cancel(self, owner_id: str, conversation_id: str, action_id: str):
        return cancel_action(action_id=action_id, owner_id=owner_id, conversation_id=conversation_id, agent_repository=self.repository)

    def clear(self, owner_id: str, conversation_id: str) -> None:
        self.repository.clear_conversation(owner_id, conversation_id)
        self.repository.clear_pending(owner_id, conversation_id)
        self.repository.clear_documents(owner_id, conversation_id)
        self._sync_retriever_documents(owner_id, conversation_id)

    def list_conversations(self, owner_id: str) -> list[dict[str, Any]]:
        return self.repository.list_conversations(owner_id)

    def forget_context(self, owner_id: str, conversation_id: str) -> None:
        """Keep the visible archive; reset model context and pending proposals."""
        state = self.repository.load_conversation(owner_id, conversation_id)
        self.repository.save_conversation(ConversationState(
            owner_id=owner_id, conversation_id=conversation_id,
            transcript=state.transcript or state.messages,
        ))
        self.repository.clear_pending(owner_id, conversation_id)

    def forget_profile_field(self, owner_id: str, field: str) -> None:
        if field not in PROFILE_KEYS:
            raise ValueError("unknown_profile_field")
        profile = self.profile_service.get(owner_id)
        profile.pop(field, None)
        self.profile_service.replace(owner_id, profile)

    def propose_profile_updates(self, owner_id: str, text: str) -> dict[str, str]:
        """Extract only explicit, reviewable preferences; never persist them silently."""
        proposed = _explicit_profile_updates(text)
        current = self.profile_service.get(owner_id)
        return {
            key: value
            for key, value in proposed.items()
            if key in PROFILE_KEYS and value and current.get(key) != value
        }

    def confirm_profile_updates(
        self, owner_id: str, updates: dict[str, str]
    ) -> dict[str, str]:
        allowed = {
            key: str(value).strip()
            for key, value in updates.items()
            if key in PROFILE_KEYS and str(value).strip()
        }
        profile = self.profile_service.get(owner_id)
        profile.update(allowed)
        return self.profile_service.replace(owner_id, profile)

    def ingest_document(self, owner_id: str, conversation_id: str, filename: str, mime_type: str, payload: bytes) -> UserDocument:
        extracted = extract_user_document(filename, mime_type, payload, DocumentLimits(self.settings.max_document_bytes, self.settings.max_document_chars))
        document = UserDocument(owner_id=owner_id, conversation_id=conversation_id, document_id=__import__("uuid").uuid4().hex, filename=extracted.filename, mime_type=extracted.mime_type, text=extracted.text, pages=extracted.pages, created_at=datetime.now())
        self.repository.save_document(document)
        self._sync_retriever_documents(owner_id, conversation_id)
        return document

    def list_documents(self, owner_id: str, conversation_id: str) -> list[UserDocument]:
        return self.repository.list_documents(owner_id, conversation_id)

    def delete_document(
        self, owner_id: str, conversation_id: str, document_id: str
    ) -> None:
        self.repository.delete_document(owner_id, conversation_id, document_id)
        self._sync_retriever_documents(owner_id, conversation_id)

    def _sync_retriever_documents(
        self, owner_id: str, conversation_id: str
    ) -> None:
        if self.retriever is None or not hasattr(
            self.retriever, "sync_user_documents"
        ):
            return
        self.retriever.sync_user_documents(
            owner_id,
            conversation_id,
            self.repository.list_documents(owner_id, conversation_id),
        )

    def _toolkit(self, owner_id: str, conversation_id: str):
        return build_toolkit(owner_id=owner_id, conversation_id=conversation_id, app_mode=self.settings.app_mode, wardrobe_repository=self.wardrobe_repository, agent_repository=self.repository, wardrobe_service=self.wardrobe_service, retriever=self.retriever, weather_client=self.weather_client, settings=self.settings)

    def _route_without_model(
        self,
        owner_id: str,
        conversation_id: str,
        text: str,
        *,
        state: ConversationState | None = None,
    ):
        """Route deterministic intents before falling back to the model message."""
        toolkit = self._toolkit(owner_id, conversation_id)
        lower = text.lower()
        if any(term in text for term in ("推荐购买", "买什么", "购买建议")):
            return self._call_named(toolkit, "recommend_purchases", {"scene": "日常"})
        destination = _travel_destination(text)
        continuing_travel = _is_travel_follow_up(state, text) if state else False
        if any(term in text for term in ("旅行行李", "旅游", "旅行", "行李清单")) or continuing_travel:
            if not destination:
                return (
                    "请告诉我旅行目的地、行程天数和主要活动，"
                    "例如：去成都4天，主要城市观光。",
                    [],
                    [],
                )
            return self._travel_route(
                toolkit,
                destination=destination,
                days=_travel_days(text),
                activities=_travel_activities(text),
            )
        if any(word in lower for word in CARE_INTENT_TERMS):
            material = "羊毛" if "羊毛" in text else text[:80]
            return self._call_named(toolkit, "care_guide", {"material": material})
        size = _size_values(text)
        if size:
            return self._call_named(toolkit, "recommend_size", size)
        if any(word in text for word in ("搭配", "穿什么")):
            return self._outfit_route(toolkit, owner_id, text)
        if any(word in text for word in ("天气", "定位", "城市")):
            city = _city(text)
            return self._call_named(toolkit, "get_weather" if "天气" in text else "get_user_location", {"city": city})
        if any(word in lower for word in KNOWLEDGE_INTENT_TERMS):
            material = "羊毛" if "羊毛" in text else text[:80]
            if any(word in lower for word in CARE_INTENT_TERMS):
                return self._call_named(toolkit, "care_guide", {"material": material})
            return self._call_named(toolkit, "rag_search", {"query": text})
        if any(word in text for word in ("缺", "补齐", "补充")):
            return self._call_named(toolkit, "wardrobe_gap_check", {"season": _season(text)})
        if any(word in lower for word in ("删除", "delete")):
            return self._call_named(toolkit, "delete_garment", {"garment_id": _garment_id(text)})
        if any(word in text for word in ("衣橱", "衣柜", "搜索")):
            return self._call_named(
                toolkit, "search_wardrobe", _wardrobe_filters(text)
            )
        if any(word in text for word in ("风格", "分析")):
            return self._call_named(toolkit, "item_style_analysis", {"garment_id": _garment_id(text)})
        return NO_KEY_MESSAGE, [], []

    def _travel_route(
        self,
        toolkit,
        *,
        destination: str,
        days: int,
        activities: list[str],
    ):
        """Check destination weather before producing a bounded packing list."""
        weather_payload = self._invoke_named(toolkit, "get_weather", {"city": destination})
        weather = self._present_named("get_weather", weather_payload)
        weather_result = _successful_result(weather_payload)
        packing_arguments: dict[str, Any] = {
            "destination": destination,
            "days": days,
            "activities": activities,
        }
        if weather_result.get("available"):
            packing_arguments.update(
                {
                    "temperature_c": weather_result.get("temperature_c"),
                    "weather_condition": weather_result.get("summary") or None,
                }
            )
        packing = self._call_named(toolkit, "travel_packing", packing_arguments)
        return (
            f"{weather[0]}\n\n{packing[0]}",
            [*weather[1], *packing[1]],
            [*weather[2], *packing[2]],
        )

    def _outfit_route(
        self,
        toolkit,
        owner_id: str,
        text: str,
        *,
        arguments: dict[str, Any] | None = None,
    ):
        arguments = arguments or _outfit_arguments(text)
        general = self._call_named(toolkit, "recommend_open_outfit", arguments)
        if not self.wardrobe_repository.list_garments(owner_id):
            return general
        inventory = self._call_named(toolkit, "recommend_inventory_outfit", arguments)
        return (
            f"{general[0]}\n\n{inventory[0]}",
            [*general[1], *inventory[1]],
            [*general[2], *inventory[2]],
        )

    def _call_named(self, toolkit, name: str, args: dict[str, Any]):
        return self._present_named(name, self._invoke_named(toolkit, name, args))

    @staticmethod
    def _invoke_named(toolkit, name: str, args: dict[str, Any]) -> dict[str, Any]:
        tool = next(tool for tool in toolkit.tools if tool.name == name)
        try:
            return __import__("json").loads(tool.invoke(args))
        except Exception:
            return {"result": {"message": "工具暂时不可用，请稍后重试。"},
                    "trace": {"name": name, "status": "failed", "summary": "tool invocation failed", "duration_ms": 0}}

    @staticmethod
    def _present_named(name: str, payload: dict[str, Any]):
        result = payload.get("result", {})
        failed = isinstance(payload.get("trace"), dict) and payload["trace"].get("status") == "failed"
        if failed:
            content = (result.get("message") if isinstance(result, dict) else None) or "工具未完成操作，请检查条件后重试。"
        elif name == "recommend_size" and isinstance(result, dict):
            content = f"参考尺码：{result.get('recommended_size', '请提供身高体重')}。{result.get('reference_note', '')}"
        elif name in {"care_guide", "rag_search"} and isinstance(result, dict):
            snippets = result.get("results", [])
            content = (snippets[0].get("snippet", "知识库暂未找到直接答案。") if snippets
                       else result.get("message") or "知识库暂未找到直接答案。")
            if snippets:
                for label, field in (("适用范围", "applicability"), ("限制", "limitations")):
                    if snippets[0].get(field):
                        content += f"\n{label}：{snippets[0][field]}"
        elif name == "recommend_open_outfit" and isinstance(result, dict):
            content = result.get("recommendation", "暂未生成通用穿搭建议。")
            alternatives = result.get("alternatives", [])
            if alternatives:
                content += "\n" + "\n".join(f"- {item}" for item in alternatives)
        elif name == "recommend_purchases" and isinstance(result, dict):
            priorities = result.get("priorities", [])
            lines = [result.get("message", "优先购买：")]
            lines.extend(
                f"- {item.get('item', '')}：{item.get('reason', '')}"
                for item in priorities
            )
            content = "\n".join(lines)
        elif name == "travel_packing" and isinstance(result, dict):
            lines = [result.get("message", "行李清单：")]
            lines.extend(f"- {item}" for item in result.get("packing_list", []))
            content = "\n".join(lines)
        elif name == "get_weather" and isinstance(result, dict):
            temperature = result.get("temperature_c")
            temperature_text = f"{temperature:g}" if isinstance(temperature, (int, float)) else "-"
            content = f"{result.get('city') or '当地'}天气：{result.get('summary') or '暂不可用'}，{temperature_text}°C。"
        elif name == "recommend_inventory_outfit" and isinstance(result, dict):
            recommendations = result.get("recommendations", [])
            if recommendations:
                lines = ["根据你的衣橱，我整理了这几套搭配："]
                for index, item in enumerate(recommendations[:3], start=1):
                    lines.append(
                        f"{index}. 衣物编号：{'、'.join(item.get('garment_ids', []))}；"
                        f"评分 {item.get('score', '-')}；{item.get('reason', '')}"
                    )
                content = "\n".join(lines)
            else:
                content = result.get("message") or "当前衣橱没有满足本次条件的完整搭配。可调整排除条件，或补充适合的上装与下装（或连衣裙）。"
        elif name == "search_wardrobe" and isinstance(result, dict):
            garments = result.get("garments", [])
            content = "\n".join(
                f"- {item.get('name', '未命名')}（ID：{item.get('id', '-')}）"
                for item in garments
            ) or "当前衣橱没有符合条件的衣物。"
        elif name == "wardrobe_gap_check" and isinstance(result, dict):
            suggestions = result.get("suggestions", [])
            content = "；".join(suggestions) if suggestions else "当前基础品类比较完整。"
        elif name in {"add_garment", "update_garment", "delete_garment"}:
            content = ("已生成衣橱变更预览，请在下方确认后执行。" if payload.get("pending_action")
                       else "尚未生成变更预览，请说明具体操作和准确衣物编号。")
        else:
            content = str(result.get("message") if isinstance(result, dict) and result.get("message") else result)
        traces = [_trace(payload["trace"])] if isinstance(payload.get("trace"), dict) else []
        sources = [_source(item) for item in payload.get("sources", []) if _source(item) is not None]
        return content, traces, sources

    def _save_turn(self, state: ConversationState, user_text: str, reply: ConversationMessage) -> None:
        user_message = ConversationMessage(role="user", content=user_text)
        messages = [*state.messages, user_message, reply]
        facts = migrate_legacy_summary(state.facts, state.summary)
        facts = update_conversation_facts(facts, user_message)
        while len(messages) > 8:
            messages.pop(0)
        self.repository.save_conversation(
            ConversationState(
                owner_id=state.owner_id,
                conversation_id=state.conversation_id,
                messages=messages,
                transcript=[*(state.transcript or state.messages), user_message, reply],
                facts=facts,
                summary="",
            )
        )


def _successful_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Only a completed tool result may supply downstream business inputs."""
    if payload.get("trace", {}).get("status") != "success":
        return {}
    result = payload.get("result")
    return result if isinstance(result, dict) else {}


def _trace(value: dict[str, Any]) -> AgentTraceStep:
    return AgentTraceStep.model_validate(value)


def _source(value: dict[str, Any]) -> KnowledgeSource | None:
    try:
        return KnowledgeSource(id=value.get("source_name") or value.get("title") or "source", title=value["title"], url=value.get("url") or value["source_url"])
    except (KeyError, TypeError, ValueError):
        return None


def _size_values(text: str) -> dict[str, Any] | None:
    values = re.findall(r"(\d+(?:\.\d+)?)\s*(cm|厘米|kg|公斤|斤)?", text.lower())
    height = next((float(v) for v, unit in values if unit in {"cm", "厘米"} or 120 <= float(v) <= 230), None)
    weight = next((float(v) for v, unit in values if unit in {"kg", "公斤", "斤"} or 30 <= float(v) <= 120), None)
    if height is None or weight is None:
        return None
    if any(unit == "斤" for _, unit in values):
        weight /= 2
    return {"height_cm": height, "weight_kg": weight, "fit_preference": "宽松" if "宽松" in text else "标准"}


def _city(text: str) -> str:
    match = re.search(r"([\u4e00-\u9fff]{2,8})(?:市)?(?:天气|在哪里|定位)", text)
    return match.group(1).replace("的", "") if match else ""


def _travel_days(text: str) -> int:
    match = re.search(r"(\d{1,2})\s*(?:天|晚)", text)
    return max(1, min(30, int(match.group(1)))) if match else 3


def _travel_destination(text: str) -> str:
    """Extract a destination only from explicit travel phrasing or a short continuation."""
    explicit = re.search(
        r"(?:去|到|前往|目的地(?:是|为)?)\s*([\u4e00-\u9fff]{2,8})(?:市)?",
        text,
    )
    if explicit:
        candidate = explicit.group(1)
        for suffix in ("旅游", "旅行", "出差", "游玩"):
            candidate = candidate.removesuffix(suffix)
        return candidate.removesuffix("市")
    continuation = re.match(r"^\s*([\u4e00-\u9fff]{2,8})(?:市)?(?:[，,\s]|$)", text)
    return continuation.group(1).removesuffix("市") if continuation else ""


def _travel_activities(text: str) -> list[str]:
    activities = [
        activity
        for activity in ("城市观光", "商务出差", "户外活动", "探亲聚会", "约会行程")
        if activity in text
    ]
    return activities or ["城市观光"]


def _is_travel_follow_up(state: ConversationState | None, text: str) -> bool:
    if state is None or "旅行" not in state.facts.scenes:
        return False
    return bool(_travel_destination(text) or re.search(r"\d{1,2}\s*(?:天|晚)", text))


def _is_deterministic_intent(text: str) -> bool:
    return any(
        term in text
        for term in (
            "搭配",
            "穿什么",
            "推荐购买",
            "买什么",
            "购买建议",
            "洗护",
            "洗涤",
            "护理",
            "旅行",
            "旅游",
            "行李",
        )
    )


def _season(text: str) -> str:
    return next((s for s in "春夏秋冬" if s in text), "")


def _garment_id(text: str) -> str:
    match = re.search(
        r"(?:(?:衣物\s*)?(?:id|编号)\s*[:：]?\s*|衣物\s*[:：]\s*)([\w-]+)",
        text,
        re.I,
    )
    return match.group(1) if match else ""


def _outfit_arguments(text: str) -> dict[str, Any]:
    scene_aliases = {"旅游": "旅行"}
    scene = next(
        (
            scene_aliases.get(candidate, candidate)
            for candidate in (
                "面试",
                "通勤",
                "约会",
                "旅行",
                "旅游",
                "运动",
                "聚会",
                "婚礼",
                "日常",
            )
            if candidate in text
        ),
        "日常",
    )
    from stylemate.rules.constraints import extract_color_exclusions

    exclusions = [
        constraint
        for constraint in ("不穿裙子", "不要裙子", "不穿高跟鞋", "不要高跟鞋")
        if constraint in text
    ]
    exclusions.extend(extract_color_exclusions(text))
    arguments: dict[str, Any] = {
        "scene": scene,
        "extra_constraints": exclusions,
    }
    if season := _season(text):
        arguments["target_season"] = season
    if "宽松" in text:
        arguments["fit_preference"] = "宽松"
    elif "修身" in text:
        arguments["fit_preference"] = "修身"
    return arguments


def _wardrobe_filters(text: str) -> dict[str, str]:
    filters: dict[str, str] = {}
    categories = (
        "上装",
        "下装",
        "外套",
        "鞋履",
        "配饰",
        "连衣裙",
    )
    colors = (
        "黑色",
        "白色",
        "灰色",
        "米色",
        "蓝色",
        "浅蓝",
        "深灰",
        "奶油色",
        "红色",
        "绿色",
        "黄色",
        "紫色",
        "棕色",
    )
    styles = ("通勤", "休闲", "简约", "温柔", "优雅", "正式", "运动")
    if category := next((item for item in categories if item in text), None):
        filters["category"] = category
    if color := next((item for item in colors if item in text), None):
        filters["color"] = color
    if season := _season(text):
        filters["season"] = season
    if style := next((item for item in styles if item in text), None):
        filters["style"] = style
    return filters


def _explicit_profile_updates(text: str) -> dict[str, str]:
    """Conservative Chinese preference extraction for the UI confirmation flow."""
    updates: dict[str, str] = {}
    height = re.search(r"(1\d{2}|2[0-2]\d)\s*(?:cm|厘米)", text, re.I)
    weight = re.search(r"(\d{2,3}(?:\.\d+)?)\s*(kg|公斤|斤)", text, re.I)
    if height:
        updates["height"] = f"{height.group(1)}cm"
    if weight:
        value = float(weight.group(1))
        if weight.group(2) == "斤":
            value /= 2
        updates["weight"] = f"{value:g}kg"
    if any(phrase in text for phrase in ("不喜欢紧身", "不要紧身", "喜欢宽松", "偏好宽松")):
        updates["fit_preference"] = "宽松"
    elif any(phrase in text for phrase in ("喜欢修身", "偏好修身")):
        updates["fit_preference"] = "修身"
    style = re.search(r"(?:喜欢|偏好)([\u4e00-\u9fffA-Za-z0-9-]{1,12})风格", text)
    if style:
        updates["style_preference"] = style.group(1)
    color = re.search(r"(?:喜欢|偏好)([\u4e00-\u9fffA-Za-z0-9-]{1,8}(?:色|黑|白))", text)
    if color and "风格" not in color.group(1):
        updates["color_preference"] = color.group(1)
    return updates
