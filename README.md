# kindle-hub

Jailbroken Kindle hub: an AI morning brief and TRMNL-style dashboard screens for a Kindle running KOReader.
Runs free on GitHub: Actions builds it on a schedule, Pages hosts it. Nothing to keep running at home.

What it publishes:

| URL | Used by | What |
|---|---|---|
| `/brief.xml` | KOReader **News Downloader** | Today's brief as an ebook (one tap each morning) |
| `/api/display` | TRMNL's **KOReader plugin** (Base URL = the site) | Which screen to show + its image |
| `/screens/current.png` | anything that can show an image URL | The screen that's on air now |
| `/` | you, in a browser | Previews of every screen, links, setup values |

Screens included (each one is a plugin folder in `plugins/`):

| Plugin | Shows | On air (IST) |
|---|---|---|
| `morning_brief` | AI headline, 3 bullets, top stories, weather strip, focus | 05:30–10:00, 13:00–14:00 |
| `weather_aqi` | Now, AQI with bar, 4-day forecast, sunrise/sunset | 10:00–13:00, 16:00–05:59 |
| `markets` | Nifty 50, Sensex, USD/INR with 1-month sparklines | 13:00–16:00 |

When windows overlap, screens take turns hour by hour. A screen whose data failed is skipped.

## Schedule

- **05:47 IST** – fetches feeds, weather, markets; one OpenRouter call writes the brief.
- **Hourly 06:37–23:37 IST** – refreshes weather/markets, reuses today's brief, picks the screen on air.
- GitHub can start scheduled runs late (sometimes 10–30 min). Fine for this; not for anything to-the-minute.

## One-time setup (≈15 min)

1. **Repo.** Done: `thirstyrhino/kindle-hub` (public, which Pages on a free account requires).
2. **Key.** Get an OpenRouter key (openrouter.ai → Keys). In the repo: Settings → Secrets and variables →
   Actions → New repository secret → name `OPENROUTER_API_KEY`.
   With `models: "auto-free"` in `config.yaml` it only uses free models (`:free`); 1 call a day is far
   under the free limit. No key? It still works and publishes a headlines-only brief.
3. **Pages.** Settings → Pages → Build and deployment → Source: **GitHub Actions**.
4. **First run.** Actions tab → *Build Kindle site* → Run workflow (mode: full). When it's green, open
   <https://thirstyrhino.github.io/kindle-hub/> — you should see the three screens.

The site URL is worked out from the repo name automatically. Set `site_url` in `config.yaml` only if you
use a custom domain.

## Kindle setup (KOReader)

**Morning brief as an ebook**
1. KOReader → Tools → News downloader → Settings → add a feed:
   `https://thirstyrhino.github.io/kindle-hub/brief.xml`, limit **1**, download full article **off**.
   (Same values as `koreader/news-feed-entry.lua` if you prefer editing the config file.)
2. Each morning: News downloader → **Download news**. The brief lands in the news folder.

**Dashboard**
1. Copy `trmnl.koplugin` from <https://github.com/usetrmnl/trmnl-koreader> into `koreader/plugins/`.
   Put any word (e.g. `kindle`) in its `apikey.txt` — this site doesn't check it, but the plugin needs one.
2. Restart KOReader → Tools → TRMNL Display → Configure TRMNL → **Base URL** =
   `https://thirstyrhino.github.io/kindle-hub` (no trailing slash; the plugin adds `/api/display`).
3. Tools → More tools → Keep alive: on. Settings → Device → Auto suspend: off.
4. Tools → TRMNL Display → **Start dashboard**. Tap the screen to leave it and go back to reading.

The Kindle re-checks every `screen.refresh_seconds` (default 1 hour). Keep it on a charger while it's a dashboard.

## Your own plugins

```
plugins/my_screen/
  plugin.yaml       name, title, order, show windows
  fetch.py          def fetch(ctx) -> dict      (optional: def publish(ctx, data, site_dir))
  template.liquid   Liquid markup for one 600x800 screen
```

- `fetch(ctx)` returns a dict; its keys become template variables. Return `{"available": False}` to skip the
  screen this run. Use `ctx.get_json(url, params=...)`, `ctx.cfg`, `ctx.now`, and other plugins' data via
  `ctx.usable("weather_aqi")` (lower `order` runs first).
- Templates also get `meta.title`, `meta.updated`, `meta.date_short`, `meta.date_long`, `meta.glyph`.
- Class names follow TRMNL's framework (`layout`, `title_bar`, `item`, `title`, `value`, `label`,
  `description`), so a template can move to TRMNL or a LaraPaper server with light CSS changes.
- Put `data-fit` on a list container and `data-fit-item` on its children: items that don't fit are dropped
  whole instead of being cut mid-line.
- Styles: `templates/screen.css`. Big type, thick lines, black on white — 600×800 at 167 ppi has no room for
  subtlety.

## Run locally

```
pip install -r requirements.txt
python -m playwright install chromium
python build.py --demo                 # sample data, no network or key
python build.py --demo --at 14:30      # see what's on air at 14:30
python build.py                        # real data (set OPENROUTER_API_KEY for the AI brief)
```
Then open `site/index.html`.

## Change things

All in `config.yaml`: location, news feeds, what the brief should care about (`reader_profile`),
number of stories, models, screen size, refresh interval. Screen windows: each plugin's `plugin.yaml`.
Run times: `.github/workflows/build.yml` (cron is in UTC; IST = UTC + 5:30).

## Limits worth knowing

- **Everything published is public.** Fine for weather, AQI, news and markets. Calendars, inbox or business
  numbers need private hosting (a home server, or Cloudflare Pages with access control).
- **Markets data** comes from Yahoo Finance's unofficial chart endpoint. If it stops working, that screen
  disappears from rotation until it's fixed or swapped for another source.
- **Free AI models change.** `auto-free` picks from what OpenRouter lists as free on each run; if none
  respond, the brief falls back to headlines only. To pin a model, list it under `ai.models`.
- **GitHub pauses schedules** in public repos after 60 days without commits. You'll get an email; re-enable
  it from the Actions tab or push any small change.

## Files

```
build.py                 entry point
config.yaml              your settings
core/                    context, OpenRouter client, feed writer, renderer, publisher, playlist
plugins/*/               the screens
templates/screen.css     shared e-ink styles
assets/fonts/            Inter (SIL OFL, licence included)
fixtures/demo/           sample data for --demo
koreader/                News Downloader entry
.github/workflows/       schedule + Pages deploy
```
