"""Year of the Day: one year in history picked from Wikipedia's "On this day" events for today's date.

Equivalent of TRMNL's "Year of the Day" recipe. Data: Wikimedia's free feed API, no key.
The pick is seeded by the date, so every refresh that day shows the same year.

Modes (plugin.yaml `settings.mode`):
  text       year, what happened, background, other years
  comic      an AI comic-panel illustration of the event, with the year and headline
  newspaper  the same, drawn as a vintage newspaper halftone illustration
Image modes use Cloudflare Workers AI (free daily allowance). The image is made once a day
and reused by the hourly refreshes. Without Cloudflare keys, or if generation fails, the
screen falls back to text mode.
"""
import random
import re
import shutil
from pathlib import Path

from core import fmt, imagegen, llm
from core.context import ROOT

SOURCES = [
    "https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/events/{mm}/{dd}",
    "https://en.wikipedia.org/api/rest_v1/feed/onthisday/events/{mm}/{dd}",
]
IMAGE_W, IMAGE_H = 576, 530
SITE_IMAGE = "img/year_of_the_day.png"
# Image modes skip events built around a death or an attack: a drawing of those reads badly.
GRIM = re.compile(r"\b(kill|killed|killing|assassinat\w*|massacre\w*|murder\w*|execut\w*|bomb\w*|terror\w*|"
                  r"shot|shooting|dies|died|death|genocide|suicide|hanged|beheaded|crash\w*)\b", re.I)
STYLES = {
    "comic": ("Black-and-white comic book panel illustration, bold black ink outlines, cross-hatching and "
              "halftone dot shading, strong contrast, large clean white areas, dramatic composition."),
    "newspaper": ("Black-and-white vintage newspaper illustration printed in coarse halftone, engraved "
                  "ink look, period-accurate details, strong contrast."),
}
RULES = ("No text, letters, numbers, captions or speech bubbles. Show places, objects, vehicles, crowds "
         "or symbols rather than close-up faces of real people. No gore.")


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


def _scene(ctx, main: dict, mode: str) -> str:
    """A visual description of the event for the image model (AI-written when a key is set)."""
    fallback = f"{main['text']} ({main['label']})."
    if ctx.demo:
        return fallback
    ai, _ = llm.generate_json(
        ctx,
        "You turn historical events into one short visual scene for an illustrator. "
        "Describe only what is seen: setting, objects, era details, mood. Reply with JSON only.",
        f"Event in {main['label']}: {main['text']}\nBackground: {main['extract']}\n"
        f"Style: {mode}. {RULES}\n"
        'Return {"scene": "one sentence, max 45 words"}', max_tokens=1500)
    scene = fmt.strip_html(str((ai or {}).get("scene", "")), 400)
    return scene or fallback


def _illustrate(ctx, main: dict, mode: str) -> Path | None:
    out = ROOT / "build" / "img" / "year_of_the_day.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    # Reuse today's picture from the live site (made by the morning run).
    prev = ctx.previous_json("data/year_of_the_day.json") or {}
    if (prev.get("date") == ctx.today and prev.get("mode") == mode and prev.get("image")
            and (prev.get("main") or {}).get("year") == main["year"]):
        raw = ctx.previous(SITE_IMAGE)
        if raw:
            out.write_bytes(raw)
            ctx.log("year_of_the_day: reusing today's illustration")
            return out
    prompt = f"{STYLES[mode]} Scene: {_scene(ctx, main, mode)} {RULES}"
    raw = imagegen.generate(ctx, prompt, model=ctx.settings.get("image_model") or imagegen.DEFAULT_MODEL)
    if not raw:
        return None
    try:
        imagegen.for_eink(raw, IMAGE_W, IMAGE_H).save(out, optimize=True)
    except Exception as e:  # not an image we can read
        ctx.log(f"year_of_the_day: could not process image: {e}")
        ctx.note("cloudflare", error=f"image unreadable: {e}")
        return None
    return out


def fetch(ctx):
    mode = str(ctx.settings.get("mode", "text")).lower()
    if mode not in ("text", *STYLES):
        mode = "text"
    events = [e for e in (_clean(x) for x in _load(ctx).get("events", [])) if e and e["year"] <= ctx.now.year]
    if not events:
        return {"available": False, "error": "no events for today"}
    rng = random.Random(ctx.today)                  # same pick for the whole day
    pool = [e for e in events if e["extract"]] or events
    if mode != "text":
        pool = [e for e in pool if not GRIM.search(e["text"])] or pool
    prefer = [w.lower() for w in ctx.settings.get("prefer") or []]
    preferred = [e for e in pool if any(w in (e["text"] + " " + e["extract"]).lower() for w in prefer)]
    main = rng.choice(preferred or pool)

    rest = [e for e in events if e["year"] != main["year"]]
    rng.shuffle(rest)
    others, seen = [], {main["year"]}
    for e in rest:
        if e["year"] not in seen:
            others.append(e)
            seen.add(e["year"])
        if len(others) == int(ctx.settings.get("also_count", 3)):
            break

    image = _illustrate(ctx, main, mode) if mode != "text" else None
    return {
        "available": True,
        "date": ctx.today,
        "mode": mode if image else "text",
        "date_long": ctx.now.strftime("%-d %B"),
        "main": {**main, "ago": ctx.now.year - main["year"] - (1 if main["year"] < 0 else 0)},  # no year 0
        "others": sorted(others, key=lambda e: e["year"]),
        "image": image.as_uri() if image else None,
        "image_w": IMAGE_W,
        "image_h": IMAGE_H,
    }


def publish(ctx, data, site_dir: Path):
    """Publish today's illustration so the hourly refreshes can reuse it."""
    if data.get("image"):
        dest = site_dir / SITE_IMAGE
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "build" / "img" / "year_of_the_day.png", dest)
