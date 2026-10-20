#!/usr/bin/env python3
"""Regenerate the README images from the real templates and the demo data.

  python tools/docs_images.py

Writes docs/images/*.png. Run it after changing a template so the README stays accurate.
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
TMP = ROOT / "build" / "docs"
SCREENS = [("morning_brief", "Morning brief", "05:30–10:00"),
           ("weather_aqi", "Weather & air", "10:00–13:00 · evenings"),
           ("markets", "Markets", "13:00–16:00"),
           ("quarter_progress", "Quarter progress", "evenings"),
           ("year_of_the_day", "Year of the day", "11:00 · overnight")]
HERO = ["morning_brief", "weather_aqi", "quarter_progress", "year_of_the_day"]  # 4 fit the README width


def run_build(out: str, at: str, extra_env: dict | None = None) -> Path:
    env = {**os.environ, **(extra_env or {})}
    subprocess.run([sys.executable, "build.py", "--demo", "--at", at, "--out", out],
                   cwd=ROOT, env=env, check=True, capture_output=True)
    return ROOT / out


def data_uri(p: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()


def device(png: Path, caption: str = "", sub: str = "", scale: float = 1.0) -> str:
    w, h = int(600 * scale), int(800 * scale)
    cap = (f'<div class="cap"><b>{caption}</b><span>{sub}</span></div>' if caption else "")
    return (f'<div class="unit"><div class="bezel">'
            f'<img src="{data_uri(png)}" width="{w}" height="{h}"></div>{cap}</div>')


PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
@font-face{{font-family:Inter;src:url("{font}");font-weight:400 800}}
@font-face{{font-family:Inter;src:url("{font_b}");font-weight:700}}
body{{margin:0;background:#ebe7e0;font-family:Inter,sans-serif;color:#1d1b18}}
.stage{{display:flex;gap:{gap}px;justify-content:center;align-items:flex-start;padding:{pad}px}}
.unit{{display:flex;flex-direction:column;align-items:center;gap:22px}}
.bezel{{background:#2a2928;border-radius:30px;padding:30px 30px 60px;box-shadow:0 22px 50px rgba(40,30,20,.28),inset 0 0 0 2px #3a3937}}
.bezel img{{display:block;border-radius:3px;image-rendering:auto;background:#fff}}
.cap{{display:flex;flex-direction:column;align-items:center;gap:4px}}
.cap b{{font-size:26px;letter-spacing:-.01em}} .cap span{{font-size:19px;color:#6b665f}}
</style></head><body><div class="stage">{body}</div></body></html>"""


def shoot(html: str, dest: Path, width: int) -> None:
    src = TMP / (dest.stem + ".html")
    src.write_text(html, encoding="utf-8")
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": width, "height": 400}, device_scale_factor=1)
        pg.goto(src.as_uri())
        pg.evaluate("document.fonts.ready")
        pg.locator(".stage").screenshot(path=str(dest))
        b.close()
    # README images: keep them light
    Image.open(dest).convert("RGB").save(dest, optimize=True)


def main() -> None:
    shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True)
    OUT.mkdir(parents=True, exist_ok=True)
    fonts = ROOT / "assets" / "fonts"
    page = lambda body, gap=70, pad=70: PAGE.format(  # noqa: E731
        font=(fonts / "Inter-Medium.otf").as_uri(), font_b=(fonts / "Inter-Bold.otf").as_uri(),
        body=body, gap=gap, pad=pad)

    site = run_build("build/docs/site", "07:00")
    screens = {name: site / "screens" / f"{name}.png" for name, _, _ in SCREENS}

    # 1. Hero: three devices side by side
    shoot(page("".join(device(screens[n], t, s, scale=0.75) for n, t, s in SCREENS if n in HERO), gap=54, pad=60),
          OUT / "hero.png", 2400)

    # 2. Raw screens exactly as the Kindle gets them (600x800, 16 greys)
    for name, _, _ in SCREENS:
        shutil.copyfile(screens[name], OUT / f"screen-{name}.png")

    # 3. Fallback brief: what you get with no API key or when the AI fails
    fb = TMP / "fixtures"
    shutil.copytree(ROOT / "fixtures", fb)
    (fb / "demo" / "llm_brief.json").write_text('{"unusable": true}')
    real = ROOT / "fixtures"
    backup = ROOT / "build" / "fixtures.bak"
    shutil.move(real, backup)
    try:
        shutil.copytree(fb, real)
        fsite = run_build("build/docs/fallback", "07:00")
    finally:
        shutil.rmtree(real)
        shutil.move(backup, real)
    shutil.copyfile(fsite / "screens" / "morning_brief.png", OUT / "screen-morning_brief-fallback.png")

    # 4. The site's index page
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 1100, "height": 900}, device_scale_factor=1)
        pg.goto((site / "index.html").as_uri())
        pg.wait_for_timeout(300)
        pg.locator("main").screenshot(path=str(OUT / "site-index.png"))
        b.close()
    Image.open(OUT / "site-index.png").convert("RGB").save(OUT / "site-index.png", optimize=True)

    shutil.rmtree(ROOT / "build", ignore_errors=True)
    for p in sorted(OUT.glob("*.png")):
        print(f"{p.relative_to(ROOT)}  {Image.open(p).size}  {p.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
