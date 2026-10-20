"""Plugin discovery and the time-of-day playlist.

A plugin is a folder under plugins/ with:
  plugin.yaml      name, title, order, show windows
  fetch.py         def fetch(ctx) -> dict   (optional: def publish(ctx, data, site_dir))
  template.liquid  markup rendered into a Kindle-sized screen
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from types import ModuleType

import yaml

from .context import ROOT


@dataclass
class Plugin:
    name: str
    title: str
    order: int
    show: list[str]
    enabled: bool
    folder: Path
    module: ModuleType

    @property
    def template(self) -> str:
        return (self.folder / "template.liquid").read_text(encoding="utf-8")

    def on_air(self, now: datetime) -> bool:
        if not self.show:
            return False
        t = now.time()
        for window in self.show:
            start_s, end_s = [s.strip() for s in window.split("-")]
            start, end = time.fromisoformat(start_s), time.fromisoformat(end_s)
            if (start <= t <= end) if start <= end else (t >= start or t <= end):
                return True
        return False


def load_plugins(only: list[str] | None = None) -> list[Plugin]:
    plugins = []
    for meta_path in sorted((ROOT / "plugins").glob("*/plugin.yaml")):
        meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
        folder = meta_path.parent
        name = meta.get("name", folder.name)
        if only and name not in only:
            continue
        if meta.get("enabled", True) is False:
            continue
        spec = importlib.util.spec_from_file_location(f"plugins.{name}", folder / "fetch.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(module)
        plugins.append(Plugin(name=name, title=meta.get("title", name), order=int(meta.get("order", 50)),
                              show=list(meta.get("show", [])), enabled=True, folder=folder, module=module))
    return sorted(plugins, key=lambda p: p.order)


def pick_on_air(plugins: list[Plugin], data: dict, now: datetime) -> Plugin | None:
    """The screen the Kindle should show right now. Screens whose data failed are skipped.
    When several share a window, rotate hourly so each gets air time."""
    usable = [p for p in plugins if data.get(p.name, {}).get("available", True)]
    live = [p for p in usable if p.on_air(now)]
    pool = live or usable
    if not pool:
        return None
    return pool[now.hour % len(pool)]
