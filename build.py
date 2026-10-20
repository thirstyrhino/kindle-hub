#!/usr/bin/env python3
"""Build the Kindle site.

  python build.py                 # full run: fetch everything, write today's AI brief, render screens
  python build.py --mode refresh  # hourly run: refresh data, reuse today's brief from the live site
  python build.py --demo          # no network, no API key: sample data, for trying templates locally
  python build.py --demo --at 14:10   # pretend it's 14:10 (see which screen is on air)
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.context import ROOT, Context, load_config  # noqa: E402
from core.plugins import load_plugins, pick_on_air  # noqa: E402
from core.publish import write_data, write_display_endpoint, write_index, write_screens_list  # noqa: E402
from core.render import render_pngs  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["full", "refresh"], default="full")
    ap.add_argument("--demo", action="store_true", help="use fixtures/demo instead of the network")
    ap.add_argument("--at", help="pretend local time is HH:MM (testing the playlist)")
    ap.add_argument("--only", nargs="*", help="build only these plugins")
    ap.add_argument("--out", default="site", help="output folder (default: site)")
    args = ap.parse_args()

    cfg = load_config()
    now = None
    if args.at:
        ctx_tmp = Context(cfg)
        now = datetime.combine(ctx_tmp.now.date(), time.fromisoformat(args.at), ctx_tmp.tz)
    ctx = Context(cfg, mode=args.mode, demo=args.demo, now=now)
    ctx.log(f"mode={ctx.mode} demo={ctx.demo} now={ctx.now:%Y-%m-%d %H:%M} site={cfg['site_url'] or '(unset)'}")

    site_dir = ROOT / args.out
    if site_dir.exists():
        shutil.rmtree(site_dir)
    (site_dir / "screens").mkdir(parents=True)

    plugins = load_plugins(args.only)
    for p in plugins:  # in `order`, so later plugins can read earlier ones from ctx.data
        try:
            ctx.settings = p.settings  # this plugin's `settings:` from its plugin.yaml
            ctx.data[p.name] = p.module.fetch(ctx) or {}
        except Exception as e:
            ctx.log(f"{p.name}: fetch failed: {e}")
            ctx.data[p.name] = {"available": False, "error": str(e)}

    jobs = [(p, ctx.data[p.name]) for p in plugins if ctx.data[p.name].get("available", True)]
    rendered = render_pngs(ctx, jobs, site_dir / "screens") if jobs else {}

    for p in plugins:
        write_data(p.name, ctx.data[p.name], site_dir)
        if hasattr(p.module, "publish") and ctx.data[p.name].get("available", True):
            p.module.publish(ctx, ctx.data[p.name], site_dir)
    if not (site_dir / "brief.xml").exists():  # brief failed this run: keep serving the last feed
        prev = ctx.previous("brief.xml")
        if prev:
            (site_dir / "brief.xml").write_bytes(prev)

    on_air = pick_on_air([p for p in plugins if p.name in rendered], ctx.data, ctx.now)
    if on_air:
        payload = write_display_endpoint(ctx, on_air, site_dir)
        ctx.log(f"on air: {on_air.name} -> {payload['image_url']}")
    else:
        ctx.log("nothing rendered; the Kindle keeps its last screen")
    write_index(ctx, plugins, rendered, on_air, site_dir)
    write_screens_list(ctx, plugins, rendered, on_air, site_dir)
    write_data("_diagnostics", {"built": ctx.now.strftime("%Y-%m-%d %H:%M"), "mode": ctx.mode,
                                "secrets": {k: bool(os.environ.get(k)) for k in
                                            ["OPENROUTER_API_KEY", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"]},
                                **ctx.diag}, site_dir)
    write_run_summary(ctx, plugins, rendered, on_air)
    return 0 if rendered else 1


def write_run_summary(ctx, plugins, rendered, on_air) -> None:
    """On GitHub Actions, show what this run did at the top of the run page (no log digging)."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    rows = ["| Screen | Result |", "|---|---|"]
    for p in plugins:
        d = ctx.data.get(p.name, {})
        if p.name not in rendered:
            result = f"skipped: {d.get('error', 'no data')}"[:160]
        elif p.name == "morning_brief":
            result = f"AI brief by `{d['model']}`" if d.get("ai") else "headlines only (AI unavailable or no key)"
        elif p.name == "year_of_the_day":
            result = (f"{d['mode']} illustration" if d.get("image")
                      else "text" + (" (image mode set, but no Cloudflare keys or the image failed)"
                                     if p.settings.get("mode", "text") != "text" else ""))
        else:
            result = "rendered"
        rows.append(f"| {p.title}{' (on air)' if on_air and p.name == on_air.name else ''} | {result} |")
    for service, info in ctx.diag.items():
        for err in info.get("errors", [])[:3]:
            rows.append(f"| {service} error | {err.replace('|', '/')[:200]} |")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"### Kindle Hub · {ctx.mode} run · {ctx.now:%d %b %H:%M} IST\n\n" + "\n".join(rows) + "\n")


if __name__ == "__main__":
    sys.exit(main())
