"""OpenRouter client: picks models (auto-free or configured), asks for JSON, parses defensively."""
from __future__ import annotations

import json
import os
import re
from typing import Any

from .context import Context

DEFAULT_BASE = "https://openrouter.ai/api/v1"


def _base() -> str:
    return os.environ.get("OPENROUTER_BASE_URL", DEFAULT_BASE).rstrip("/")


def pick_models(ctx: Context) -> list[str]:
    ai = ctx.cfg.get("ai", {})
    models = ai.get("models", "auto-free")
    if isinstance(models, list):
        return [m for m in models if m][:3]
    if models != "auto-free":
        return [str(models)]
    # Free models rotate in and out, so discover them at run time.
    try:
        listing = ctx.get_json(f"{_base()}/models", timeout=20, retries=1)
    except Exception as e:
        ctx.log(f"could not list OpenRouter models: {e}")
        return []
    free = []
    for m in listing.get("data", []):
        mid = m.get("id", "")
        pricing = m.get("pricing") or {}
        is_free = mid.endswith(":free") or (str(pricing.get("prompt")) in ("0", "0.0")
                                             and str(pricing.get("completion")) in ("0", "0.0"))
        if is_free and m.get("context_length", 0) >= 16000:
            free.append(m)
    prefer = [p.lower() for p in ai.get("prefer", [])]

    def rank(m: dict) -> tuple:
        mid = m["id"].lower()
        pref = next((i for i, p in enumerate(prefer) if p in mid), len(prefer))
        return (pref, -int(m.get("context_length", 0)))

    chosen = [m["id"] for m in sorted(free, key=rank)[:3]]
    ctx.log(f"auto-free models: {chosen}")
    return chosen


def extract_json(text: str) -> Any:
    """Models wrap JSON in prose or code fences; pull out the first JSON object."""
    if not text:
        raise ValueError("empty response")
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        return json.loads(fenced.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in response")
    return json.loads(text[start:end + 1])


def generate_json(ctx: Context, system: str, user: str, max_tokens: int = 1400) -> tuple[dict | None, str | None]:
    """Returns (parsed_json, model_used). (None, None) when no key, no models or every attempt fails."""
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        ctx.log("OPENROUTER_API_KEY not set; using the no-AI fallback brief")
        return None, None
    models = pick_models(ctx)
    if not models:
        return None, None

    headers = {
        "Authorization": f"Bearer {key}",
        "HTTP-Referer": ctx.cfg.get("site_url") or "https://github.com",
        "X-Title": "Kindle Hub",
    }
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    # First try lets OpenRouter fall through the model list itself; then try each model alone.
    attempts: list[dict] = []
    if len(models) > 1:
        attempts.append({"models": models})
    attempts += [{"model": m} for m in models]

    for attempt in attempts:
        body = {**attempt, "messages": messages, "temperature": 0.4, "max_tokens": max_tokens}
        try:
            r = ctx.session.post(f"{_base()}/chat/completions", json=body, headers=headers, timeout=120)
            if r.status_code != 200:
                ctx.log(f"OpenRouter {attempt} -> HTTP {r.status_code}: {r.text[:200]}")
                continue
            payload = r.json()
            content = payload["choices"][0]["message"].get("content") or ""
            parsed = extract_json(content)
            if isinstance(parsed, dict):
                return parsed, payload.get("model") or attempt.get("model") or models[0]
            ctx.log("model returned JSON that is not an object")
        except Exception as e:
            ctx.log(f"OpenRouter attempt {attempt} failed: {e}")
    return None, None
