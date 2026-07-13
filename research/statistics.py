"""Statistical analysis of market categories."""

from __future__ import annotations

import pandas as pd

from src.data.store import Store


def category_distributions(store: Store, tag: str, freq: str = "5min") -> dict:
    """Aggregate statistics across all markets in a category."""
    from src.data.fetcher import build_ohlc

    markets = store.list_markets(tag=tag)
    if not markets:
        return {}

    price_ranges = []
    volumes = []
    n_bars_list = []

    for m in markets[:20]:
        if not m.token_ids:
            continue
        bars = build_ohlc(store, m.token_ids[0], freq=freq)
        if bars.empty:
            continue
        price_ranges.append(float(bars["close"].max() - bars["close"].min()))
        volumes.append(float(bars["volume"].sum()))
        n_bars_list.append(len(bars))

    return {
        "tag": tag,
        "n_markets": len(price_ranges),
        "avg_price_range": sum(price_ranges) / len(price_ranges) if price_ranges else 0,
        "avg_volume": sum(volumes) / len(volumes) if volumes else 0,
        "avg_bars": sum(n_bars_list) / len(n_bars_list) if n_bars_list else 0,
    }


def token_volume_profile(bars: pd.DataFrame) -> dict:
    """Describe a single token's OHLCV profile."""
    if bars.empty:
        return {}
    daily_groups = bars.groupby(bars.index.date)
    daily_vol = daily_groups["volume"].sum()
    return {
        "n_bars": len(bars),
        "price_min": float(bars["low"].min()),
        "price_max": float(bars["high"].max()),
        "price_mean": float(bars["close"].mean()),
        "price_std": float(bars["close"].std()),
        "total_volume": float(bars["volume"].sum()),
        "avg_daily_volume": float(daily_vol.mean()) if len(daily_vol) > 0 else 0.0,
    }
