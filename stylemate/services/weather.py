"""Selectable weather with explicit city selection and opt-in IP location."""
import math
import time

import requests

from stylemate.agent.tools.location_weather import AmapClient, LocationResult, WeatherResult


class WeatherClient:
    def __init__(self, settings, api_key="", session=None):
        self.settings = settings
        self.session = session or requests.Session()
        self.amap = AmapClient(api_key, settings.weather_timeout_seconds, self.session)
        self.cache = {}

    def locate(self):
        if not self.settings.allow_ip_location or self.settings.weather_provider != "amap":
            return LocationResult(available=False, reason="location_disabled")
        return self.amap.locate()

    def weather(self, city_or_adcode=""):
        provider = self.settings.weather_provider
        city = city_or_adcode.strip() or self.settings.weather_city.strip()
        if provider == "disabled":
            return WeatherResult(available=False, reason="disabled")
        if not city and provider == "amap" and self.settings.allow_ip_location:
            return self.amap.weather()
        if not city:
            return WeatherResult(available=False, reason="missing_city")
        cached = self.cache.get((provider, city))
        if cached and time.monotonic() - cached[0] < 600:
            return cached[1]
        try:
            if provider == "amap":
                if not self.amap.api_key:
                    return WeatherResult(available=False, reason="missing_key")
                adcode = city
                if not (city.isdigit() and len(city) == 6):
                    data, reason = self.amap._get("geocode/geo", {"address": city})
                    if data is None:
                        return WeatherResult(available=False, reason=reason)
                    matches = data.get("geocodes", [])
                    if not matches or not isinstance(matches[0], dict) or not matches[0].get("adcode"):
                        return WeatherResult(available=False, reason="invalid_response")
                    adcode = str(matches[0]["adcode"])
                result = self.amap.weather(adcode)
            elif provider == "open-meteo":
                result = self._open_meteo(city)
            else:
                return WeatherResult(available=False, reason="invalid_response")
        except requests.Timeout:
            return WeatherResult(available=False, reason="timeout")
        except (requests.RequestException, ValueError, TypeError, KeyError, IndexError, AttributeError):
            return WeatherResult(available=False, reason="upstream_error")
        if result.available:
            self.cache[(provider, city)] = (time.monotonic(), result)
        return result

    def _get(self, url, params):
        response = self.session.get(url, params=params, timeout=self.settings.weather_timeout_seconds)
        response.raise_for_status()
        return response.json()

    def _open_meteo(self, city):
        # No IP lookup: the user selects a city. GeoNames names disambiguate the result.
        locations = self._get("https://geocoding-api.open-meteo.com/v1/search",
                              {"name": city, "count": 1, "language": "zh", "format": "json"}).get("results", [])
        if not locations:
            return WeatherResult(available=False, reason="invalid_response")
        location = locations[0]
        data = self._get("https://api.open-meteo.com/v1/forecast", {
            "latitude": location["latitude"], "longitude": location["longitude"],
            "current": "temperature_2m,relative_humidity_2m,weather_code", "timezone": "auto",
        })["current"]
        temperature = float(data["temperature_2m"])
        if not math.isfinite(temperature):
            return WeatherResult(available=False, reason="invalid_response")
        code = int(data["weather_code"])
        summary = ("晴" if code == 0 else "多云" if code <= 3 else "雾" if code <= 48 else
                   "雪" if code in {71, 73, 75, 77, 85, 86} else "雷雨" if code >= 95 else "雨")
        name = " / ".join(str(location[key]) for key in ("name", "admin1", "country") if location.get(key))
        return WeatherResult(available=True, city=name, summary=summary + "（Open-Meteo）",
                             temperature_c=temperature, humidity=int(data["relative_humidity_2m"]))
