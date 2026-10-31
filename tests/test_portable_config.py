import json
from types import SimpleNamespace

import pytest

from stylemate.config.portable import DEFAULTS, ServiceConfigStore, apply_environment, public_template, validate_config
from stylemate.config.runtime import RuntimeSettings
from stylemate.services.connection_check import check_service
from stylemate.services.weather import WeatherClient


def configured():
    return dict(DEFAULTS) | {"LLM_API_KEY": "private-key", "LLM_BASE_URL": "https://example.test/v1", "TEXT_MODEL_NAME": "example"}


def test_migration_and_explicit_clear_override_legacy_and_environment(tmp_path, monkeypatch):
    import os

    from stylemate.config.portable import FIELDS
    for key in (*FIELDS, "OPENAI_API_KEY", "DASHSCOPE_API_KEY", "GAODE_API_KEY", "OPENAI_BASE_URL", "DASHSCOPE_BASE_URL"):
        monkeypatch.setenv(key, os.environ.get(key, ""))
    (tmp_path / ".env").write_text("LLM_API_KEY=old-private\nTEXT_MODEL_NAME=old-model\n", "utf-8")
    store = ServiceConfigStore(tmp_path)
    assert store.load()["LLM_API_KEY"] == "old-private"
    store.save(dict(DEFAULTS))
    monkeypatch.setenv("LLM_API_KEY", "system-private")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fallback-private")
    values = store.load()
    assert values["LLM_API_KEY"] == ""
    apply_environment(values)
    assert not os.environ["DASHSCOPE_API_KEY"]
    assert not os.environ["LLM_API_KEY"]


def test_config_survives_folder_move_and_quotes_round_trip(tmp_path):
    secret = "private$token${VALUE}'quote\\slash\""
    store = ServiceConfigStore(tmp_path / "first")
    store.save(configured() | {"LLM_API_KEY": secret})
    (tmp_path / "first").rename(tmp_path / "moved")
    assert ServiceConfigStore(tmp_path / "moved").load()["LLM_API_KEY"] == secret
    assert not list((tmp_path / "moved").rglob("*.tmp"))


@pytest.mark.parametrize("url", ["http://remote.test/v1", "https://user:secret@host.test/v1", "https://host.test?key=secret", "not-a-url"])
def test_invalid_endpoint_never_overwrites_saved_config(tmp_path, url):
    store = ServiceConfigStore(tmp_path)
    store.save(configured())
    before = store.path.read_bytes()
    with pytest.raises(ValueError):
        store.save(configured() | {"LLM_BASE_URL": url})
    assert store.path.read_bytes() == before


def test_local_models_allowed_and_shareable_presets_exclude_private_values():
    values = validate_config(configured() | {"LLM_BASE_URL": "http://localhost:11434/v1", "WEATHER_CITY": "private-city"})
    exported = public_template(values)
    assert "private-key" not in exported and "private-city" not in exported
    assert json.loads(exported)["TEXT_MODEL_NAME"] == "example"


class FakeSession:
    def __init__(self, payloads=(), status=200):
        self.payloads = list(payloads)
        self.status = status
        self.calls = []

    def response(self):
        value = self.payloads.pop(0) if self.payloads else {}
        return SimpleNamespace(status_code=self.status, json=lambda: value, raise_for_status=lambda: None)

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response()

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response()


def test_location_is_opt_in_and_city_geocoding_is_used_and_cached():
    session = FakeSession([{"status": "1", "geocodes": [{"adcode": "330100"}]},
                           {"status": "1", "lives": [{"city": "杭州市", "weather": "晴", "temperature": "20", "humidity": "60"}]}])
    client = WeatherClient(RuntimeSettings("demo", "", ""), "private-weather", session)
    assert not client.locate().available
    assert client.locate().reason == "location_disabled"
    assert client.weather().reason == "missing_city"
    assert not session.calls
    assert client.weather("浙江省杭州市").available
    assert client.weather("浙江省杭州市").city == "杭州市"
    assert len(session.calls) == 2
    assert session.calls[1][1]["params"]["city"] == "330100"
    assert not any(url.endswith("/ip") for url, _ in session.calls)


def test_open_meteo_works_without_key_and_shows_resolved_location():
    session = FakeSession([{"results": [{"name": "杭州", "admin1": "浙江", "country": "中国", "latitude": 30, "longitude": 120}]},
                           {"current": {"temperature_2m": 21.5, "relative_humidity_2m": 60, "weather_code": 0}}])
    client = WeatherClient(RuntimeSettings("demo", "", "", weather_provider="open-meteo"), session=session)
    result = client.weather("杭州")
    assert result.available and result.temperature_c == 21.5
    assert "浙江" in result.city and "Open-Meteo" in result.summary
    assert all("key" not in kwargs["params"] for _, kwargs in session.calls)


@pytest.mark.parametrize("code,humidity", [(4, 60), (200, 60), (0, 101), (0, -1)])
def test_open_meteo_rejects_unknown_weather_codes_and_invalid_humidity(code, humidity):
    session = FakeSession([{"results": [{"name": "杭州", "latitude": 30, "longitude": 120}]},
                           {"current": {"temperature_2m": 21.5, "relative_humidity_2m": humidity,
                                        "weather_code": code}}])
    client = WeatherClient(RuntimeSettings("demo", "", "", weather_provider="open-meteo"), session=session)
    result = client.weather("杭州")
    assert not result.available and result.reason == "invalid_response"


def test_model_probe_sends_minimal_request_and_redacts_error():
    session = FakeSession(status=401)
    result = check_service("text", configured(), session)
    assert not result["ok"] and "401" in result["message"]
    assert "private-key" not in str(result)
    assert session.calls[0][1]["allow_redirects"] is False
    assert session.calls[0][1]["json"]["max_tokens"] == 600


def test_probe_distinguishes_connected_but_exhausted_output_from_transport_failure():
    session = FakeSession([{"choices": [{"finish_reason": "length", "message": {
        "content": "", "reasoning_content": "synthetic reasoning"}}]}])
    result = check_service("text", configured(), session)
    assert not result["ok"] and result["reason"] == "output_budget_exhausted"
    assert "已连接" in result["message"]


@pytest.mark.parametrize("kind,prefix,model,response", [
    ("text", "LLM", "TEXT_MODEL_NAME", {"choices": [{"message": {"content": "OK"}}]}),
    ("vision", "VISION", "VISION_MODEL_NAME", {"choices": [{"message": {"content": "blue"}}]}),
    ("embedding", "EMBEDDING", "EMBEDDING_MODEL_NAME", {"data": [{"embedding": [0.1, 0.2]}]}),
])
def test_capability_specific_model_probe(kind, prefix, model, response):
    values = dict(DEFAULTS) | {prefix + "_API_KEY": "secret", model: "model"}
    session = FakeSession([response])
    assert check_service(kind, values, session)["ok"]
    if kind == "vision":
        content = session.calls[0][1]["json"]["messages"][0]["content"]
        assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
