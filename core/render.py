"""Render plugin templates to Kindle-ready PNGs (exact panel size, 16-level greyscale)."""
from __future__ import annotations

import html
from pathlib import Path

from liquid import Environment
from PIL import Image

from .context import ROOT, Context
from .plugins import Plugin

ENV = Environment()
FONTS = [  # family, file, weight
    ("Inter", "Inter-Regular.otf", 400), ("Inter", "Inter-Medium.otf", 500),
    ("Inter", "Inter-SemiBold.otf", 600), ("Inter", "Inter-Bold.otf", 700),
    ("Inter Display", "InterDisplay-SemiBold.otf", 600), ("Inter Display", "InterDisplay-Bold.otf", 700),
]
GLYPHS = {  # small title-bar icons
    "morning_brief": '<svg class="glyph" viewBox="0 0 26 26"><rect x="3" y="4" width="20" height="18" fill="none" stroke="#000" stroke-width="3"/><line x1="7" y1="10" x2="19" y2="10" stroke="#000" stroke-width="3"/><line x1="7" y1="15" x2="15" y2="15" stroke="#000" stroke-width="3"/></svg>',
    "weather_aqi": '<svg class="glyph" viewBox="0 0 26 26"><circle cx="13" cy="13" r="6" fill="none" stroke="#000" stroke-width="3"/><g stroke="#000" stroke-width="3" stroke-linecap="round"><line x1="13" y1="1.5" x2="13" y2="4"/><line x1="13" y1="22" x2="13" y2="24.5"/><line x1="1.5" y1="13" x2="4" y2="13"/><line x1="22" y1="13" x2="24.5" y2="13"/></g></svg>',
    "quarter_progress": '<svg class="glyph" viewBox="0 0 26 26"><g fill="#000"><rect x="2" y="2" width="6" height="6"/><rect x="10" y="2" width="6" height="6"/><rect x="18" y="2" width="6" height="6"/><rect x="2" y="10" width="6" height="6"/><rect x="10" y="10" width="6" height="6"/></g><g fill="none" stroke="#000" stroke-width="2"><rect x="19" y="11" width="4" height="4"/><rect x="3" y="19" width="4" height="4"/><rect x="11" y="19" width="4" height="4"/><rect x="19" y="19" width="4" height="4"/></g></svg>',
    "markets": '<svg class="glyph" viewBox="0 0 26 26"><polyline points="2,20 9,12 14,16 24,5" fill="none" stroke="#000" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/></svg>',
}


# Drop trailing [data-fit-item] children until their [data-fit] container stops overflowing,
# so lists end on a whole item instead of a clipped line (like TRMNL's overflow engine).
FIT_JS = """() => {
  for (const box of document.querySelectorAll('[data-fit]')) {
    const items = () => Array.from(box.querySelectorAll(':scope > [data-fit-item]'));
    while (box.scrollHeight > box.clientHeight + 1 && items().length > 1) items().at(-1).remove();
  }
}"""


def _font_css() -> str:
    rules = []
    for family, file, weight in FONTS:
        url = (ROOT / "assets" / "fonts" / file).as_uri()
        rules.append(f'@font-face{{font-family:"{family}";src:url("{url}");font-weight:{weight};}}')
    return "\n".join(rules)


def screen_vars(ctx: Context, plugin: Plugin, data: dict) -> dict:
    return {
        **data,
        "meta": {
            "title": plugin.title,
            "glyph": GLYPHS.get(plugin.name, GLYPHS["morning_brief"]),
            "updated": ctx.now.strftime("%H:%M"),
            "date_short": ctx.now.strftime("%a %d %b"),
            "date_long": ctx.now.strftime("%A, %d %B"),
            "location": ctx.cfg["location"]["name"],
        },
        "weather": ctx.usable("weather_aqi"),
    }


def screen_html(ctx: Context, plugin: Plugin, data: dict) -> str:
    w, h = ctx.cfg["screen"]["width"], ctx.cfg["screen"]["height"]
    markup = ENV.from_string(plugin.template).render(**screen_vars(ctx, plugin, data))
    css = (ROOT / "templates" / "screen.css").read_text(encoding="utf-8")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(plugin.title)}</title>
<style>{_font_css()}
:root{{--w:{w}px;--h:{h}px}}
{css}</style></head>
<body><div class="screen"><div class="view view--full">{markup}</div></div></body></html>"""


def render_pngs(ctx: Context, jobs: list[tuple[Plugin, dict]], out_dir: Path) -> dict[str, Path]:
    """Screenshot each screen with headless Chromium, then convert to 16-level greyscale."""
    from playwright.sync_api import sync_playwright

    w, h = ctx.cfg["screen"]["width"], ctx.cfg["screen"]["height"]
    work = ROOT / "build" / "render"
    work.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
        for plugin, data in jobs:
            src = work / f"{plugin.name}.html"
            src.write_text(screen_html(ctx, plugin, data), encoding="utf-8")
            page.goto(src.as_uri())
            page.evaluate("document.fonts.ready")
            page.evaluate(FIT_JS)
            raw = work / f"{plugin.name}.raw.png"
            page.screenshot(path=str(raw), clip={"x": 0, "y": 0, "width": w, "height": h})
            img = Image.open(raw).convert("L")
            # Kindle panels show 16 grey levels; snapping avoids muddy dithering on device.
            img = img.point(lambda v: round(v / 17) * 17)
            dest = out_dir / f"{plugin.name}.png"
            img.save(dest, optimize=True)
            results[plugin.name] = dest
            ctx.log(f"rendered {dest.name} ({w}x{h})")
        browser.close()
    return results
