#!/usr/bin/env python3
"""Cut the font the Kindle draws the weather clock with: Inter Display Bold, digits and "AMP:" only.

  python tools/make_clock_font.py

Writes koreader/kindlehub.koplugin/fonts/InterDisplay-Bold-clock.otf (a few KB), so the time the
Kindle draws every minute matches the rest of the screen. Needs fonttools (pip install fonttools).
"""
import shutil
from pathlib import Path

from fontTools import subset

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "fonts" / "InterDisplay-Bold.otf"
DEST = ROOT / "koreader" / "kindlehub.koplugin" / "fonts" / "InterDisplay-Bold-clock.otf"

DEST.parent.mkdir(parents=True, exist_ok=True)
opts = subset.Options()
opts.layout_features = ["kern"]
opts.name_IDs = ["*"]                # keep the copyright and licence names
opts.notdef_outline = True
font = subset.load_font(str(SRC), opts)
sub = subset.Subsetter(opts)
sub.populate(text="0123456789: APM")
sub.subset(font)
subset.save_font(font, str(DEST), opts)
shutil.copyfile(ROOT / "assets" / "fonts" / "LICENSE-Inter.txt", DEST.parent / "LICENSE-Inter.txt")
print(f"wrote {DEST.relative_to(ROOT)} ({DEST.stat().st_size} bytes)")
