import pytest

from stylemate.agent.tools.location_weather import AmapClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, *, params, timeout):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return FakeResponse(self.payload)


def test_amap_weather_uses_configured_timeout():
    fake_http = FakeSession(
        {"status": "1", "lives": [{"city": "杭州", "weather": "晴", "temperature": "28"}]}
    )

    result = AmapClient("amap-test", 5, fake_http).weather("杭州")

    assert result.available is True
    assert result.city == "杭州"
    assert result.summary == "晴"
    assert result.temperature_c == 28.0
    assert fake_http.calls[0]["timeout"] == 5


def test_missing_amap_key_returns_configuration_result_without_http():
    result = AmapClient("", 5).locate()

    assert result.available is False
    assert result.reason == "missing_key"


@pytest.mark.parametrize("temperature,humidity", [("NaN", "50"), ("inf", "50"), ("", "50"), ("25", "120")])
def test_invalid_weather_observations_do_not_become_outfit_inputs(temperature, humidity):
    session = FakeSession({"status": "1", "lives": [{"city": "杭州", "weather": "晴",
                                                      "temperature": temperature, "humidity": humidity}]})
    result = AmapClient("test", 5, session).weather("杭州")
    assert not result.available and result.reason == "invalid_response"
