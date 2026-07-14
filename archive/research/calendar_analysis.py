"""Analyse resolution timing patterns."""

from __future__ import annotations

import datetime as dt

from src.data.store import Store


def resolution_patterns(store: Store, tag: str | None = None) -> dict:
    """Summarize end-date patterns across cached markets.

    Helps identify markets that resolve on predictable schedules
    (daily sports matches, weekly economic reports, etc.).
    """
    markets = store.list_markets(tag=tag)
    if not markets:
        return {}

    day_of_week: dict[str, int] = {}
    hour_of_day: dict[str, int] = {}
    month: dict[str, int] = {}

    for m in markets:
        if not m.end_date:
            continue
        try:
            end = dt.datetime.fromisoformat(m.end_date)
        except (ValueError, TypeError):
            continue
        dow = end.strftime("%A")
        hod = end.strftime("%H:00")
        mon = end.strftime("%B")
        day_of_week[dow] = day_of_week.get(dow, 0) + 1
        hour_of_day[hod] = hour_of_day.get(hod, 0) + 1
        month[mon] = month.get(mon, 0) + 1

    return {
        "n_markets": len(markets),
        "day_of_week": dict(sorted(day_of_week.items(), key=lambda x: x[1], reverse=True)),
        "hour_of_day": dict(sorted(hour_of_day.items(), key=lambda x: x[1], reverse=True)),
        "month": dict(sorted(month.items(), key=lambda x: x[1], reverse=True)),
    }
