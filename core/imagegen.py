"""Text-to-image via Cloudflare Workers AI (free daily allowance), plus e-ink preparation.

Needs two environment variables (GitHub secrets): CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN.
FLUX.1 [schnell] at 8 steps costs ~82 of the 10,000 free daily units, so one image a day is free.
"""
from __future__ import annotations

import base64
import io
import os

from PIL import Image, ImageFilter, ImageOps

from .context import Context

DEFAULT_MODEL = "@cf/black-forest-labs/flux-1-schnell"
API = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"


def configured() -> bool:
    return bool(os.environ.get("CLOUDFLARE_ACCOUNT_ID") and os.environ.get("CLOUDFLARE_API_TOKEN"))


def generate(ctx: Context, prompt: str, model: str = DEFAULT_MODEL, seed: int | None = None) -> bytes | None:
    """Returns encoded image bytes (JPEG/PNG), or None if not configured or the call fails."""
    if ctx.demo:
        try:
            return ctx.fixture("yotd_illustration.png")
        except FileNotFoundError:
            return None
    if not configured():
        ctx.log("image: CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN not set; using the text layout")
        return None
    url = os.environ.get("CLOUDFLARE_AI_URL") or API.format(account=os.environ["CLOUDFLARE_ACCOUNT_ID"], model=model)
    body = {"prompt": prompt[:2048], "steps": 8}
    if seed is not None:
        body["seed"] = seed
    for attempt in (1, 2):
        try:
            r = ctx.session.post(url, json=body, timeout=120,
                                 headers={"Authorization": f"Bearer {os.environ['CLOUDFLARE_API_TOKEN']}"})
            if r.status_code != 200:
                ctx.log(f"image: Cloudflare HTTP {r.status_code}: {r.text[:200]}")
                continue
            if r.headers.get("content-type", "").startswith("image/"):
                return r.content
            payload = r.json()
            b64 = (payload.get("result") or {}).get("image") or payload.get("image")
            if not b64:
                ctx.log(f"image: no image in response: {str(payload)[:200]}")
                continue
            return base64.b64decode(b64)
        except Exception as e:
            ctx.log(f"image: attempt {attempt} failed: {e}")
    return None


def for_eink(raw: bytes, width: int, height: int) -> Image.Image:
    """Crop to fill width x height, boost contrast, and dither to the Kindle's 16 greys."""
    img = Image.open(io.BytesIO(raw)).convert("L")
    img = ImageOps.fit(img, (width, height), method=Image.Resampling.LANCZOS, centering=(0.5, 0.45))
    img = ImageOps.autocontrast(img, cutoff=1)
    img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))
    palette = Image.new("P", (1, 1))
    palette.putpalette([v for level in range(16) for v in (level * 17,) * 3] + [0, 0, 0] * 240)
    return img.convert("RGB").quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG).convert("L")
