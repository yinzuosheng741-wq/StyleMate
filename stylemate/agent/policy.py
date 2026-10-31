"""One request policy shared by graph, shortcuts and deterministic fallbacks."""

import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import monotonic

from pydantic import ValidationError

from stylemate.agent.tool_results import error_payload
from stylemate.domain.models import OutfitRecommendation


@dataclass
class RequestPolicy:
    owner_id: str
    conversation_id: str
    allowed_tools: frozenset[str]
    max_calls: int = 6
    calls: int = 0
    deadline: float = 0.0
    outfits: list[OutfitRecommendation] = field(default_factory=list)


_policy: ContextVar[RequestPolicy | None] = ContextVar("stylemate_request_policy", default=None)


class RequestExecutionDenied(RuntimeError):
    """Stable request-boundary failure without provider or user content."""


def check_request_deadline() -> None:
    remaining = remaining_request_seconds()
    if remaining is not None and remaining <= 0:
        raise RequestExecutionDenied("request_deadline_exceeded")


def discard_request_outfits() -> None:
    policy = _policy.get()
    if policy is not None:
        policy.outfits.clear()


def remaining_request_seconds() -> float | None:
    """Return the trusted request's remaining wall-clock budget, if bound."""
    policy = _policy.get()
    return max(0.0, policy.deadline - monotonic()) if policy is not None else None


@contextmanager
def request_policy(owner_id, conversation_id, allowed_tools, *, max_calls=6, timeout=90):
    policy = RequestPolicy(owner_id, conversation_id, frozenset(allowed_tools),
                           max_calls=max_calls, deadline=monotonic() + timeout)
    token = _policy.set(policy)
    try:
        yield policy
    finally:
        _policy.reset(token)


def denied_tool_payload(name: str, owner_id: str, conversation_id: str) -> str | None:
    policy = _policy.get()
    if policy is None:
        # Direct trusted library calls remain available; public chat binds policy.
        return None
    code = ""
    if (owner_id, conversation_id) != (policy.owner_id, policy.conversation_id):
        code = "identity_scope_denied"
    elif name not in policy.allowed_tools:
        code = "tool_capability_denied"
    elif monotonic() >= policy.deadline:
        code = "request_deadline_exceeded"
    elif policy.calls >= policy.max_calls:
        code = "tool_budget_exhausted"
    if not code:
        policy.calls += 1
        return None
    return json.dumps({**error_payload("本轮工具权限或预算受限，请调整问题后重试。", code),
                       "trace": {"name": name, "status": "failed", "summary": code,
                                 "duration_ms": 0}}, ensure_ascii=False)


def record_outfits(owner_id, conversation_id, result, repository):
    """Capture typed read-only results at the trusted tool boundary, never from model prose."""
    policy = _policy.get()
    if policy is None or (owner_id, conversation_id) != (policy.owner_id, policy.conversation_id):
        return
    if len(policy.outfits) >= 3:
        return
    if "recommend_inventory_outfit" not in policy.allowed_tools or not isinstance(result.get("recommendations"), list):
        return
    seen = {item.id for item in policy.outfits}
    for payload in result.get("recommendations", [])[:3]:
        try:
            outfit = OutfitRecommendation.model_validate(payload)
        except (ValidationError, TypeError):
            continue
        if outfit.id in seen or not all(repository.get_garment(owner_id, key) for key in outfit.garment_ids):
            continue
        policy.outfits.append(outfit)
        seen.add(outfit.id)
        if len(policy.outfits) >= 3:
            break


def current_outfits(owner_id, conversation_id):
    policy = _policy.get()
    if policy is None or (owner_id, conversation_id) != (policy.owner_id, policy.conversation_id):
        return []
    return list(policy.outfits)
