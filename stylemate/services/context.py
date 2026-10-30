"""Application services and validated wardrobe operations for the native client."""

import hashlib
import os
from dataclasses import dataclass
from typing import Callable

from stylemate.agent.model import build_chat_model_from_env
from stylemate.agent.service import AgentService
from stylemate.agent.tools.location_weather import WeatherResult
from stylemate.config.portable import application_root
from stylemate.config.runtime import RuntimeSettings
from stylemate.demo.sample_data import sample_garments
from stylemate.domain.models import Garment
from stylemate.gateways.vision import (
    DashScopeVisionGateway,
    OpenAICompatibleVisionGateway,
    VisionGateway,
)
from stylemate.rag.corpus import load_builtin_records
from stylemate.rag.retriever import (
    DashScopeEmbeddingAdapter,
    HybridRetriever,
    OpenAICompatibleEmbeddingAdapter,
    create_chroma_client,
)
from stylemate.repositories.agent_base import AgentRepository
from stylemate.repositories.agent_session import SessionAgentRepository
from stylemate.repositories.agent_sqlite import SQLiteAgentRepository
from stylemate.repositories.base import WardrobeRepository
from stylemate.repositories.session import SessionWardrobeRepository
from stylemate.repositories.sqlite import SQLiteWardrobeRepository
from stylemate.services.demo_wardrobe import seed_local_demo_wardrobe
from stylemate.services.profile_service import ProfileService
from stylemate.services.wardrobe_service import WardrobeService
from stylemate.services.weather import WeatherClient
from stylemate.skills.outfit_planning import OutfitPlanningSkill
from stylemate.skills.wardrobe_onboarding import WardrobeOnboardingSkill
from stylemate.storage.images import ImageStore, LocalImageStore, SessionImageStore


@dataclass
class AppContext:
    settings: RuntimeSettings
    owner_id: str
    repository: WardrobeRepository
    image_store: ImageStore
    wardrobe_service: WardrobeService
    profile_service: ProfileService
    agent_repository: AgentRepository
    agent_service: AgentService
    conversation_id: str
    weather_client: WeatherClient
    onboarding_skill: WardrobeOnboardingSkill
    outfit_skill: OutfitPlanningSkill


def _weather_loader(settings: RuntimeSettings) -> Callable[[str], WeatherResult]:
    client = WeatherClient(settings, os.getenv("AMAP_API_KEY") or os.getenv("GAODE_API_KEY", ""))
    return client.weather


def _credential_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def build_context(
    state: dict,
    settings: RuntimeSettings,
    vision: VisionGateway | None = None,
    weather_loader: Callable[[str], WeatherResult] | None = None,
) -> AppContext:
    """Build per-session dependencies, retaining only the selected data store."""
    project_root = application_root()
    if settings.app_mode == "demo":
        repository = state.setdefault("stylemate_repository", SessionWardrobeRepository(state))
        image_store = state.setdefault("stylemate_image_store", SessionImageStore(state))
        agent_repository = state.setdefault(
            "stylemate_agent_repository", SessionAgentRepository(state)
        )
        owner_id = "demo-user"
    else:
        database_path = project_root / "data" / "stylemate.db"
        from stylemate.agent.telemetry import configure_run_logging
        configure_run_logging(project_root / "data" / "desktop")
        repository = state.setdefault(
            "stylemate_repository", SQLiteWardrobeRepository(database_path)
        )
        image_store = state.setdefault(
            "stylemate_image_store", LocalImageStore(project_root / "data" / "uploads")
        )
        agent_repository = state.setdefault(
            "stylemate_agent_repository", SQLiteAgentRepository(database_path)
        )
        owner_id = "local-user"
        seed_local_demo_wardrobe(
            repository,
            image_store,
            project_root / "assets" / "demo" / "wardrobe.json",
            owner_id,
        )

    service = WardrobeService(repository, image_store, settings.max_upload_bytes)
    profile_service = ProfileService(repository)
    actual_vision = vision or _build_vision_gateway(settings)
    weather_key = os.getenv("AMAP_API_KEY") or os.getenv("GAODE_API_KEY", "")
    weather_signature = (settings.weather_provider, settings.weather_city, settings.allow_ip_location,
                         settings.weather_timeout_seconds, _credential_fingerprint(weather_key))
    if state.get("stylemate_weather_signature") != weather_signature:
        state["stylemate_weather_client"] = WeatherClient(settings, weather_key)
        state["stylemate_weather_signature"] = weather_signature
    weather_client = state["stylemate_weather_client"]
    actual_weather = weather_loader or weather_client.weather
    conversation_id = state.setdefault(
        "stylemate_conversation_id", "wardrobe-assistant"
    )
    model_signature = (
        settings.text_provider_name,
        settings.text_base_url,
        settings.text_model_name,
        settings.model_timeout_seconds,
        _credential_fingerprint(os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY", "")),
    )
    if state.get("stylemate_chat_model_signature") != model_signature:
        state["stylemate_chat_model"] = build_chat_model_from_env(settings)
        state["stylemate_chat_model_signature"] = model_signature
    model = state["stylemate_chat_model"]
    retriever_signature = (
        settings.embedding_base_url,
        settings.embedding_model_name,
        _credential_fingerprint(os.getenv("EMBEDDING_API_KEY") or os.getenv("DASHSCOPE_API_KEY", "")),
        settings.rag_timeout_seconds,
    )
    if state.get("stylemate_retriever_signature") != retriever_signature:
        embedding = _build_embedding(settings)
        state["stylemate_retriever"] = HybridRetriever(
            load_builtin_records(project_root / "data" / "knowledge" / "records.jsonl"),
            agent_repository,
            embedding,
            create_chroma_client(
                settings.app_mode, str(project_root / "data" / "chroma")
            ),
            settings.rag_timeout_seconds,
        )
        state["stylemate_retriever_signature"] = retriever_signature
    retriever = state["stylemate_retriever"]
    retriever.sync_user_documents(
        owner_id,
        conversation_id,
        agent_repository.list_documents(owner_id, conversation_id),
    )
    agent_service = AgentService(
        settings=settings,
        agent_repository=agent_repository,
        wardrobe_repository=repository,
        wardrobe_service=service,
        retriever=retriever,
        model=model,
        weather_client=weather_client,
    )
    return AppContext(
        settings=settings,
        owner_id=owner_id,
        repository=repository,
        image_store=image_store,
        wardrobe_service=service,
        profile_service=profile_service,
        agent_repository=agent_repository,
        agent_service=agent_service,
        conversation_id=conversation_id,
        weather_client=weather_client,
        onboarding_skill=WardrobeOnboardingSkill(service, actual_vision),
        outfit_skill=OutfitPlanningSkill(repository, weather_loader=actual_weather),
    )


def _build_vision_gateway(settings: RuntimeSettings) -> VisionGateway:
    api_key = os.getenv("VISION_API_KEY") or os.getenv("DASHSCOPE_API_KEY", "")
    if settings.vision_base_url.strip():
        return OpenAICompatibleVisionGateway(settings, api_key)
    return DashScopeVisionGateway(settings, api_key)


def _build_embedding(settings: RuntimeSettings):
    api_key = os.getenv("EMBEDDING_API_KEY") or os.getenv(
        "DASHSCOPE_API_KEY", ""
    )
    if not api_key.strip():
        return None
    if settings.embedding_base_url.strip():
        return OpenAICompatibleEmbeddingAdapter(
            api_key,
            settings.embedding_base_url,
            settings.embedding_model_name,
            settings.rag_timeout_seconds,
        )
    return DashScopeEmbeddingAdapter(settings.rag_timeout_seconds, api_key, settings.embedding_model_name)


def load_sample_wardrobe(context: AppContext) -> int:
    """Add only sample records absent from this session/owner."""
    present_ids = {
        garment.id
        for garment in context.repository.list_garments(context.owner_id)
    }
    inserted = 0
    for garment in sample_garments():
        if garment.id not in present_ids:
            context.repository.save_garment(context.owner_id, garment)
            inserted += 1
    return inserted


def delete_garment(context: AppContext, garment_id: str) -> None:
    """Delete an owned image first, then its wardrobe record."""
    garment = context.repository.get_garment(context.owner_id, garment_id)
    if garment is None:
        return
    if garment.image_ref:
        context.image_store.delete(context.owner_id, garment.image_ref)
    context.repository.delete_garment(context.owner_id, garment_id)


def validated_garment_update(
    garment: Garment,
    *,
    name: str,
    category: str,
    primary_color: str,
    material: str | None,
    seasons: str,
    styles: str,
) -> Garment:
    """Return a fully validated edit, leaving persistence to the caller."""
    normalized = {
        "name": name.strip(),
        "category": category.strip(),
        "primary_color": primary_color.strip(),
        "material": material.strip() if material else None,
        "seasons": _split_labels(seasons),
        "styles": _split_labels(styles),
    }
    required = ("name", "category", "primary_color")
    if any(not normalized[field] for field in required):
        raise ValueError("Name, category, and color are required")
    if not normalized["seasons"] or not normalized["styles"]:
        raise ValueError("At least one season and style are required")
    return Garment.model_validate({**garment.model_dump(mode="json"), **normalized})


def _split_labels(value: str) -> list[str]:
    return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
