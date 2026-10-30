"""Standalone Amap location and weather client."""

import math
from typing import Literal

import requests
from pydantic import BaseModel

_AMAP_BASE_URL = "https://restapi.amap.com/v3"
_FailureReason = Literal["", "missing_key", "timeout", "upstream_error", "invalid_response", "disabled", "location_disabled", "missing_city"]


class LocationResult(BaseModel):
    available: bool
    city: str = ""
    province: str = ""
    adcode: str = ""
    reason: _FailureReason = ""


class WeatherResult(BaseModel):
    available: bool
    city: str = ""
    summary: str = ""
    temperature_c: float | None = None
    humidity: int | None = None
    reason: _FailureReason = ""


class AmapClient:
    def __init__(
        self,
        api_key: str,
        timeout_seconds: int,
        session: requests.Session | None = None,
    ):
        self.api_key = api_key.strip()
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def locate(self) -> LocationResult:
        payload, reason = self._get("ip", {})
        if payload is None:
            return LocationResult(available=False, reason=reason)
        city = payload.get("city")
        province = payload.get("province")
        adcode = payload.get("adcode")
        if not all(isinstance(value, str) for value in (city, province, adcode)):
            return LocationResult(available=False, reason="invalid_response")
        if not city and not province and not adcode:
            return LocationResult(available=False, reason="invalid_response")
        return LocationResult(available=True, city=city, province=province, adcode=adcode)

    def weather(self, city_or_adcode: str = "") -> WeatherResult:
        city = city_or_adcode.strip()
        if not city:
            location = self.locate()
            if not location.available:
                return WeatherResult(available=False, reason=location.reason)
            city = location.adcode or location.city or location.province
        if not city:
            return WeatherResult(available=False, reason="invalid_response")
        payload, reason = self._get(
            "weather/weatherInfo", {"city": city, "extensions": "base", "output": "JSON"}
        )
        if payload is None:
            return WeatherResult(available=False, reason=reason)
        lives = payload.get("lives")
        if not isinstance(lives, list) or not lives or not isinstance(lives[0], dict):
            return WeatherResult(available=False, reason="invalid_response")
        live = lives[0]
        summary = live.get("weather")
        result_city = live.get("city", city)
        if not isinstance(summary, str) or not summary or not isinstance(result_city, str):
            return WeatherResult(available=False, reason="invalid_response")
        temperature = self._as_float(live.get("temperature"))
        humidity = self._as_int(live.get("humidity"))
        if temperature is None or not math.isfinite(temperature) or (humidity is not None and not 0 <= humidity <= 100):
            return WeatherResult(available=False, reason="invalid_response")
        return WeatherResult(
            available=True,
            city=result_city,
            summary=summary,
            temperature_c=temperature,
            humidity=humidity,
        )

    def _get(self, path: str, params: dict[str, str]) -> tuple[dict | None, _FailureReason]:
        if not self.api_key:
            return None, "missing_key"
        try:
            response = self.session.get(
                f"{_AMAP_BASE_URL}/{path}",
                params={"key": self.api_key, **params},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.Timeout:
            return None, "timeout"
        except (requests.RequestException, ValueError):
            return None, "upstream_error"
        if not isinstance(payload, dict):
            return None, "invalid_response"
        if payload.get("status") != "1":
            return None, "upstream_error"
        return payload, ""

    @staticmethod
    def _as_float(value: object) -> float | None:
        try:
            return float(value) if value not in (None, "") else None
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _as_int(value: object) -> int | None:
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError, OverflowError):
            return None
