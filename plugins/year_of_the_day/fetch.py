"""Year of the Day: one year in history picked from Wikipedia's "On this day" events for today's date.

Equivalent of TRMNL's "Year of the Day" recipe (text mode). Data: Wikimedia's free feed API, no key.
The pick is seeded by the date, so every refresh that day shows the same year.
"""
import random

from core import fmt

SOURCES = [
    "https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/events/{mm}/{dd}",
    "https://en.wikipedia.org/api/rest_v1/feed/onthisday/events/{mm}/{dd}",
]


def _year_label(y: int) -> str:
    return f"{-y} BC" if y < 0 else str(y)


def _clean(event: dict) -> dict | None:
    year, text = event.get("year"), fmt.strip_html(event.get("text", ""))
    if not isinstance(year, int) or not text:
        return None
    page = next((p for p in event.get("pages") or [] if p.get("extract")), {})
    return {"year": year, "label": _year_label(year), "text": text,
            "page": fmt.strip_html((page.get("titles") or {}).get("normalized") or page.get("title", "")),
            "extract": fmt.strip_html(page.get("extract", ""), 460)}


def _load(ctx) -> dict:
    if ctx.demo:
        return ctx.fixture("onthisday_events.json")
    mm, dd = ctx.now.strftime("%m"), ctx.now.strftime("%d")
    last = None
    for url in SOURCES:
        try:
            return ctx.get_json(url.format(mm=mm, dd=dd), retries=1)
        except Exception as e:  # try the next source
            last = e
    raise RuntimeError(f"On this day feed unavailable: {last}")


def fetch(ctx):
    events = [e for e in (_clean(x) for x in _load(ctx).get("events", [])) if e and e["year"] <= ctx.now.year]
    if not events:
        return {"available": False, "error": "no events for today"}
    rng = random.Random(ctx.today)                  # same pick for the whole day
    with_extract = [e for e in events if e["extract"]] or events
    prefer = [w.lower() for w in ctx.settings.get("prefer") or []]
    preferred = [e for e in with_extract if any(w in (e["text"] + " " + e["extract"]).lower() for w in prefer)]
    main = rng.choice(preferred or with_extract)

    rest = [e for e in events if e["year"] != main["year"]]
    rng.shuffle(rest)
    others, seen = [], {main["year"]}
    for e in rest:
        if e["year"] not in seen:
            others.append(e)
            seen.add(e["year"])
        if len(others) == int(ctx.settings.get("also_count", 3)):
            break
    return {
        "available": True,
        "date_long": ctx.now.strftime("%-d %B"),
        "main": {**main, "ago": ctx.now.year - main["year"] - (1 if main["year"] < 0 else 0)},  # no year 0
        "others": sorted(others, key=lambda e: e["year"]),
    }
