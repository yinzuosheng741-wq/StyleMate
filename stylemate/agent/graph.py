"""A deliberately small, bounded assistant -> tools LangGraph."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph

from stylemate.agent.policy import check_request_deadline
from stylemate.agent.routing import route_skills
from stylemate.agent.state import AgentState, model_messages

logger = logging.getLogger(__name__)

MAX_MODEL_CALLS = 4
MAX_TOOL_CALLS = 6
_STOP_MESSAGE = "本轮工具调用次数已达上限，请缩小问题后再试。"


def _system_prompt() -> str:
    path = Path(__file__).resolve().parent.parent / "prompts" / "agent_system.txt"
    return path.read_text(encoding="utf-8") if path.exists() else "你是 StyleMate 衣橱助手。回答简洁、基于工具结果，衣橱写操作必须先等待确认。"


def build_agent_graph(model, tools: list[BaseTool]):
    """Compile the two-node graph.  The tool node only sees bound closures."""
    tool_map = {tool.name: tool for tool in tools}

    def route(state: AgentState) -> dict[str, Any]:
        user_messages = [m for m in state.get("messages", []) if getattr(m, "type", "") == "human"]
        text = str(user_messages[-1].content) if user_messages else ""
        decision = route_skills(text, set(tool_map))
        logger.info("skill_route_finished skills=%s tools=%d", decision.skills, len(decision.allowed_tools))
        return {"allowed_tools": sorted(decision.allowed_tools), "active_skills": list(decision.skills),
                "traces": [{"name": "skill_router", "status": "success",
                            "summary": ", ".join(decision.skills), "duration_ms": 0}]}

    def assistant(state: AgentState) -> dict[str, Any]:
        check_request_deadline()
        if (
            state.get("model_calls", 0) >= MAX_MODEL_CALLS
            or state.get("tool_calls", 0) >= MAX_TOOL_CALLS
        ):
            return {"messages": [AIMessage(content=_STOP_MESSAGE)]}
        allowed = set(state.get("allowed_tools", []))
        visible_tools = [tool for tool in tools if tool.name in allowed]
        logger.info("agent_model_started call=%d tools=%d", state.get("model_calls", 0) + 1, len(visible_tools))
        response = model.bind_tools(visible_tools).invoke(model_messages(state, _system_prompt()))
        check_request_deadline()
        if not isinstance(response, AIMessage):
            response = AIMessage(content=str(getattr(response, "content", response) or ""))
        # Do not end the graph on an unexecuted tool request at the model-call limit.
        if (
            response.tool_calls
            and state.get("model_calls", 0) + 1 >= MAX_MODEL_CALLS
        ):
            response = AIMessage(content=_STOP_MESSAGE)
        return {"messages": [response], "model_calls": 1}

    def route_after_assistant(state: AgentState) -> str:
        message = state.get("messages", [])[-1] if state.get("messages") else None
        if state.get("model_calls", 0) >= MAX_MODEL_CALLS:
            return END
        if getattr(message, "tool_calls", None):
            return "tools" if state.get("tool_calls", 0) < MAX_TOOL_CALLS else END
        return END

    def tool_node(state: AgentState) -> dict[str, Any]:
        message = state.get("messages", [])[-1]
        messages: list[ToolMessage] = []
        traces: list[dict[str, Any]] = []
        sources: list[dict[str, str]] = []
        pending = None
        count = 0
        for call in getattr(message, "tool_calls", []) or []:
            if state.get("tool_calls", 0) + count >= MAX_TOOL_CALLS:
                messages.append(ToolMessage(content=json.dumps({"result": {"message": _STOP_MESSAGE}}, ensure_ascii=False), tool_call_id=call.get("id", "limit"), name=call.get("name", "tool")))
                continue
            name, args = call.get("name", ""), call.get("args", {}) or {}
            tool = tool_map.get(name)
            if tool is not None and name not in state.get("allowed_tools", []):
                logger.warning("tool_policy_blocked tool=%s", name)
                raw = {"result": {"message": "当前任务未开放该工具，请明确操作意图后重试。"},
                       "trace": {"name": name, "status": "failed", "summary": "skill tool permission denied", "duration_ms": 0}}
            elif tool is None:
                raw = {"result": {"message": "不支持该工具。"}, "trace": {"name": name or "unknown", "status": "failed", "summary": "unknown tool", "duration_ms": 0}}
            else:
                try:
                    raw = json.loads(tool.invoke(args))
                except Exception:
                    raw = {"result": {"message": "工具暂时不可用。"}, "trace": {"name": name, "status": "failed", "summary": "tool invocation failed", "duration_ms": 0}}
            trace = raw.get("trace")
            if isinstance(trace, dict):
                traces.append(trace)
            if isinstance(raw.get("sources"), list):
                sources.extend(item for item in raw["sources"] if isinstance(item, dict))
            if isinstance(raw.get("pending_action"), dict):
                pending = raw["pending_action"]
            messages.append(ToolMessage(content=json.dumps({"result": raw.get("result", {})}, ensure_ascii=False, default=str, separators=(",", ":")), tool_call_id=call.get("id", name), name=name))
            count += 1
        update: dict[str, Any] = {"messages": messages, "traces": traces, "sources": sources, "tool_calls": count}
        if pending is not None:
            update["pending_action"] = pending
        return update

    builder = StateGraph(AgentState)
    builder.add_node("route", route)
    builder.add_node("assistant", assistant)
    builder.add_node("tools", tool_node)
    builder.add_edge(START, "route")
    builder.add_edge("route", "assistant")
    builder.add_conditional_edges("assistant", route_after_assistant, {"tools": "tools", END: END})
    builder.add_edge("tools", "assistant")
    return builder.compile()


__all__ = ["build_agent_graph", "MAX_MODEL_CALLS", "MAX_TOOL_CALLS"]
