"""Typed, auditable data exchanged by the wardrobe knowledge retriever."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator

KnowledgeTopic = Literal["fabric", "care", "size", "color", "weather", "scenario", "wardrobe", "style", "storage"]


class KnowledgeRecord(BaseModel):
    id: str
    title: str = Field(min_length=4, max_length=80)
    content: str = Field(min_length=40, max_length=900)
    source_url: HttpUrl | None
    source_name: str
    topic: KnowledgeTopic
    retrieved_at: date
    content_kind: Literal["source_summary", "heuristic"] = "source_summary"
    review_status: Literal["pending_review", "reviewed", "quarantined", "project_rule"] = "pending_review"
    source_locator: str = ""
    review_note: str = ""
    reviewed_at: date | None = None
    reviewer: str = ""
    applicability: str = ""
    limitations: str = ""

    @model_validator(mode="after")
    def review_contract(self) -> "KnowledgeRecord":
        if self.content_kind == "heuristic" and self.review_status not in {"project_rule", "pending_review"}:
            raise ValueError("heuristics cannot be published as reviewed source evidence")
        if self.review_status == "project_rule" and self.content_kind != "heuristic":
            raise ValueError("project rules must be labeled heuristic")
        if self.review_status == "reviewed" and not (
            self.source_url and self.source_locator.strip() and self.review_note.strip()
            and self.reviewed_at and self.reviewer.strip() and self.applicability.strip()
        ):
            raise ValueError("reviewed evidence requires source, locator, scope and review provenance")
        return self

    @property
    def is_published_evidence(self) -> bool:
        return self.content_kind == "source_summary" and self.review_status == "reviewed"


class RetrievalHit(BaseModel):
    title: str
    snippet: str
    source_name: str
    source_url: str
    topic: KnowledgeTopic
    score: float
    record_id: str | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    page_number: int | None = None
    section_title: str | None = None
    source_locator: str | None = None
    review_status: str | None = None
    applicability: str | None = None
    limitations: str | None = None


class UserDocumentText(BaseModel):
    filename: str
    mime_type: str
    text: str
    pages: list[str] = Field(default_factory=list)


class UserDocumentChunk(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    text: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    page_number: int | None = Field(default=None, ge=1)
    section_title: str | None = None
    previous_chunk_id: str | None = None
    next_chunk_id: str | None = None
