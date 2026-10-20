"""Quarter progress: one square per day of the current quarter, plus month and year progress.

Equivalent of TRMNL's "Quarter Progress" recipe, laid out for a portrait Kindle. No network needed.
Set `fiscal_year_start: 4` in plugin.yaml for Indian financial-year quarters (Q1 = Apr–Jun).
"""
from calendar import monthrange
from datetime import date, timedelta

LABEL_W, GAP = 26, 4  # weekday-label column width and grid gap, px


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
    return q, start, end


def _year(today: date, fy_start: int):
    y = today.year if today.month >= fy_start else today.year - 1
    start = date(y, fy_start, 1)
    ny, nm = _add_months(y, fy_start, 12)
    end = date(ny, nm, 1) - timedelta(days=1)
    label = str(y) if fy_start == 1 else f"FY{str(end.year)[-2:]}"
    return label, start, end


def _weekdays_between(a: date, b: date) -> int:
    """Mon–Fri days from a to b inclusive."""
    if b < a:
        return 0
    days = (b - a).days + 1
    full, rest = divmod(days, 7)
    count = full * 5
    for i in range(rest):
        if (a + timedelta(days=full * 7 + i)).weekday() < 5:
            count += 1
    return count


def fetch(ctx):
    fy_start = int(ctx.settings.get("fiscal_year_start", 1))
    today = ctx.now.date()
    q, q_start, q_end = _quarter(today, fy_start)
    total = (q_end - q_start).days + 1
    day = (today - q_start).days + 1
    year_label, y_start, y_end = _year(today, fy_start)

    # Week columns, Monday first (like a calendar turned on its side).
    first_monday = q_start - timedelta(days=q_start.weekday())
    weeks, d = [], first_monday
    while d <= q_end:
        cells, label = [], ""
        for i in range(7):
            cur = d + timedelta(days=i)
            if cur < q_start or cur > q_end:
                state = "out"
            elif cur < today:
                state = "past"
            elif cur == today:
                state = "today"
            else:
                state = "future"
            cells.append({"state": state, "first": state != "out" and cur.day == 1})
            if q_start <= cur <= q_end and (cur.day == 1 or not weeks and not label):
                label = cur.strftime("%b")
        weeks.append({"label": label, "cells": cells})
        d += timedelta(days=7)

    usable = ctx.cfg["screen"]["width"] - 2 * 28 - LABEL_W
    cell = min(40, (usable - GAP * len(weeks)) // len(weeks))

    months = []
    for i in range(3):
        y, m = _add_months(q_start.year, q_start.month, i)
        m_start, m_days = date(y, m, 1), monthrange(y, m)[1]
        done = 0 if today < m_start else min(m_days, (today - m_start).days + 1)
        months.append({"name": m_start.strftime("%B"), "pct": round(done / m_days * 100),
                       "note": "done" if done == m_days else ("to come" if done == 0 else f"day {done} of {m_days}")})

    q_name = f"Q{q} {q_start.year}" if fy_start == 1 else f"Q{q} {year_label}"
    same_year = q_start.year == q_end.year
    y_total, y_day = (y_end - y_start).days + 1, (today - y_start).days + 1
    return {
        "available": True,
        "quarter": q_name,
        "range": f"{q_start:%b} – {q_end:%b %Y}" if same_year else f"{q_start:%b %Y} – {q_end:%b %Y}",
        "pct": round(day / total * 100),
        "day": day,
        "total": total,
        "days_left": total - day,
        "weekdays_left": _weekdays_between(today + timedelta(days=1), q_end),
        "weeks": weeks,
        "cell": cell,
        "label_w": LABEL_W,
        "gap": GAP,
        "months": months,
        "year": {"label": year_label, "pct": round(y_day / y_total * 100), "days_left": y_total - y_day},
    }
