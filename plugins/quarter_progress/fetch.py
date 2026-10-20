"""Quarter progress: one square per day of the current quarter, with days passed and days left.

Equivalent of TRMNL's "Quarter Progress" recipe, laid out for a portrait Kindle. No network needed.
Set `fiscal_year_start: 4` in plugin.yaml for Indian financial-year quarters (Q1 = Apr–Jun).
"""
from calendar import monthrange
from datetime import date
from math import ceil

PAD, GAP = 12, 8          # screen padding and gap between squares, px
CHROME = 330              # px the template uses above and below the grid (title, numbers, title bar)


def _add_months(year: int, month: int, n: int) -> tuple[int, int]:
    m = month - 1 + n
    return year + m // 12, m % 12 + 1


def _quarter(today: date, fy_start: int):
    offset = (today.month - fy_start) % 12          # months since the (fiscal) year began
    q = offset // 3 + 1
    y0, m0 = _add_months(today.year, today.month, -(offset % 3))
    start = date(y0, m0, 1)
    y1, m1 = _add_months(y0, m0, 2)
    end = date(y1, m1, monthrange(y1, m1)[1])
    fy_end_year = end.year if fy_start == 1 else _add_months(start.year, start.month, 12 - offset // 3 * 3 - 1)[0]
    return q, start, end, fy_end_year


def _grid(n: int, width: int, height: int) -> tuple[int, int]:
    """Columns and square size that make the biggest squares fitting width x height."""
    best = (1, 0)
    for cols in range(1, n + 1):
        rows = ceil(n / cols)
        size = min((width - GAP * (cols - 1)) // cols, (height - GAP * (rows - 1)) // rows)
        if size >= best[1]:       # on a tie, more columns: the grid spans the full width
            best = (cols, size)
    return best


def fetch(ctx):
    fy_start = int(ctx.settings.get("fiscal_year_start", 1))
    today = ctx.now.date()
    q, start, end, fy_end_year = _quarter(today, fy_start)
    total = (end - start).days + 1
    day = (today - start).days + 1                   # today's position in the quarter (1-based)
    passed = day                                     # today counts as passed
    label = f"Q{q} {start.year}" if fy_start == 1 else f"Q{q} FY{str(fy_end_year)[-2:]}"

    screen_w = ctx.cfg["screen"]["width"]
    cols, size = _grid(total, screen_w - 2 * PAD, ctx.cfg["screen"]["height"] - CHROME)
    days = ["past"] * (day - 1) + ["today"] + ["future"] * (total - day)
    return {
        "available": True,
        "quarter": label,
        "passed": passed,
        "left": total - passed,
        "total": total,
        "pct": round(passed / total * 100),
        "days": days,
        "grid_cols": cols,
        "grid_size": size,
        "gap": GAP,
        "pad": PAD,
    }
