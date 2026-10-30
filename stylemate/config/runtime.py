import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeSettings:
    app_mode: str
    vision_model_name: str
    text_model_name: str
    max_upload_bytes: int = 8 * 1024 * 1024
    weather_timeout_seconds: int = 5
    model_timeout_seconds: int = 30
    text_provider_name: str = "dashscope"
    text_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    vision_base_url: str = ""
    embedding_base_url: str = ""
    embedding_model_name: str = "text-embedding-v4"
    rag_top_k: int = 4
    rag_timeout_seconds: int = 15
    tool_timeout_seconds: int = 5
    max_document_bytes: int = 4 * 1024 * 1024
    max_document_chars: int = 200_000
    weather_provider: str = "amap"
    weather_city: str = ""
    allow_ip_location: bool = False

    @property
    def dashscope_base_url(self) -> str:
        """Backward-compatible alias for older callers and saved documentation."""
        return self.text_base_url

    @classmethod
    def from_env(cls) -> "RuntimeSettings":
        mode = os.getenv("APP_MODE", "local").strip().lower()
        if mode not in {"demo", "local"}:
            raise ValueError("APP_MODE must be 'demo' or 'local'")
        return cls(
            app_mode=mode,
            vision_model_name=os.getenv("VISION_MODEL_NAME", "qwen-vl-plus"),
            text_model_name=os.getenv("TEXT_MODEL_NAME", "qwen-plus"),
            text_provider_name=(
                os.getenv("LLM_PROVIDER")
                or os.getenv("MODEL_PROVIDER")
                or "dashscope"
            ),
            text_base_url=(
                os.getenv("LLM_BASE_URL")
                or os.getenv("OPENAI_BASE_URL")
                or os.getenv("DASHSCOPE_BASE_URL")
                or "https://dashscope.aliyuncs.com/compatible-mode/v1"
            ),
            vision_base_url=os.getenv("VISION_BASE_URL", ""),
            embedding_base_url=os.getenv("EMBEDDING_BASE_URL", ""),
            embedding_model_name=os.getenv("EMBEDDING_MODEL_NAME", "text-embedding-v4"),
            weather_provider=os.getenv("WEATHER_PROVIDER", "amap"),
            weather_city=os.getenv("WEATHER_CITY", ""),
            allow_ip_location=os.getenv("ALLOW_IP_LOCATION", "0") == "1",
        )
