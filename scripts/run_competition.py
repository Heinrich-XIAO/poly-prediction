#!/usr/bin/env python3
"""Run all registered strategies on every market in a category and compare results.

Usage:
    python scripts/run_competition.py --tag soccer --freq 5min --cash 1000

Strategies are tested on *every* market with sufficient trade data.
A strategy that cherry-picks a single market will not rank well.
Requires cached data (run `python -m src.cli.main fetch --with-trades --tag soccer` first).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from competition.registry import register, StrategyRecord, list_strategies
from competition.runner import CompetitionRunner, MarketDef
from competition.report import print_comparison_report
from competition.leaderboard import Leaderboard
from src.data.store import Store
from src.data.fetcher import build_ohlc


def _register_builtins():
    import importlib
    import inspect

    from src.strategy.base import Strategy

    # Manual register for builtins
    from strategies.builtin.buy_and_hold import BuyAndHold
    from strategies.builtin.momentum import MomentumSMA

    register(StrategyRecord(
        name="buy_and_hold", strategy_class=BuyAndHold,
        default_params={"allocation_pct": 0.95},
        category_tags=["soccer", "nba", "crypto", "politics", "weather"],
        description="Buy once on first bar, hold to end.",
    ))
    register(StrategyRecord(
        name="momentum_sma", strategy_class=MomentumSMA,
        default_params={"lookback": 20, "entry_threshold": 0.02, "exit_threshold": 0.02, "position_size_usd": 100.0},
        category_tags=["soccer", "nba", "crypto"],
        description="SMA crossover momentum.",
    ))

    # Auto-discover strategies from originals/ and hybrids/
    all_tags = ["soccer", "nba", "crypto", "politics", "weather"]
    for directory in ("strategies/originals", "strategies/hybrids"):
        p = Path(__file__).resolve().parents[1] / directory
        if not p.is_dir():
            continue
        for f in sorted(p.glob("*.py")):
            if f.name == "__init__.py":
                continue
            module_path = f"strategies.{p.name}.{f.stem}"
            try:
                mod = importlib.import_module(module_path)
            except Exception as exc:
                logging.warning("failed to import %s: %s", module_path, exc)
                continue
            for name, obj in inspect.getmembers(mod):
                if not inspect.isclass(obj) or not issubclass(obj, Strategy) or obj is Strategy:
                    continue
                if name.startswith("_"):
                    continue
                register(StrategyRecord(
                    name=f.name.replace(".py", ""),
                    strategy_class=obj,
                    default_params={},
                    category_tags=all_tags,
                    description=(obj.__doc__ or mod.__doc__ or "").strip() or f"Auto-discovered from {module_path}",
                ))


_MIN_BARS = 20
_MAX_MARKETS = 50


def main():
    parser = argparse.ArgumentParser(description="Run strategy competition across all markets in a tag")
    parser.add_argument("--tag", default="soccer", help="Market category tag")
    parser.add_argument("--freq", default="5min", help="Bar frequency")
    parser.add_argument("--cash", type=float, default=1000.0, help="Initial cash per market")
    parser.add_argument("--db", default="data/cache.db", help="SQLite cache path")
    parser.add_argument("--min-bars", type=int, default=_MIN_BARS, help="Minimum bars to include a market")
    parser.add_argument("--max-markets", type=int, default=_MAX_MARKETS, help="Max markets to test on")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

    _register_builtins()

    with Store(args.db) as store:
        markets = store.list_markets(tag=args.tag)
        if not markets:
            print(f"No cached markets for tag '{args.tag}'. Run fetch first.")
            sys.exit(1)

        market_defs: list[MarketDef] = []
        for m in markets:
            if len(market_defs) >= args.max_markets:
                break
            if not m.token_ids:
                continue
            tid = m.token_ids[0]
            bars = build_ohlc(store, tid, freq=args.freq)
            if len(bars) < args.min_bars:
                continue
            market_defs.append(MarketDef(
                bars=bars, token_id=tid,
                question=m.question, tag=args.tag,
            ))

        if not market_defs:
            print(f"No markets with >= {args.min_bars} bars of trade data for tag '{args.tag}'.")
            sys.exit(1)

        print(f"Testing {len(market_defs)} markets ({args.min_bars}+ bars each)")
        print(f"Strategies: {len(list_strategies())}")
        print()

        runner = CompetitionRunner(market_defs, initial_cash=args.cash)
        result = runner.run(list_strategies())

        print_comparison_report(result)

        lb = Leaderboard("data/leaderboard.db")
        for name, metrics in result.aggregate_metrics.items():
            lb.record_aggregate(metrics, name, category=args.tag)
        lb.close()


if __name__ == "__main__":
    main()
