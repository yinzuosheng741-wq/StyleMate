"""Strict, tool-specific argument contracts exposed to the language model."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmptyArguments(StrictArguments):
    pass


class WeatherArguments(StrictArguments):
    city: str = Field(default="", max_length=80)


class SizeArguments(StrictArguments):
    height_cm: float = Field(ge=120, le=230)
    weight_kg: float = Field(ge=30, le=200)
    fit_preference: str = Field(default="标准", max_length=40)


class CareArguments(StrictArguments):
    material: str = Field(min_length=1, max_length=80)


class RagSearchArguments(StrictArguments):
    query: str = Field(min_length=1, max_length=500)


class WardrobeSearchArguments(StrictArguments):
    name: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=80)
    color: str | None = Field(default=None, max_length=80)
    season: str | None = Field(default=None, max_length=80)
    style: str | None = Field(default=None, max_length=80)


class OutfitArguments(StrictArguments):
    scene: str = Field(min_length=1, max_length=80)
    target_date: str | None = Field(default=None, max_length=32)
    city: str | None = Field(default=None, max_length=80)
    target_season: str | None = Field(default=None, max_length=20)
    temperature_c: float | None = Field(default=None, ge=-50, le=60)
    weather_condition: str | None = Field(default=None, max_length=80)
    style_preference: str | None = Field(default=None, max_length=80)
    color_preference: str | None = Field(default=None, max_length=80)
    fit_preference: str | None = Field(default=None, max_length=80)
    extra_constraints: list[str] = Field(default_factory=list, max_length=12)
    candidate_garment_ids: list[str] = Field(default_factory=list, max_length=100)
    required_garment_id: str | None = Field(default=None, min_length=1, max_length=120)


class OpenOutfitArguments(OutfitArguments):
    """Arguments for a knowledge-first outfit recommendation."""


class PurchaseArguments(StrictArguments):
    season: str = Field(default="", max_length=20)
    scene: str = Field(default="日常", max_length=80)
    temperature_c: float | None = Field(default=None, ge=-50, le=60)


class TravelArguments(StrictArguments):
    destination: str = Field(min_length=1, max_length=80)
    days: int = Field(default=3, ge=1, le=30)
    activities: list[str] = Field(default_factory=list, max_length=8)
    temperature_c: float | None = Field(default=None, ge=-50, le=60)
    weather_condition: str | None = Field(default=None, max_length=80)


class WardrobeGapArguments(StrictArguments):
    season: str = Field(default="", max_length=80)


class ItemStyleArguments(StrictArguments):
    garment_id: str = Field(min_length=1, max_length=120)


class GetGarmentArguments(StrictArguments):
    garment_id: str = Field(min_length=1, max_length=120)


class ManualGarmentInput(StrictArguments):
    id: str | None = Field(default=None, min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    primary_color: str = Field(min_length=1, max_length=80)
    material: str | None = Field(default=None, max_length=80)
    seasons: list[str] = Field(min_length=1, max_length=12)
    styles: list[str] = Field(min_length=1, max_length=12)


class AddGarmentArguments(StrictArguments):
    metadata: ManualGarmentInput


class GarmentChanges(StrictArguments):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, min_length=1, max_length=80)
    primary_color: str | None = Field(default=None, min_length=1, max_length=80)
    material: str | None = Field(default=None, max_length=80)
    seasons: list[str] | None = Field(default=None, min_length=1, max_length=12)
    styles: list[str] | None = Field(default=None, min_length=1, max_length=12)

    @model_validator(mode="after")
    def has_change(self) -> "GarmentChanges":
        if not self.model_fields_set:
            raise ValueError("at least one editable field is required")
        return self


class UpdateGarmentArguments(StrictArguments):
    garment_id: str = Field(min_length=1, max_length=120)
    changes: GarmentChanges


class DeleteGarmentArguments(StrictArguments):
    garment_id: str = Field(min_length=1, max_length=120)


READ_TOOL_SCHEMAS: dict[str, type[BaseModel]] = {
    "get_user_location": EmptyArguments,
    "get_weather": WeatherArguments,
    "recommend_size": SizeArguments,
    "care_guide": CareArguments,
    "rag_search": RagSearchArguments,
    "search_wardrobe": WardrobeSearchArguments,
    "recommend_inventory_outfit": OutfitArguments,
    "recommend_open_outfit": OpenOutfitArguments,
    "recommend_purchases": PurchaseArguments,
    "travel_packing": TravelArguments,
    "wardrobe_gap_check": WardrobeGapArguments,
    "item_style_analysis": ItemStyleArguments,
    "get_garment": GetGarmentArguments,
}

WRITE_TOOL_SCHEMAS: dict[str, type[BaseModel]] = {
    "add_garment": AddGarmentArguments,
    "update_garment": UpdateGarmentArguments,
    "delete_garment": DeleteGarmentArguments,
}


def plain_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Convert nested Pydantic values produced by LangChain back to plain data."""
    return {
        key: value.model_dump(exclude_none=True)
        if isinstance(value, BaseModel)
        else value
        for key, value in arguments.items()
    }


__all__ = [
    "READ_TOOL_SCHEMAS",
    "WRITE_TOOL_SCHEMAS",
    "CareArguments",
    "ItemStyleArguments",
    "OutfitArguments",
    "OpenOutfitArguments",
    "PurchaseArguments",
    "RagSearchArguments",
    "SizeArguments",
    "WardrobeGapArguments",
    "WardrobeSearchArguments",
    "TravelArguments",
    "WeatherArguments",
    "plain_arguments",
]
