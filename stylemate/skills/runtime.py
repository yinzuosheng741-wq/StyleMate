"""Per-invocation contracts for bounded, synchronous domain workflows.

Steps are checked before their body runs. This limits admitted workflow actions,
not CPU time or individual HTTP requests inside an action. External tool calls
still need ToolExecutor's deadline and capacity boundary.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from time import perf_counter
from typing import Literal

from pydantic import BaseModel

from stylemate.domain.models import AgentTrace, AgentTraceStep, SkillOutcome, SkillSpec


class SkillContractError(ValueError):
    """An undeclared or over-budget action was rejected before execution."""


@dataclass
class StepResult:
    status: Literal["success", "fallback", "failed"] = "success"


class SkillRun:
    def __init__(self, spec: SkillSpec, request: BaseModel, *, trace_name: str):
        self.spec = spec
        # Revalidate serialized input so model_construct/model_copy cannot skip
        # the declared contract at this entry point.
        self.request = spec.input_model.model_validate(request.model_dump())
        self.trace_name = trace_name
        self.started = perf_counter()
        self.steps: list[AgentTraceStep] = []
        self.admitted_steps = 0

    @contextmanager
    def step(self, name: str) -> Iterator[StepResult]:
        if name not in self.spec.allowed_tools:
            raise SkillContractError("undeclared skill action")
        if self.admitted_steps >= self.spec.max_steps:
            raise SkillContractError("skill step budget exhausted")
        self.admitted_steps += 1
        result = StepResult()
        started = perf_counter()
        try:
            yield result
        except Exception:
            result.status = "failed"
            raise
        finally:
            self.steps.append(AgentTraceStep(
                name=name, status=result.status, summary=f"{name}: {result.status}",
                duration_ms=max(0, round((perf_counter() - started) * 1000)),
            ))

    def finish(self, *, status, data: dict, message: str) -> SkillOutcome:
        outcome = SkillOutcome(
            status=status, data=data, user_message=message,
            trace=AgentTrace(
                skill_name=self.trace_name, steps=list(self.steps),
                duration_ms=max(0, round((perf_counter() - self.started) * 1000)),
                status=("fallback" if any(step.status == "fallback" for step in self.steps) else "success")
                if status == "needs_review" else status,
            ),
        )
        return self.spec.output_model.model_validate(outcome.model_dump())
