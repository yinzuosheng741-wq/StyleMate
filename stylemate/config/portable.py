"""Portable service settings. Secrets stay local and are never public defaults."""
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

FIELDS = (
    "LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "TEXT_MODEL_NAME",
    "VISION_BASE_URL", "VISION_API_KEY", "VISION_MODEL_NAME",
    "EMBEDDING_BASE_URL", "EMBEDDING_API_KEY", "EMBEDDING_MODEL_NAME",
    "AMAP_API_KEY", "WEATHER_PROVIDER", "WEATHER_CITY", "ALLOW_IP_LOCATION",
)
DEFAULTS = dict.fromkeys(FIELDS, "") | {
    "LLM_PROVIDER": "openai-compatible", "WEATHER_PROVIDER": "amap", "ALLOW_IP_LOCATION": "0",
}


def application_root():
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]


class ServiceConfigStore:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else application_root()
        self.path = self.root / "data/config/services.env"

    def load(self):
        values = dict(DEFAULTS)
        legacy = dotenv_values(self.root / ".env", interpolate=False) if (self.root / ".env").is_file() else {}
        # The portable file is authoritative, including explicitly empty keys.
        if self.path.is_file():
            saved = dotenv_values(self.path, interpolate=False)
            values.update({key: saved.get(key) or "" for key in FIELDS})
        else:
            for key in FIELDS:
                values[key] = os.environ.get(key) or legacy.get(key) or values[key]
            shared = os.environ.get("DASHSCOPE_API_KEY") or legacy.get("DASHSCOPE_API_KEY") or ""
            values["LLM_API_KEY"] = values["LLM_API_KEY"] or os.environ.get("OPENAI_API_KEY") or legacy.get("OPENAI_API_KEY") or shared
            values["LLM_BASE_URL"] = values["LLM_BASE_URL"] or os.environ.get("OPENAI_BASE_URL") or legacy.get("OPENAI_BASE_URL") or ""
            values["VISION_API_KEY"] = values["VISION_API_KEY"] or shared
            values["EMBEDDING_API_KEY"] = values["EMBEDDING_API_KEY"] or shared
            values["AMAP_API_KEY"] = values["AMAP_API_KEY"] or os.environ.get("GAODE_API_KEY") or legacy.get("GAODE_API_KEY") or ""
        return {key: str(value).strip() for key, value in values.items()}

    def save(self, values):
        validated = validate_config(values)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                stream.write("# Local private configuration. Do not share this file.\n")
                for key, value in validated.items():
                    # dotenv single quotes keep dollar signs and double quotes literal.
                    quoted = value.replace("\\", "\\\\").replace("'", "\\'")
                    stream.write(f"{key}='{quoted}'\n")
            os.chmod(temporary, 0o600)
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
        return validated


def validate_config(values):
    result = {key: str(values.get(key, DEFAULTS[key])).strip() for key in FIELDS}
    for key, value in result.items():
        if any(char in value for char in ("\n", "\r", "\0")):
            raise ValueError("配置不能包含换行或控制字符。")
        if key.endswith("BASE_URL") and value:
            parsed = urlsplit(value)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
                    or parsed.password or parsed.query or parsed.fragment):
                raise ValueError("接口地址应为完整 HTTP(S) 地址，密钥请填写在 API Key 中。")
            if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("远程模型接口需要使用 HTTPS；HTTP 仅允许本机模型服务。")
    if result["WEATHER_PROVIDER"] not in {"amap", "open-meteo", "disabled"}:
        raise ValueError("请选择有效的天气服务。")
    if result["ALLOW_IP_LOCATION"] not in {"0", "1"}:
        raise ValueError("定位选项无效。")
    for prefix, model in [("LLM", "TEXT_MODEL_NAME"), ("VISION", "VISION_MODEL_NAME"), ("EMBEDDING", "EMBEDDING_MODEL_NAME")]:
        if result[prefix + "_API_KEY"] and not result[model]:
            raise ValueError("填写模型密钥后，请同时填写相应模型名称。")
    return result


def apply_environment(values):
    # Avoid accidentally using a developer/system fallback after a user clears a key.
    for alias in ("OPENAI_API_KEY", "DASHSCOPE_API_KEY", "GAODE_API_KEY", "OPENAI_BASE_URL", "DASHSCOPE_BASE_URL"):
        os.environ[alias] = ""
    for key in FIELDS:
        os.environ[key] = values.get(key, "")


def public_template(values):
    """Optional shareable presets contain model addresses/names, never credentials/location."""
    return json.dumps({key: value for key, value in values.items()
                       if key in FIELDS and not key.endswith("API_KEY") and key not in {"WEATHER_CITY", "ALLOW_IP_LOCATION"}},
                      ensure_ascii=False, indent=2)
