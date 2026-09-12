"""Non-sensitive runtime diagnostics for demos and deployment checks."""

from __future__ import annotations

import os
from typing import Any


def runtime_diagnostics(settings: Any, retriever: Any | None = None) -> dict[str, Any]:
    """Return a redacted readiness snapshot; never include key values or prompts."""
    embedding_key = bool(os.getenv("EMBEDDING_API_KEY") or os.getenv("DASHSCOPE_API_KEY"))
    text_key = bool(os.getenv("LLM_API_KEY") or os.getenv("DASHSCOPE_API_KEY"))
    vision_key = bool(os.getenv("VISION_API_KEY") or os.getenv("DASHSCOPE_API_KEY"))
    weather_key = bool(os.getenv("AMAP_API_KEY") or os.getenv("GAODE_API_KEY"))
    result: dict[str, Any] = {
        "mode": settings.app_mode,
        "text_model": settings.text_model_name,
        "embedding_model": settings.embedding_model_name,
        "text_model_configured": text_key,
        "vision_configured": vision_key,
        "embedding_configured": embedding_key,
        "weather_configured": weather_key,
        "rag_mode": "hybrid" if embedding_key else "bm25-fallback",
    }
    if retriever is not None and hasattr(retriever, "stats"):
        result["retriever_stats"] = retriever.stats()
    return result


__all__ = ["runtime_diagnostics"]
