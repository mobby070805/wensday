"""Weather plugin (Open-Meteo: free, no API key). Example of a network-scoped plugin."""
from __future__ import annotations

import httpx

from app.agent.tools import Ctx, Tool, ToolResult
from app.plugins.sdk import PluginSpec

_CODES = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "foggy", 48: "foggy", 51: "drizzle", 53: "drizzle",
          55: "drizzle", 61: "light rain", 63: "rain", 65: "heavy rain", 80: "showers", 81: "showers", 82: "heavy showers", 95: "thunderstorm"}
_TG = {"clear": "clear ah", "mostly clear": "mostly clear", "partly cloudy": "konjam mugam", "overcast": "mugam moottam", "foggy": "pani mootam",
       "drizzle": "thooral", "light rain": "lesa mazhai", "rain": "mazhai", "heavy rain": "romba mazhai", "showers": "mazhai", "heavy showers": "romba mazhai",
       "thunderstorm": "idi mazhai"}
_TA = {"clear": "தெளிவான வானம்", "mostly clear": "பெரும்பாலும் தெளிவு", "partly cloudy": "லேசான மேகமூட்டம்", "overcast": "மேகமூட்டம்", "foggy": "பனிமூட்டம்",
       "drizzle": "தூறல்", "light rain": "லேசான மழை", "rain": "மழை", "heavy rain": "கனமழை", "showers": "மழை", "heavy showers": "கனமழை", "thunderstorm": "இடியுடன் கூடிய மழை"}


async def get_weather(ctx: Ctx, a: dict) -> ToolResult:
    city = a.get("city") or ctx.extra.get("plugin_config", {}).get("weather", {}).get("city") or "Chennai"
    http: httpx.AsyncClient = ctx.http
    try:
        g = (await http.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": city, "count": 1}, timeout=10)).json()
        place = g["results"][0]
        w = (await http.get("https://api.open-meteo.com/v1/forecast", timeout=10, params={
            "latitude": place["latitude"], "longitude": place["longitude"], "current": "temperature_2m,weather_code"})).json()["current"]
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        return ToolResult(False, error="weather service unavailable")
    desc = _CODES.get(w["weather_code"], "unsettled")
    temp = round(w["temperature_2m"])
    name = place["name"]
    summary = {"en": f"It's {temp}°C and {desc} in {name}.",
               "tg": f"{name} la ippo {temp}°C, {_TG.get(desc, desc)}.",
               "ta": f"{name} இல் இப்போது {temp}°C, {_TA.get(desc, desc)}."}[ctx.style]
    return ToolResult(data={"city": name, "temp_c": temp, "condition": desc, "summary": summary})


PLUGIN = PluginSpec(
    name="weather", version="1.0.0", description="Current weather via Open-Meteo.", scopes=["net:fetch"],
    tools=[Tool("get_weather", "Get the current weather for a city (defaults to the user's configured city).",
                {"type": "object", "properties": {"city": {"type": "string"}}, "required": []}, get_weather, frozenset({"net:fetch"}))],
)
