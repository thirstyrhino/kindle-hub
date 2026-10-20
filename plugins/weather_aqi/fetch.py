"""Weather + air quality from Open-Meteo (free, no API key).

Now, the next 24 hours at 3-hour steps (temperature, rain chance), the next days, and US AQI.
"""
from datetime import date, datetime, timedelta

from core import fmt

FORECAST = "https://api.open-meteo.com/v1/forecast"
OUTLOOK_STEP = 3      # hours between points in the outlook
OUTLOOK_POINTS = 8    # 8 x 3 h = the next 24 hours
AIR = "https://air-quality-api.open-meteo.com/v1/air-quality"


def fetch(ctx):
    loc = ctx.cfg["location"]
    tz = ctx.cfg.get("timezone", "Asia/Kolkata")
    if ctx.demo:
        fc, aq = ctx.fixture("open_meteo_forecast.json"), ctx.fixture("open_meteo_air.json")
    else:
        fc = ctx.get_json(FORECAST, params={
            "latitude": loc["latitude"], "longitude": loc["longitude"], "timezone": tz, "forecast_days": 4,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day",
            "hourly": "temperature_2m,precipitation_probability,weather_code,is_day",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
        })
        try:
            aq = ctx.get_json(AIR, params={"latitude": loc["latitude"], "longitude": loc["longitude"],
                                           "timezone": tz, "current": "us_aqi,pm2_5,pm10"})
        except Exception as e:  # weather still useful without AQI
            ctx.log(f"air quality unavailable: {e}")
            aq = {}

    if ctx.demo:
        fc = _rebase(fc, ctx.now.date())
    cur, daily = fc["current"], fc["daily"]
    label, icon = fmt.weather(cur.get("weather_code"), cur.get("is_day", 1) != 0)
    days = []
    for i, day in enumerate(daily["time"]):
        d_label, d_icon = fmt.weather(daily["weather_code"][i])
        days.append({
            "name": "Today" if i == 0 else date.fromisoformat(day).strftime("%a"),
            "high": round(daily["temperature_2m_max"][i]),
            "low": round(daily["temperature_2m_min"][i]),
            "rain": daily["precipitation_probability_max"][i],
            "label": d_label,
            "icon_svg": fmt.icon_svg(d_icon, 52),
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
            "icon_svg": fmt.icon_svg(icon, 70),
        },
        "outlook": (outlook := _outlook(fc.get("hourly") or {}, ctx.now, str(ctx.cfg.get("clock", "12h")))),
        "chart_svg": fmt.hourly_chart(outlook),
        "today": days[0],
        "forecast": days[:4],
        "sunrise": daily["sunrise"][0][-5:],
        "sunset": daily["sunset"][0][-5:],
        "aqi": {**band,
                "pm25": round(aq_cur["pm2_5"]) if aq_cur.get("pm2_5") is not None else None,
                "pm10": round(aq_cur["pm10"]) if aq_cur.get("pm10") is not None else None},
    }


def _hour_label(t: datetime, clock: str) -> str:
    if clock == "24h":
        return t.strftime("%H:%M")
    return t.strftime("%I %p").lstrip("0")


def _outlook(hourly: dict, now: datetime, clock: str) -> list[dict]:
    """The next OUTLOOK_POINTS hours on the OUTLOOK_STEP grid (21:00, 00:00, 03:00...) after now."""
    times = hourly.get("time") or []
    local_now = now.replace(tzinfo=None)
    points = []
    for i, ts in enumerate(times):
        try:
            t = datetime.fromisoformat(ts)
            temp = hourly["temperature_2m"][i]
        except (ValueError, KeyError, IndexError):
            continue
        if t <= local_now or t.hour % OUTLOOK_STEP or temp is None:
            continue
        is_day = (hourly.get("is_day") or [1] * len(times))[i] != 0
        rain = (hourly.get("precipitation_probability") or [None] * len(times))[i]
        points.append({
            "label": _hour_label(t, clock),
            "temp": round(temp),
            "rain": int(rain) if rain is not None else 0,
            "icon": fmt.weather((hourly.get("weather_code") or [None] * len(times))[i], is_day)[1],
        })
        if len(points) == OUTLOOK_POINTS:
            break
    return points


def _rebase(fc: dict, today: date) -> dict:
    """Demo data: move the fixture's dates to today, so the outlook lines up with any --at time."""
    first = date.fromisoformat(fc["daily"]["time"][0])
    shift = timedelta(days=(today - first).days)
    if not shift:
        return fc

    def move(ts: str) -> str:
        if "T" in ts:
            return (datetime.fromisoformat(ts) + shift).strftime("%Y-%m-%dT%H:%M")
        return (date.fromisoformat(ts) + shift).isoformat()

    out = {**fc, "daily": {**fc["daily"]}}
    for key in ("time", "sunrise", "sunset"):
        out["daily"][key] = [move(t) for t in fc["daily"][key]]
    if fc.get("hourly"):
        out["hourly"] = {**fc["hourly"], "time": [move(t) for t in fc["hourly"]["time"]]}
    return out


def tile(data):
    """Summary for the Kindle Hub card on Bookshelf's home screen."""
    now, today, aqi = data["now"], data["today"], data.get("aqi") or {}
    return {
        "heading": data["location"],
        "value": f"{now['temp']}°",
        "suffix": now["label"],
        "sub": f"↑{today['high']}° ↓{today['low']}° · rain {today['rain']}%",
        "context": f"AQI {aqi['value']} · {aqi['label']}" if aqi.get("value") is not None else None,
    }
