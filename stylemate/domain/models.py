import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Garment(BaseModel):
    id: str
    name: str
    category: str = Field(min_length=1)
    primary_color: str = Field(min_length=1)
    material: str | None = None
    seasons: list[str] = Field(min_length=1)
    styles: list[str] = Field(min_length=1)
    image_ref: str | None = None
    image_hash: str | None = None
    confidence: dict[str, float] = Field(default_factory=dict)
    source: Literal["ai", "manual", "sample"]
    created_at: datetime = Field(default_factory=datetime.now)


class OutfitRequest(BaseModel):
    scene: str = Field(min_length=1)
    target_date: str | None = None
    city: str | None = None
    target_season: str | None = None
    temperature_c: float | None = Field(default=None, ge=-50, le=60)
    weather_condition: str | None = None
    style_preference: str | None = None
    color_preference: str | None = None
    fit_preference: str | None = None
    extra_constraints: list[str] = Field(default_factory=list)
    candidate_garment_ids: list[str] = Field(default_factory=list)


class OutfitRecommendation(BaseModel):
    id: str
    garment_ids: list[str] = Field(min_length=1)
    score: int = Field(ge=0, le=100)
    reason: str = Field(min_length=1)
    weather_note: str | None = None
    constraint_checks: dict[str, bool]
    score_breakdown: dict[str, int] = Field(default_factory=dict)
    knowledge_sources: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)

    @field_validator("garment_ids")
    @classmethod
    def unique_ids(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))


class AgentTraceStep(BaseModel):
    name: str
    status: Literal["success", "fallback", "failed"]
    summary: str
    duration_ms: int = Field(ge=0)


class ToolSpec(BaseModel):
    """Guardrails that apply before a tool handler is allowed to run."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    permission: Literal["read", "write_prepare"]
    timeout_seconds: int = Field(default=5, ge=1, le=30)
    retry_once: bool = False
    validates_inventory_ids: bool = False
    arguments_model: type[BaseModel] | None = None


class ToolExecution(BaseModel):
    status: Literal["success", "fallback", "failed"]
    data: Any = None
    user_message: str
    trace: AgentTraceStep


class KnowledgeSource(BaseModel):
    id: str
    title: str
    url: str


class ConversationMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)
    traces: list[AgentTraceStep] = Field(default_factory=list)
    sources: list[KnowledgeSource] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)


class PendingAction(BaseModel):
    id: str
    owner_id: str
    conversation_id: str
    operation: Literal["add", "update", "delete"]
    target_garment_id: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    created_at: datetime
    expires_at: datetime


class FactProvenance(BaseModel):
    field: Literal[
        "topics",
        "scenes",
        "locations",
        "garment_ids",
        "constraints",
        "last_user_goal",
    ]
    value: str = Field(min_length=1, max_length=400)
    source_message_id: str
    updated_at: datetime
    expires_at: datetime | None = None


class ConversationFacts(BaseModel):
    """Bounded, session-scoped facts extracted from compacted dialogue."""

    topics: list[str] = Field(default_factory=list, max_length=12)
    scenes: list[str] = Field(default_factory=list, max_length=8)
    locations: list[str] = Field(default_factory=list, max_length=8)
    garment_ids: list[str] = Field(default_factory=list, max_length=16)
    constraints: list[str] = Field(default_factory=list, max_length=12)
    last_user_goal: str = Field(default="", max_length=400)
    legacy_notes: list[str] = Field(default_factory=list, max_length=2)
    provenance: list[FactProvenance] = Field(default_factory=list, max_length=80)


class ConversationState(BaseModel):
    owner_id: str
    conversation_id: str
    messages: list[ConversationMessage] = Field(default_factory=list)
    # Full UI history is never passed to the model. Old payloads migrate on save.
    transcript: list[ConversationMessage] = Field(default_factory=list)
    facts: ConversationFacts = Field(default_factory=ConversationFacts)
    # Read old persisted payloads, then migrate this text into facts on the next turn.
    summary: str = ""


class UserDocument(BaseModel):
    owner_id: str
    conversation_id: str
    document_id: str
    filename: str
    mime_type: str
    text: str
    pages: list[str] = Field(default_factory=list)
    created_at: datetime


class AgentTrace(BaseModel):
    skill_name: str
    steps: list[AgentTraceStep]
    tool_calls: list[str] = Field(default_factory=list)
    fallbacks: list[str] = Field(default_factory=list)
    duration_ms: int = Field(ge=0)
    status: Literal["success", "fallback", "failed"]


class SkillSpec(BaseModel):
    """Static contract for a bounded, reusable domain workflow."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    allowed_tools: tuple[str, ...]
    max_steps: int = Field(ge=1, le=8)
    fallback_strategy: str


class FavoriteOutfit(BaseModel):
    owner_id: str
    recommendation: OutfitRecommendation


class OutfitFeedback(BaseModel):
    outfit_id: str
    owner_id: str
    reasons: list[str]
    note: str = ""


class SkillOutcome(BaseModel):
    status: Literal["success", "needs_review", "fallback", "failed"]
    data: dict[str, Any]
    trace: AgentTrace
    user_message: str
