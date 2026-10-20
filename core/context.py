"""Shared run context: config, clock, HTTP helpers, demo fixtures, previous outputs."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
UA = "kindle-hub/1.0 (+https://github.com)"
PLACEHOLDER = "YOUR-GITHUB-USERNAME"


def load_config(path: Path | None = None) -> dict:
    path = path or Path(os.environ.get("KB_CONFIG", ROOT / "config.yaml"))
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    site = os.environ.get("SITE_URL") or cfg.get("site_url") or ""
    if not site or PLACEHOLDER in site:
        # On GitHub Actions, derive the Pages URL from the repo name.
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        if "/" in repo:
            owner, name = repo.split("/", 1)
            site = (f"https://{owner.lower()}.github.io" if name.lower() == f"{owner.lower()}.github.io"
                    else f"https://{owner.lower()}.github.io/{name}")
    cfg["site_url"] = site.rstrip("/")
    return cfg


@dataclass
class Context:
    cfg: dict
    mode: str = "full"            # "full" regenerates the AI brief, "refresh" reuses today's
    demo: bool = False            # use fixtures/ instead of the network
    now: datetime = None          # type: ignore[assignment]
    data: dict[str, Any] = field(default_factory=dict)   # plugin name -> fetched data
    _previous: dict[str, Any] = field(default_factory=dict)
    session: requests.Session = field(default_factory=requests.Session)

    def __post_init__(self):
        self.tz = ZoneInfo(self.cfg.get("timezone", "Asia/Kolkata"))
        if self.now is None:
            self.now = datetime.now(self.tz)
        elif self.now.tzinfo is None:
            self.now = self.now.replace(tzinfo=self.tz)
        self.session.headers["User-Agent"] = UA

    # -- logging -----------------------------------------------------------
    def log(self, *parts: Any) -> None:
        print("[kindle-hub]", *parts, file=sys.stderr, flush=True)

    # -- network -----------------------------------------------------------
    def get_json(self, url: str, params: dict | None = None, headers: dict | None = None,
                 timeout: float = 20, retries: int = 2) -> Any:
        last: Exception | None = None
        for attempt in range(retries + 1):
            try:
                r = self.session.get(url, params=params, headers=headers, timeout=timeout)
                r.raise_for_status()
                return r.json()
            except Exception as e:  # network errors, HTTP errors, bad JSON
                last = e
                self.log(f"GET {url} failed (attempt {attempt + 1}): {e}")
        raise RuntimeError(f"GET {url} failed: {last}")

    def get_bytes(self, url: str, timeout: float = 20) -> bytes:
        r = self.session.get(url, timeout=timeout)
        r.raise_for_status()
        return r.content

    # -- demo fixtures -----------------------------------------------------
    def fixture(self, name: str) -> Any:
        p = ROOT / "fixtures" / "demo" / name
        return json.loads(p.read_text(encoding="utf-8")) if p.suffix == ".json" else p.read_bytes()

    # -- what the live site published last time ----------------------------
    def previous(self, rel_path: str) -> bytes | None:
        """Fetch a file from the currently published site (None if unavailable)."""
        if rel_path in self._previous:
            return self._previous[rel_path]
        content = None
        site = self.cfg.get("site_url")
        if not self.demo and site:
            try:
                content = self.get_bytes(f"{site}/{rel_path}", timeout=15)
            except Exception as e:
                self.log(f"no previous {rel_path}: {e}")
        self._previous[rel_path] = content
        return content

    def previous_json(self, rel_path: str) -> Any:
        raw = self.previous(rel_path)
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            return None

    def usable(self, plugin_name: str) -> dict | None:
        """Another plugin's data from this run, or None if it failed or hasn't run."""
        d = self.data.get(plugin_name)
        return d if d and d.get("available", True) else None

    # -- time helpers ------------------------------------------------------
    @property
    def today(self) -> str:
        return self.now.strftime("%Y-%m-%d")

    @property
    def stamp(self) -> str:
        return self.now.strftime("%Y%m%d%H%M")
