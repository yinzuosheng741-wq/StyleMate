"""Small user-triggered probes. Never return exception bodies or credentials."""
import base64
import time
from io import BytesIO

import requests
from PIL import Image

from stylemate.config.runtime import RuntimeSettings
from stylemate.services.weather import WeatherClient


def check_service(kind, values, session=None):
    session = session or requests.Session()
    started = time.monotonic()
    try:
        if kind == "weather":
            settings = RuntimeSettings(app_mode="local", vision_model_name="", text_model_name="",
                                       weather_provider=values["WEATHER_PROVIDER"], weather_city=values["WEATHER_CITY"],
                                       allow_ip_location=values["ALLOW_IP_LOCATION"] == "1")
            weather = WeatherClient(settings, values["AMAP_API_KEY"], session).weather()
            messages = {"disabled": "当前已关闭在线天气。", "missing_city": "请填写默认城市；高德用户也可主动启用 IP 城市定位。",
                        "location_disabled": "IP 定位未启用，请填写城市或在设置中主动启用。"}
            return {"ok": weather.available, "message": (f"{weather.city} · {weather.summary} · {weather.temperature_c}℃"
                    if weather.available else messages.get(weather.reason, "天气不可用：请检查城市、Key、授权及网络。"))}
        prefix, model_key = {"text": ("LLM", "TEXT_MODEL_NAME"), "vision": ("VISION", "VISION_MODEL_NAME"),
                             "embedding": ("EMBEDDING", "EMBEDDING_MODEL_NAME")}[kind]
        key = values[prefix + "_API_KEY"]
        model = values[model_key]
        if not key or not model:
            return {"ok": False, "message": "请填写 API Key 和模型名称。"}
        base = values[prefix + "_BASE_URL"] or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        if kind == "embedding":
            endpoint, body = "/embeddings", {"model": model, "input": ["衣物洗护"]}
        else:
            content = "Reply OK."
            if kind == "vision":
                image = BytesIO()
                Image.new("RGB", (32, 32), "blue").save(image, "PNG")
                content = [{"type": "text", "text": "Name the image color in one word."},
                           {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(image.getvalue()).decode()}}]
            endpoint = "/chat/completions"
            body = {"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": 64}
        response = session.post(base.rstrip("/") + endpoint, headers={"Authorization": "Bearer " + key},
                                json=body, timeout=(5, 25), allow_redirects=False)
        if response.status_code != 200:
            reason = {401: "密钥无效或已失效", 403: "账号或模型未授权", 404: "接口路径或模型名称不正确",
                      429: "额度不足或请求受限", 400: "模型不支持此请求或参数"}.get(response.status_code, "服务返回异常")
            return {"ok": False, "message": f"HTTP {response.status_code}：{reason}。"}
        data = response.json()
        valid = bool(data.get("data") and data["data"][0].get("embedding")) if kind == "embedding" else bool(
            data.get("choices") and data["choices"][0].get("message", {}).get("content"))
        if not valid:
            return {"ok": False, "message": "接口已响应，但返回内容不符合该能力的格式。"}
        return {"ok": True, "message": f"测试通过 · {time.monotonic() - started:.1f} 秒"}
    except requests.Timeout:
        return {"ok": False, "message": "连接超时，请检查网络或服务状态。"}
    except Exception:
        return {"ok": False, "message": "连接失败，请检查地址、代理、证书及服务配置。"}
