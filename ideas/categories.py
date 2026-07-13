"""Analyze strategy performance per Polymarket category/tag."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from competition.registry import StrategyRecord
from competition.runner import ComparisonResult
from src.analytics.metrics import compute_all
from src.data.store import Store

_CATEGORY_TAGS = [
    "soccer", "nba", "nfl", "mlb", "ufc", "tennis", "cricket", "boxing",
    "crypto", "politics", "weather", "entertainment", "technology",
    "economics", "pop-culture", "awards",
]


def analyze_category_performance(store: Store, strategy: StrategyRecord, freq: str = "5min") -> dict[str, dict]:
    """Run a strategy across all cached market categories and return per-category metrics.

    For each category tag that has cached trades, builds OHLC bars and runs the
    strategy. Returns a dict mapping tag → metrics.
    """
    from src.data.fetcher import build_ohlc

    results: dict[str, dict] = {}
    for tag in _CATEGORY_TAGS:
        markets = store.list_markets(tag=tag)
        if not markets:
            continue

        category_returns = []
        for m in markets[:10]:
            if not m.token_ids:
                continue
            token_id = m.token_ids[0]
            bars = build_ohlc(store, token_id, freq=freq)
            if bars.empty or len(bars) < 30:
                continue

            inst = strategy.strategy_class(**strategy.default_params)
            from src.sim.engine import Engine
            engine = Engine(inst, bars, token_id=token_id, initial_cash=1000.0)
            run = engine.run()
            metrics = compute_all(run.equity_curve, run.trades, run.fees_paid)
            category_returns.append(metrics["total_return"])

        if category_returns:
            results[tag] = {
                "mean_return": sum(category_returns) / len(category_returns),
                "n_markets": len(category_returns),
                "positive_rate": sum(1 for r in category_returns if r > 0) / len(category_returns),
            }

    return results
