"""AI morning brief: headlines from your feeds + weather + markets, written up by an OpenRouter model.

Runs the model once a day ("full" mode). Hourly refreshes reuse today's brief from the live site.
If the model is unavailable, a plain brief is built from the headlines so the Kindle never goes blank.
"""
from email.utils import format_datetime
from pathlib import Path

import feedparser

from core import fmt, llm
from core.feed import write_feed

SYSTEM = (
    "You write a crisp morning brief for one reader, read on a small e-ink screen. "
    "Plain words, no hype, no emojis. Only use the stories you are given and refer to them by id; "
    "never invent facts, numbers or links. Reply with a single JSON object and nothing else."
)


def collect_headlines(ctx):
    per_feed = int(ctx.cfg.get("max_headlines_per_feed", 12))
    items = []
    for feed in ctx.cfg.get("feeds", []):
        try:
            raw = ctx.fixture(f"feed_{feed['name'].lower().replace(' ', '_')}.xml") if ctx.demo \
                else ctx.get_bytes(feed["url"], timeout=20)
            parsed = feedparser.parse(raw)
        except Exception as e:
            ctx.log(f"feed {feed['name']} failed: {e}")
            continue
        for entry in parsed.entries[:per_feed]:
            title = fmt.strip_html(entry.get("title", ""))
            if not title:
                continue
            items.append({
                "source": feed["name"],
                "title": title,
                "link": entry.get("link", ""),
                "summary": fmt.strip_html(entry.get("summary", ""), 280),
            })
    # Interleave sources so one busy feed doesn't crowd out the rest.
    by_source = {}
    for it in items:
        by_source.setdefault(it["source"], []).append(it)
    mixed = []
    while any(by_source.values()):
        for src in list(by_source):
            if by_source[src]:
                mixed.append(by_source[src].pop(0))
    for i, it in enumerate(mixed, 1):
        it["id"] = f"s{i}"
    return mixed


def _prompt(ctx, headlines, weather, markets):
    want = int(ctx.cfg.get("ai", {}).get("stories", 5))
    lines = [f"Today is {ctx.now.strftime('%A %d %B %Y')} in {ctx.cfg['location']['name']}.",
             f"Reader: {ctx.cfg.get('ai', {}).get('reader_profile', '').strip()}", ""]
    if weather:
        n, t, a = weather["now"], weather["today"], weather["aqi"]
        lines.append(f"Weather: {n['label']}, {n['temp']}°C now, high {t['high']}° low {t['low']}°, "
                     f"rain chance {t['rain']}%. AQI {a['value']} ({a['label']}).")
    if markets and markets.get("rows"):
        lines.append("Markets: " + "; ".join(f"{r['name']} {r['value']} ({r['pct']})" for r in markets["rows"]))
    lines += ["", "Stories (id | source | title | snippet):"]
    lines += [f"{h['id']} | {h['source']} | {h['title']} | {h['summary']}" for h in headlines[:45]]
    lines += ["", f"""Return JSON exactly in this shape:
{{
  "headline": "one line, max 12 words, the day's main theme for this reader",
  "summary": ["3 bullets, max 22 words each, what matters today and why"],
  "stories": [{{"id": "s3", "why": "max 25 words on why it matters to this reader"}}],
  "weather_note": "one short practical line about weather and air",
  "focus": "one short, practical nudge for the day"
}}
Pick the {want} most relevant stories for this reader, most important first."""]
    return "\n".join(lines)


def _validate(ai, headlines, want):
    by_id = {h["id"]: h for h in headlines}
    stories = []
    for s in ai.get("stories", []) or []:
        h = by_id.get(str(s.get("id", "")).strip())
        if h and h not in [x["src"] for x in stories]:
            stories.append({"src": h, "why": fmt.strip_html(str(s.get("why", "")), 220)})
    summary = [fmt.strip_html(str(b), 200) for b in (ai.get("summary") or []) if str(b).strip()][:3]
    headline = fmt.strip_html(str(ai.get("headline", "")), 110)
    if not headline or not summary or not stories:
        raise ValueError("AI brief missing headline, summary or valid stories")
    return {
        "headline": headline,
        "summary": summary,
        "stories": [{**s["src"], "why": s["why"]} for s in stories[:want]],
        "weather_note": fmt.strip_html(str(ai.get("weather_note", "")), 160),
        "focus": fmt.strip_html(str(ai.get("focus", "")), 160),
    }


def _fallback(headlines, weather, want):
    w = ""
    if weather:
        w = (f"{weather['now']['label']}, {weather['today']['low']}–{weather['today']['high']}°C, "
             f"rain {weather['today']['rain']}%. AQI {weather['aqi']['value']} ({weather['aqi']['label']}).")
    return {
        "headline": "Today's top stories",
        "summary": [h["title"] for h in headlines[:3]],
        "stories": [{**h, "why": h["summary"][:200]} for h in headlines[:want]],
        "weather_note": w,
        "focus": "",
    }


def fetch(ctx):
    if ctx.mode == "refresh":
        prev = ctx.previous_json("data/morning_brief.json")
        if prev and prev.get("date") == ctx.today:
            ctx.log("morning_brief: reusing today's brief")
            return prev
        ctx.log("morning_brief: no brief for today yet, generating one")

    headlines = collect_headlines(ctx)
    weather, markets = ctx.usable("weather_aqi"), ctx.usable("markets")
    want = int(ctx.cfg.get("ai", {}).get("stories", 5))
    if not headlines:
        return {"available": bool(weather), "date": ctx.today, "ai": False, "model": None,
                **_fallback([], weather, want)}

    if ctx.demo:
        ai, model = ctx.fixture("llm_brief.json"), "demo/fixture"
    else:
        ai, model = llm.generate_json(ctx, SYSTEM, _prompt(ctx, headlines, weather, markets))
    brief = None
    if ai:
        try:
            brief = _validate(ai, headlines, want)
        except ValueError as e:
            ctx.log(f"morning_brief: AI output rejected ({e}); using fallback")
    used_ai = brief is not None
    brief = brief or _fallback(headlines, weather, want)
    return {
        "available": True,
        "date": ctx.today,
        "date_long": ctx.now.strftime("%A, %d %B %Y"),
        "generated_at": ctx.now.strftime("%H:%M"),
        "pub_date": format_datetime(ctx.now),
        "ai": used_ai,
        "model": model if used_ai else None,
        "markets": (markets or {}).get("rows", []),
        **brief,
    }


def publish(ctx, data, site_dir: Path):
    """Write the KOReader feed (brief.xml) and the dated archive pages."""
    write_feed(ctx, data, site_dir)
