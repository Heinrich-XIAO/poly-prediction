#!/usr/bin/env python3
"""Run all registered strategies on a market and compare results.

Usage:
    python scripts/run_competition.py --tag soccer --freq 5min --cash 1000

Requires cached data (run `python -m src.cli.main fetch --with-trades --tag soccer` first).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from competition.registry import register, StrategyRecord, list_strategies
from competition.runner import CompetitionRunner
from competition.report import print_comparison_report
from competition.leaderboard import Leaderboard
from src.data.store import Store
from src.data.fetcher import build_ohlc


def _register_builtins():
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


def main():
    parser = argparse.ArgumentParser(description="Run strategy competition")
    parser.add_argument("--tag", default="soccer", help="Market category tag")
    parser.add_argument("--freq", default="5min", help="Bar frequency")
    parser.add_argument("--cash", type=float, default=1000.0, help="Initial cash")
    parser.add_argument("--db", default="data/cache.db", help="SQLite cache path")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

    _register_builtins()

    with Store(args.db) as store:
        markets = store.list_markets(tag=args.tag)
        if not markets:
            print(f"No cached markets for tag '{args.tag}'. Run fetch first.")
            sys.exit(1)

        target = next((m for m in markets if m.token_ids), None)
        if not target:
            print("No tradable market found.")
            sys.exit(1)

        token_id = target.token_ids[0]
        print(f"Market: {target.question[:80]}")
        print(f"Token:  {token_id[:16]}…")

        bars = build_ohlc(store, token_id, freq=args.freq)
        if bars.empty:
            print(f"No trades cached for token {token_id[:16]}…")
            sys.exit(1)

        print(f"Bars:   {len(bars)} ({args.freq})")
        print()

        runner = CompetitionRunner(bars, token_id, initial_cash=args.cash)
        result = runner.run(list_strategies())

        print_comparison_report(result)

        lb = Leaderboard("data/leaderboard.db")
        for name in result.runs:
            lb.record(result.runs[name], result.metrics[name], name, category=args.tag)
        lb.close()


if __name__ == "__main__":
    main()
