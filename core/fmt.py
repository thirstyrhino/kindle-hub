"""Small formatting helpers shared by plugins: numbers, AQI bands, weather codes, SVG bits."""
from __future__ import annotations

import html
import re


def indian(n: float, decimals: int = 2) -> str:
    """12345678.9 -> '1,23,45,678.90' (Indian digit grouping)."""
    neg = n < 0
    whole, _, frac = f"{abs(n):.{decimals}f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        head = ",".join(re.findall(r"\d{1,2}", head[::-1]))[::-1]
        whole = f"{head},{tail}"
    out = whole + (f".{frac}" if decimals else "")
    return f"-{out}" if neg else out


def strip_html(text: str, limit: int = 0) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if limit and len(text) > limit:
        text = text[: limit - 1].rsplit(" ", 1)[0] + "…"
    return text


# US EPA AQI bands (what Open-Meteo's us_aqi follows).
AQI_BANDS = [
    (50, "Good", "Air is fine for everyone."),
    (100, "Moderate", "OK for most; very sensitive people take it easy."),
    (150, "Unhealthy for sensitive groups", "Sensitive groups should cut long outdoor effort."),
    (200, "Unhealthy", "Limit long outdoor exertion."),
    (300, "Very unhealthy", "Avoid outdoor exertion."),
    (10_000, "Hazardous", "Stay indoors if you can."),
]


def aqi_band(aqi: float | None) -> dict:
    if aqi is None:
        return {"value": None, "label": "No data", "advice": "", "pct": 0}
    for limit, label, advice in AQI_BANDS:
        if aqi <= limit:
            return {"value": round(aqi), "label": label, "advice": advice,
                    "pct": max(2, min(100, round(aqi / 300 * 100)))}
    return {"value": round(aqi), "label": "Hazardous", "advice": "", "pct": 100}


# WMO weather interpretation codes -> (label, icon key)
WMO = {
    0: ("Clear", "sun"), 1: ("Mostly clear", "sun"), 2: ("Partly cloudy", "partly"), 3: ("Overcast", "cloud"),
    45: ("Fog", "fog"), 48: ("Fog", "fog"),
    51: ("Light drizzle", "drizzle"), 53: ("Drizzle", "drizzle"), 55: ("Heavy drizzle", "drizzle"),
    56: ("Freezing drizzle", "drizzle"), 57: ("Freezing drizzle", "drizzle"),
    61: ("Light rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "rain"), 67: ("Freezing rain", "rain"),
    71: ("Light snow", "cloud"), 73: ("Snow", "cloud"), 75: ("Heavy snow", "cloud"), 77: ("Snow grains", "cloud"),
    80: ("Light showers", "rain"), 81: ("Showers", "rain"), 82: ("Violent showers", "rain"),
    85: ("Snow showers", "cloud"), 86: ("Snow showers", "cloud"),
    95: ("Thunderstorm", "storm"), 96: ("Thunderstorm, hail", "storm"), 99: ("Thunderstorm, hail", "storm"),
}


def weather(code: int | None) -> tuple[str, str]:
    return WMO.get(int(code) if code is not None else -1, ("—", "cloud"))


def icon_svg(key: str, size: int = 64) -> str:
    """Bold, single-colour icons that survive 16-level e-ink."""
    s = 'stroke="#000" stroke-width="5" fill="none" stroke-linecap="round" stroke-linejoin="round"'
    cloud = '<path d="M22 70h40a16 16 0 0 0 0-32 22 22 0 0 0-42 6 13 13 0 0 0 2 26z" ' + s + "/>"
    sun_rays = "".join(
        f'<line x1="{50 + 30 * c:.1f}" y1="{50 + 30 * d:.1f}" x2="{50 + 40 * c:.1f}" y2="{50 + 40 * d:.1f}" {s}/>'
        for c, d in [(1, 0), (-1, 0), (0, 1), (0, -1), (.707, .707), (-.707, .707), (.707, -.707), (-.707, -.707)])
    shapes = {
        "sun": f'<circle cx="50" cy="50" r="18" {s}/>' + sun_rays,
        "partly": f'<circle cx="38" cy="36" r="13" {s}/>'
                  + "".join(f'<line x1="{38 + 20 * c:.1f}" y1="{36 + 20 * d:.1f}" x2="{38 + 27 * c:.1f}" y2="{36 + 27 * d:.1f}" {s}/>'
                            for c, d in [(-1, 0), (0, -1), (-.707, -.707), (.707, -.707)])
                  + '<path d="M30 80h40a14 14 0 0 0 0-28 19 19 0 0 0-36 5 11 11 0 0 0-4 23z" '
                  + s.replace('fill="none"', 'fill="#fff"') + "/>",
        "cloud": cloud,
        "fog": cloud.replace("M22 70", "M22 58").replace("0-32", "0-30")
               + f'<line x1="18" y1="78" x2="82" y2="78" {s}/><line x1="26" y1="90" x2="74" y2="90" {s}/>',
        "drizzle": cloud + "".join(
            f'<line x1="{x}" y1="82" x2="{x - 3}" y2="90" {s}/>' for x in (34, 50, 66)),
        "rain": cloud + "".join(f'<line x1="{x}" y1="80" x2="{x - 6}" y2="96" {s}/>' for x in (36, 52, 68)),
        "storm": cloud + f'<path d="M52 74l-10 14h12l-8 12" {s}/>',
    }
    body = shapes.get(key, cloud)
    return f'<svg width="{size}" height="{size}" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">{body}</svg>'


def sparkline(values: list[float], width: int = 150, height: int = 40, stroke: int = 3) -> str:
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    pad = stroke
    pts = " ".join(
        f"{pad + i * (width - 2 * pad) / (len(vals) - 1):.1f},{pad + (hi - v) * (height - 2 * pad) / span:.1f}"
        for i, v in enumerate(vals))
    last_x, last_y = pts.split(" ")[-1].split(",")
    return (f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">'
            f'<polyline points="{pts}" fill="none" stroke="#000" stroke-width="{stroke}" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
            f'<circle cx="{last_x}" cy="{last_y}" r="{stroke + 2}" fill="#000"/></svg>')
