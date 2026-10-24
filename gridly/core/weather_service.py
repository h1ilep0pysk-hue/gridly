"""
core/weather_service.py
Асинхронная погода через Open-Meteo (без API-ключа).

Сервис сначала находит координаты города через geocoding-api.open-meteo.com,
затем запрашивает текущую погоду. Результаты приходят сигналом ready(key, data),
ошибки — failed(key, message). key — id виджета, чтобы один общий сервис мог
обслуживать несколько виджетов погоды.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from PyQt6.QtCore import QObject, QUrl, QUrlQuery, pyqtSignal
from PyQt6.QtNetwork import (QNetworkAccessManager, QNetworkReply,
                             QNetworkRequest)

logger = logging.getLogger("gridly.weather")

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Коды WMO: https://open-meteo.com/en/docs
WEATHER_DESCRIPTIONS = {
    0: "Ясно",
    1: "Почти ясно",
    2: "Переменная облачность",
    3: "Пасмурно",
    45: "Туман",
    48: "Изморозь",
    51: "Слабая морось",
    53: "Морось",
    55: "Сильная морось",
    56: "Ледяная морось",
    57: "Ледяная морось",
    61: "Небольшой дождь",
    63: "Дождь",
    65: "Сильный дождь",
    66: "Ледяной дождь",
    67: "Ледяной дождь",
    71: "Небольшой снег",
    73: "Снег",
    75: "Сильный снег",
    77: "Снежная крупа",
    80: "Ливень",
    81: "Ливень",
    82: "Сильный ливень",
    85: "Снегопад",
    86: "Сильный снегопад",
    95: "Гроза",
    96: "Гроза с градом",
    99: "Сильная гроза с градом",
}


def weather_icon_name(code: int, is_day: bool = True) -> str:
    """Код WMO → имя векторной иконки."""
    if not is_day and code in (0, 1):
        return "weather_moon"
    if code in (0, 1):
        return "weather_sun"
    if code in (2,):
        return "weather_partly"
    if code in (3, 45, 48):
        return "weather_cloud" if code == 3 else "weather_fog"
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return "weather_rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "weather_snow"
    if code in (95, 96, 99):
        return "weather_thunder"
    return "weather_cloud"


class WeatherService(QObject):
    ready = pyqtSignal(str, dict)
    failed = pyqtSignal(str, str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._geo_cache: dict[str, tuple[float, float, str]] = {}

    # ------------------------------------------------------------- public
    def request(self, key: str, city: str, units: str = "c") -> None:
        city = city.strip()
        if not city:
            self.failed.emit(key, "Укажите город")
            return

        units = "f" if units == "f" else "c"
        cached = self._geo_cache.get(city.casefold())
        if cached is not None:
            lat, lon, resolved = cached
            self._fetch_weather(key, lat, lon, resolved, city, units)
            return

        url = QUrl(GEOCODE_URL)
        query = QUrlQuery()
        query.addQueryItem("name", city)
        query.addQueryItem("count", "1")
        query.addQueryItem("language", "ru")
        query.addQueryItem("format", "json")
        url.setQuery(query)

        reply = self._nam.get(self._request(url))
        reply.finished.connect(
            lambda: self._on_geocode(reply, key, city, units)
        )

    def clear_cache(self) -> None:
        self._geo_cache.clear()

    # ------------------------------------------------------------ network
    @staticmethod
    def _request(url: QUrl) -> QNetworkRequest:
        request = QNetworkRequest(url)
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader,
                          "Gridly/1.0 (desktop widget)")
        request.setTransferTimeout(15000)
        return request

    @staticmethod
    def _read_json(reply: QNetworkReply) -> dict | None:
        try:
            raw = bytes(reply.readAll()).decode("utf-8", errors="replace")
            return json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            logger.error("Некорректный ответ погоды: %s", exc)
            return None

    def _on_geocode(self, reply: QNetworkReply, key: str, city: str,
                    units: str) -> None:
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                logger.warning("Geocoding: %s", reply.errorString())
                self.failed.emit(key, "Нет связи с сервисом погоды")
                return

            payload = self._read_json(reply)
            if not payload:
                self.failed.emit(key, "Сервис вернул пустой ответ")
                return

            results = payload.get("results") or []
            if not results:
                self.failed.emit(key, f"Город «{city}» не найден")
                return

            item = results[0]
            lat = float(item["latitude"])
            lon = float(item["longitude"])
            resolved = str(item.get("name") or city).strip()
            country = str(item.get("country") or "").strip()
            if country and country.casefold() not in resolved.casefold():
                resolved = f"{resolved}, {country}"

            self._geo_cache[city.casefold()] = (lat, lon, resolved)
            self._fetch_weather(key, lat, lon, resolved, city, units)
        finally:
            reply.deleteLater()

    def _fetch_weather(self, key: str, lat: float, lon: float,
                       resolved: str, query_city: str, units: str) -> None:
        url = QUrl(FORECAST_URL)
        query = QUrlQuery()
        query.addQueryItem("latitude", f"{lat:.6f}")
        query.addQueryItem("longitude", f"{lon:.6f}")
        query.addQueryItem(
            "current",
            "temperature_2m,relative_humidity_2m,apparent_temperature,"
            "is_day,weather_code,wind_speed_10m",
        )
        query.addQueryItem("timezone", "auto")
        query.addQueryItem("forecast_days", "1")
        if units == "f":
            query.addQueryItem("temperature_unit", "fahrenheit")
            query.addQueryItem("wind_speed_unit", "mph")
        else:
            query.addQueryItem("wind_speed_unit", "ms")
        url.setQuery(query)

        reply = self._nam.get(self._request(url))
        reply.finished.connect(
            lambda: self._on_weather(reply, key, resolved, query_city, units)
        )

    def _on_weather(self, reply: QNetworkReply, key: str, resolved: str,
                    query_city: str, units: str) -> None:
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                logger.warning("Forecast: %s", reply.errorString())
                self.failed.emit(key, "Нет связи с сервисом погоды")
                return

            payload = self._read_json(reply)
            if not payload:
                self.failed.emit(key, "Сервис вернул пустой ответ")
                return

            current = payload.get("current") or {}
            if "temperature_2m" not in current:
                self.failed.emit(key, "В ответе нет температуры")
                return

            code = int(current.get("weather_code", 3))
            is_day = bool(current.get("is_day", 1))
            self.ready.emit(key, {
                "temp": round(float(current["temperature_2m"])),
                "feels": round(float(current.get(
                    "apparent_temperature", current["temperature_2m"]))),
                "humidity": int(current.get("relative_humidity_2m", 0)),
                "wind": float(current.get("wind_speed_10m", 0.0)),
                "code": code,
                "is_day": is_day,
                "description": WEATHER_DESCRIPTIONS.get(code, "Облачно"),
                "icon": weather_icon_name(code, is_day),
                "city": resolved,
                "query_city": query_city,
                "units": units,
                "updated": datetime.now(),
            })
        finally:
            reply.deleteLater()
