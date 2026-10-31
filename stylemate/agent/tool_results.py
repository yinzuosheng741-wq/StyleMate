"""Business outcomes are separate from successful handler execution.

Output validation is enabled incrementally per tool. Existing data payloads
remain compatible; model and UI receive explicit metadata alongside them.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from stylemate.domain.models import Garment, OutfitRecommendation, ToolExecution


class GarmentLookupResult(BaseModel):
    found: bool
    garment: Garment | None = None
    message: str = ""

    @model_validator(mode="after")
    def consistent_lookup(self):
        if self.found != (self.garment is not None):
            raise ValueError("lookup result inconsistent")
        return self


class InventoryOutfitResult(BaseModel):
    recommendations: list[OutfitRecommendation] = Field(max_length=3)
    message: str = ""


READ_TOOL_RESULT_MODELS = {
    "get_garment": GarmentLookupResult,
    "recommend_inventory_outfit": InventoryOutfitResult,
}


def business_metadata(name: str, data) -> dict:
    if not isinstance(data, dict):
        return {}
    if data.get("answer_status") == "needs_clarification" or data.get("missing_conditions"):
        return {"outcome": "needs_clarification", "reason_code": "missing_conditions",
                "missing_conditions": data.get("missing_conditions", [])}
    if data.get("found") is False:
        return {"outcome": "not_found", "reason_code": "item_not_found"}
    if data.get("available") is False:
        # A missing key, missing city and upstream outage need different user
        # actions. Conservatively avoid promising an automatic retry will help.
        return {"outcome": "unavailable", "reason_code": "dependency_unavailable"}
    if data.get("answer_status") == "not_found":
        return {"outcome": "not_found", "reason_code": "no_evidence"}
    if name in {"rag_search", "care_guide"} and data.get("results") == []:
        return {"outcome": "not_found", "reason_code": "no_evidence"}
    if name == "recommend_inventory_outfit" and data.get("recommendations") == []:
        return {"outcome": "empty", "reason_code": "no_feasible_outfit"}
    if name == "search_wardrobe" and data.get("garments") == []:
        return {"outcome": "empty", "reason_code": "no_matching_garments"}
    return {}


class ToolResultEnvelope(BaseModel):
    result: object
    outcome: Literal["success", "empty", "not_found", "needs_clarification", "unavailable", "error"]
    execution_status: Literal["success", "fallback", "failed"]
    reason_code: str
    retryable: bool = False
    missing_conditions: list[str] = Field(default_factory=list)


def execution_payload(execution: ToolExecution) -> dict:
    return ToolResultEnvelope(
        result={"message": execution.user_message} if execution.status == "failed" else execution.data,
        outcome=execution.outcome, execution_status=execution.status,
        reason_code=execution.reason_code, retryable=execution.retryable,
        missing_conditions=execution.missing_conditions,
    ).model_dump(mode="json")


def error_payload(message: str, reason_code: str) -> dict:
    return ToolResultEnvelope(result={"message": message}, outcome="error",
                              execution_status="failed", reason_code=reason_code).model_dump(mode="json")
