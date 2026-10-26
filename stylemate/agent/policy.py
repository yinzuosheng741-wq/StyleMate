"""One request policy shared by graph, shortcuts and deterministic fallbacks."""

import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from time import monotonic


@dataclass
class RequestPolicy:
    owner_id: str
    conversation_id: str
    allowed_tools: frozenset[str]
    max_calls: int = 6
    calls: int = 0
    deadline: float = 0.0


_policy: ContextVar[RequestPolicy | None] = ContextVar("stylemate_request_policy", default=None)


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
    return json.dumps({"result": {"message": "本轮工具权限或预算受限，请调整问题后重试。"},
                       "trace": {"name": name, "status": "failed", "summary": code,
                                 "duration_ms": 0}}, ensure_ascii=False)
