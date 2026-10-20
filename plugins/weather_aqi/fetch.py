"""Weather + air quality from Open-Meteo (free, no API key)."""
from datetime import date

from core import fmt

FORECAST = "https://api.open-meteo.com/v1/forecast"
AIR = "https://air-quality-api.open-meteo.com/v1/air-quality"


def fetch(ctx):
    loc = ctx.cfg["location"]
    tz = ctx.cfg.get("timezone", "Asia/Kolkata")
    if ctx.demo:
        fc, aq = ctx.fixture("open_meteo_forecast.json"), ctx.fixture("open_meteo_air.json")
    else:
        fc = ctx.get_json(FORECAST, params={
            "latitude": loc["latitude"], "longitude": loc["longitude"], "timezone": tz, "forecast_days": 4,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
        })
        try:
            aq = ctx.get_json(AIR, params={"latitude": loc["latitude"], "longitude": loc["longitude"],
                                           "timezone": tz, "current": "us_aqi,pm2_5,pm10"})
        except Exception as e:  # weather still useful without AQI
            ctx.log(f"air quality unavailable: {e}")
            aq = {}

    cur, daily = fc["current"], fc["daily"]
    label, icon = fmt.weather(cur.get("weather_code"))
    days = []
    for i, day in enumerate(daily["time"]):
        d_label, d_icon = fmt.weather(daily["weather_code"][i])
        days.append({
            "name": "Today" if i == 0 else date.fromisoformat(day).strftime("%a"),
            "high": round(daily["temperature_2m_max"][i]),
            "low": round(daily["temperature_2m_min"][i]),
            "rain": daily["precipitation_probability_max"][i],
            "label": d_label,
            "icon_svg": fmt.icon_svg(d_icon, 44),
        })
    aq_cur = (aq or {}).get("current", {})
    band = fmt.aqi_band(aq_cur.get("us_aqi"))
    return {
        "available": True,
        "location": loc["name"],
        "now": {
            "temp": round(cur["temperature_2m"]),
            "feels": round(cur["apparent_temperature"]),
            "humidity": round(cur["relative_humidity_2m"]),
            "wind": round(cur["wind_speed_10m"]),
            "label": label,
            "icon_svg": fmt.icon_svg(icon, 120),
        },
        "today": days[0],
        "forecast": days[:4],
        "sunrise": daily["sunrise"][0][-5:],
        "sunset": daily["sunset"][0][-5:],
        "aqi": {**band,
                "pm25": round(aq_cur["pm2_5"]) if aq_cur.get("pm2_5") is not None else None,
                "pm10": round(aq_cur["pm10"]) if aq_cur.get("pm10") is not None else None},
    }
