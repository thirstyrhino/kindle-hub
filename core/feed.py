"""The RSS feed KOReader's News Downloader reads, plus dated archive pages.

KOReader (with download_full_article=false) builds each ebook from the item's <description>,
so the whole brief goes into the description as HTML.
"""
from __future__ import annotations

import html
import xml.etree.ElementTree as ET
from email.utils import format_datetime
from pathlib import Path

from .context import Context

CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"


def article_html(data: dict) -> str:
    e = html.escape
    parts = [f"<h2>{e(data['headline'])}</h2>"]
    if data.get("weather_note"):
        parts.append(f"<p><strong>Weather &amp; air:</strong> {e(data['weather_note'])}</p>")
    if data.get("summary"):
        parts.append("<ul>" + "".join(f"<li>{e(b)}</li>" for b in data["summary"]) + "</ul>")
    if data.get("stories"):
        parts.append("<h3>Top stories</h3>")
        for s in data["stories"]:
            link = f' <a href="{e(s["link"])}">{e(s["source"])}</a>' if s.get("link") else f" ({e(s['source'])})"
            why = f" — {e(s['why'])}" if s.get("why") else ""
            parts.append(f"<p><strong>{e(s['title'])}</strong>{why}{link}</p>")
    if data.get("markets"):
        parts.append("<h3>Markets</h3><p>" + " · ".join(
            f"{e(r['name'])} {e(r['value'])} ({e(r['pct'])})" for r in data["markets"]) + "</p>")
    if data.get("focus"):
        parts.append(f"<h3>Focus for today</h3><p>{e(data['focus'])}</p>")
    made_by = f"written by {e(data['model'])}" if data.get("ai") else "AI unavailable, headlines only"
    parts.append(f"<p><small>Generated {e(data.get('generated_at', ''))} IST · {made_by}</small></p>")
    return "\n".join(parts)


def page_html(title: str, body: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title>
<style>body{{font:18px/1.55 Georgia,serif;max-width:40rem;margin:2rem auto;padding:0 1rem;color:#111;background:#fff}}
h1{{font:700 1.2rem system-ui,sans-serif;text-transform:uppercase;letter-spacing:.06em}}a{{color:#111}}
@media (prefers-color-scheme:dark){{body{{background:#111;color:#eee}}a{{color:#eee}}}}</style></head>
<body><h1>{html.escape(title)}</h1>{body}</body></html>"""


def _cdata(text: str) -> str:
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def _previous_items(ctx: Context) -> list[dict]:
    raw = ctx.previous("brief.xml")
    if not raw:
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        ctx.log(f"previous feed unreadable: {e}")
        return []
    items = []
    for it in root.iter("item"):
        items.append({
            "title": it.findtext("title", ""),
            "link": it.findtext("link", ""),
            "guid": it.findtext("guid", ""),
            "pubDate": it.findtext("pubDate", ""),
            "html": it.findtext(f"{{{CONTENT_NS}}}encoded") or it.findtext("description", ""),
            "date": (it.findtext("guid", "").rsplit("/", 1)[-1]).removesuffix(".html"),
        })
    return items


def write_feed(ctx: Context, data: dict, site_dir: Path) -> None:
    site = ctx.cfg["site_url"]
    title = ctx.cfg.get("title", "Morning Brief")
    date = data["date"]
    body = article_html(data)
    today = {
        "title": f"{title} — {ctx.now.strftime('%a %d %b %Y')}",
        "link": f"{site}/briefs/{date}.html",
        "guid": f"{site}/briefs/{date}.html",
        "pubDate": data.get("pub_date") or format_datetime(ctx.now),  # stable across hourly refreshes
        "html": body,
        "date": date,
    }
    keep = int(ctx.cfg.get("feed_history", 7))
    items = [today] + [i for i in _previous_items(ctx) if i["date"] != date][: keep - 1]

    briefs = site_dir / "briefs"
    briefs.mkdir(parents=True, exist_ok=True)
    for it in items:  # Pages deploys replace the whole site, so rewrite every archive page we still list
        (briefs / f"{it['date']}.html").write_text(page_html(it["title"], it["html"]), encoding="utf-8")

    e = html.escape
    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<rss version="2.0" xmlns:content="{CONTENT_NS}"><channel>',
           f"<title>{e(title)}</title><link>{e(site)}/</link>",
           f"<description>{e(title)} for {e(ctx.cfg['location']['name'])}</description>",
           f"<lastBuildDate>{format_datetime(ctx.now)}</lastBuildDate>"]
    for it in items:
        xml += ["<item>",
                f"<title>{e(it['title'])}</title>",
                f"<link>{e(it['link'])}</link>",
                f'<guid isPermaLink="false">{e(it["guid"])}</guid>',
                f"<pubDate>{e(it['pubDate'])}</pubDate>",
                f"<description>{_cdata(it['html'])}</description>",
                f"<content:encoded>{_cdata(it['html'])}</content:encoded>",
                "</item>"]
    xml.append("</channel></rss>")
    (site_dir / "brief.xml").write_text("\n".join(xml), encoding="utf-8")
