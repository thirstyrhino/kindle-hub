"""Write the static site: TRMNL-protocol endpoint, screens, data snapshots and an index page."""
from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

from .context import Context
from .plugins import Plugin


def write_display_endpoint(ctx: Context, on_air: Plugin, site_dir: Path) -> dict:
    """GET <base>/api/display is all the TRMNL KOReader plugin calls. It needs JSON with image_url;
    a new filename tells it the picture changed; refresh_rate (seconds) sets the next fetch."""
    site = ctx.cfg["site_url"]
    payload = {
        "status": 0,
        "image_url": f"{site}/screens/{on_air.name}.png?v={ctx.stamp}",
        "filename": f"{on_air.name}-{ctx.stamp}",
        "refresh_rate": int(ctx.cfg["screen"].get("refresh_seconds", 3600)),
        "screen": on_air.name,
    }
    api = site_dir / "api"
    api.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, indent=1)
    (api / "display").write_text(body, encoding="utf-8")        # no extension: the path the plugin requests
    (api / "display.json").write_text(body, encoding="utf-8")   # same thing, readable in a browser
    # Fixed URL of whatever is on air, for kindle-dash or any plain image fetcher.
    shutil.copyfile(site_dir / "screens" / f"{on_air.name}.png", site_dir / "screens" / "current.png")
    return payload


TILE_TEXT = {"heading": 60, "value": 24, "suffix": 40, "sub": 80, "context": 80, "text": 200}


def make_tile(ctx: Context, p: Plugin) -> dict | None:
    """A plugin's optional tile(data): the few lines the Kindle Hub card on Bookshelf's home screen
    shows. Cleaned to short strings (and a 0-1 `bar`); a broken tile is logged and left out."""
    fn = getattr(p.module, "tile", None)
    if not fn:
        return None
    try:
        raw = fn(ctx.data[p.name]) or {}
    except Exception as e:
        ctx.log(f"{p.name}: tile skipped ({type(e).__name__}: {e})")
        return None
    out = {}
    for key, limit in TILE_TEXT.items():
        v = raw.get(key)
        if v is not None and str(v).strip():
            s = " ".join(str(v).split())
            out[key] = s if len(s) <= limit else s[: limit - 1].rstrip() + "…"
    if isinstance(raw.get("bar"), (int, float)):
        out["bar"] = round(min(1.0, max(0.0, float(raw["bar"]))), 3)
    return out or None


def write_screens_list(ctx: Context, plugins: list[Plugin], rendered: dict, on_air: Plugin | None,
                       site_dir: Path, live: dict | None = None) -> None:
    """GET <base>/api/screens is what the Kindle Hub KOReader plugin lists for picking a screen,
    and what its Bookshelf card reads (each screen's `tile`)."""
    site = ctx.cfg["site_url"]
    live = live or {}
    screens = []
    for p in plugins:
        if p.name not in rendered:
            continue
        s = {"name": p.name, "title": p.title, "image_url": f"{site}/screens/{p.name}.png?v={ctx.stamp}"}
        tile = make_tile(ctx, p)
        if tile:
            s["tile"] = tile
        if p.window():
            s["window"] = p.window()           # e.g. markets: the Kindle's "take turns" skips it outside
        if live.get(p.name):
            s["live"] = live[p.name]           # e.g. the weather clock, drawn by the Kindle every minute
        screens.append(s)
    payload = {
        "updated": ctx.now.strftime("%a %d %b, %H:%M"),
        "updated_epoch": int(ctx.now.timestamp()),
        "on_air": on_air.name if on_air else None,
        "screens": screens,
    }
    api = site_dir / "api"
    api.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=1)
    (api / "screens").write_text(body, encoding="utf-8")
    (api / "screens.json").write_text(body, encoding="utf-8")


def write_data(name: str, data: dict, site_dir: Path) -> None:
    d = site_dir / "data"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def write_index(ctx: Context, plugins: list[Plugin], rendered: dict, on_air: Plugin | None,
                site_dir: Path) -> None:
    site = ctx.cfg["site_url"] or "(set site_url)"
    e = html.escape
    cards = []
    for p in plugins:
        status = "ON AIR" if on_air and p.name == on_air.name else ("unavailable" if p.name not in rendered else "")
        windows = ", ".join(p.show) or "rotation only"
        if p.days and len(p.days) < 7:
            names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            ds = sorted(p.days)
            span = f"{names[ds[0]]}–{names[ds[-1]]}" if ds == list(range(ds[0], ds[-1] + 1)) else ", ".join(names[d] for d in ds)
            windows = f"{span} {windows}"
        img = (f'<img src="screens/{p.name}.png?v={ctx.stamp}" alt="{e(p.title)} screen">'
               if p.name in rendered else '<div class="missing">No data this run</div>')
        cards.append(f'<figure>{img}<figcaption><b>{e(p.title)}</b> <span class="tag">{status}</span>'
                     f'<br><small>Shown {e(windows)} IST</small></figcaption></figure>')
    w, h = ctx.cfg["screen"]["width"], ctx.cfg["screen"]["height"]
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Kindle Hub</title>
<style>
:root{{--bg:#f4f2ee;--fg:#141414;--muted:#5d5a55;--card:#fff;--line:#d9d5ce}}
@media (prefers-color-scheme:dark){{:root{{--bg:#141414;--fg:#eee;--muted:#a8a29b;--card:#1e1e1e;--line:#333}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:28px 16px 48px}}
h1{{font-size:28px;margin:0 0 4px}} p{{color:var(--muted);margin:0 0 20px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:20px}}
figure{{margin:0;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}}
img{{width:100%;aspect-ratio:{w}/{h};display:block;border:1px solid var(--line);background:#fff}}
.missing{{aspect-ratio:{w}/{h};display:grid;place-items:center;color:var(--muted);border:1px dashed var(--line)}}
figcaption{{margin-top:10px}} .tag{{font-size:12px;font-weight:700;letter-spacing:.06em}}
dl{{display:grid;grid-template-columns:max-content 1fr;gap:6px 16px;background:var(--card);border:1px solid var(--line);
border-radius:10px;padding:16px;margin:0 0 24px}} dt{{color:var(--muted)}} dd{{margin:0;word-break:break-all}}
code{{font-size:14px}}
</style></head><body><main>
<h1>Kindle Hub</h1>
<p>Built {e(ctx.now.strftime('%a %d %b %Y, %H:%M'))} IST · {w}×{h} screens</p>
<dl>
<dt>KOReader News Downloader feed</dt><dd><code>{e(site)}/brief.xml</code></dd>
<dt>TRMNL plugin Base URL</dt><dd><code>{e(site)}</code></dd>
<dt>Current screen (plain image)</dt><dd><code>{e(site)}/screens/current.png</code></dd>
<dt>Today's brief</dt><dd><a href="briefs/{e(ctx.today)}.html">briefs/{e(ctx.today)}.html</a></dd>
</dl>
<div class="grid">{''.join(cards)}</div>
</main></body></html>"""
    (site_dir / "index.html").write_text(page, encoding="utf-8")
    (site_dir / ".nojekyll").write_text("", encoding="utf-8")
