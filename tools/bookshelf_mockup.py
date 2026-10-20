#!/usr/bin/env python3
"""Mock-up of Kindle Hub cards on Bookshelf's home screen, for the README.

  python tools/bookshelf_mockup.py            # writes docs/images/bookshelf-cards.png

An approximation drawn in a browser from the demo build's real tiles (api/screens): the cards
on the Kindle are drawn by Bookshelf, which picks the exact sizes. Uses Noto Sans (KOReader's UI
font) when NOTO_SANS_DIR points at an unpacked @fontsource/noto-sans package, else Inter.
"""
from __future__ import annotations

import html
import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images" / "bookshelf-cards.png"
TMP = ROOT / "build" / "docs"


def fonts_css() -> tuple[str, str]:
    noto = os.environ.get("NOTO_SANS_DIR")
    if noto and Path(noto, "400.css").exists():
        css = "".join(f'@import url("{Path(noto, f).as_uri()}");' for f in ("400.css", "700.css", "400-italic.css"))
        return css, "'Noto Sans'"
    fonts = ROOT / "assets" / "fonts"
    css = "".join(f'@font-face{{font-family:Inter;src:url("{(fonts / f).as_uri()}");font-weight:{w}}}'
                  for f, w in (("Inter-Regular.otf", 400), ("Inter-Bold.otf", 700)))
    return css, "Inter"


def card(tile: dict, cls: str = "") -> str:
    e = html.escape
    parts = []
    if tile.get("heading"):
        parts.append(f'<div class="h">{e(tile["heading"])}</div>')
    if tile.get("value"):
        suf = f'<span class="s"> {e(tile["suffix"])}</span>' if tile.get("suffix") else ""
        parts.append(f'<div class="v">{e(tile["value"])}{suf}</div>')
    if isinstance(tile.get("bar"), (int, float)):
        parts.append(f'<div class="bar"><i style="width:{tile["bar"] * 100:.0f}%"></i></div>')
    if tile.get("sub"):
        parts.append(f'<div class="sub">{e(tile["sub"])}</div>')
    if tile.get("text"):
        parts.append(f'<div class="t">{e(tile["text"])}</div>')
    if tile.get("context"):
        parts.append(f'<div class="c">{e(tile["context"])}</div>')
    return f'<div class="card {cls}">{"".join(parts)}</div>'


CLOCK = """<div class="card sq"><svg viewBox="0 0 100 100" width="136" height="136">
{ticks}<line x1="50" y1="50" x2="50" y2="22" stroke="#000" stroke-width="2.6" stroke-linecap="round"
transform="rotate(176 50 50)"/><line x1="50" y1="50" x2="50" y2="12" stroke="#000" stroke-width="1.8"
stroke-linecap="round" transform="rotate(318 50 50)"/></svg><div class="date">Tuesday 20 October</div></div>"""


def main() -> None:
    out = ROOT / "build" / "mockup_site"
    subprocess.run([sys.executable, "build.py", "--demo", "--at", "18:00", "--out", str(out)],
                   cwd=ROOT, check=True, capture_output=True)
    tiles = {s["name"]: s["tile"] for s in json.loads((out / "api" / "screens").read_text())["screens"]}
    ticks = "".join(
        f'<line x1="50" y1="{4 if i % 3 == 0 else 7}" x2="50" y2="{13 if i % 3 == 0 else 11}" stroke="#000" '
        f'stroke-width="{2.4 if i % 3 == 0 else 1.4}" transform="rotate({i * 30} 50 50)"/>' for i in range(12))
    css, family = fonts_css()
    page = f"""<!doctype html><html><head><meta charset="utf-8"><style>{css}
*{{box-sizing:border-box}} body{{margin:0;background:#fff}}
.screen{{width:600px;height:800px;background:#fff;font-family:{family},sans-serif;color:#000;padding:0 12px;
  display:flex;flex-direction:column;gap:11px;position:relative}}
.status{{display:flex;justify-content:space-between;font-size:15px;padding:8px 2px 0;height:30px}}
.row{{display:flex;gap:11px}}
.card{{background:#eee;border:1px solid #000;border-radius:5px;padding:12px 18px;display:flex;flex-direction:column;
  justify-content:center;flex:1;min-width:0;overflow:hidden}}
.sq{{flex:0 0 190px;align-items:center;gap:6px}} .date{{font-size:15px;font-style:italic}}
.h{{font-weight:700;color:#555;font-size:21px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.v{{font-weight:700;font-size:31px;line-height:1.25;white-space:nowrap}} .s{{font-weight:400;font-size:20px}}
.bar{{height:11px;background:#ccc;margin:6px 0 4px}} .bar i{{display:block;height:100%;background:#000}}
.sub{{font-size:18px;color:#555;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.t{{font-size:22px;line-height:1.3;margin-top:4px}}
.c{{font-size:18px;font-style:italic;margin-top:3px;white-space:nowrap}}
.foot{{position:absolute;left:24px;right:24px;bottom:14px;display:flex;justify-content:space-between;font-size:30px;color:#555}}
</style></head><body><div class="screen">
<div class="status"><span>5:53 PM</span><span>Wi-Fi · 99%</span></div>
<div class="row" style="height:185px">{CLOCK.format(ticks=ticks)}{card(tiles["weather_aqi"])}</div>
<div class="row" style="height:140px">{card(tiles["quarter_progress"])}</div>
<div class="row" style="height:160px">{card(tiles["morning_brief"])}</div>
<div class="row" style="height:172px">{card(tiles["year_of_the_day"])}</div>
<div class="foot"><span>&#8801;</span><span>&#215;</span></div>
</div></body></html>"""
    TMP.mkdir(parents=True, exist_ok=True)
    src = TMP / "bookshelf_mockup.html"
    src.write_text(page, encoding="utf-8")
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 600, "height": 800}, device_scale_factor=1)
        pg.goto(src.as_uri())
        pg.evaluate("document.fonts.ready")
        pg.locator(".screen").screenshot(path=str(OUT))
        b.close()
    grey = Image.open(OUT).convert("L")
    palette = Image.new("P", (1, 1))
    palette.putpalette([v for i in range(16) for v in (i * 17,) * 3] + [0] * (768 - 48))
    grey.convert("RGB").quantize(palette=palette, dither=Image.Dither.NONE).convert("L").save(OUT, optimize=True)
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
