#!/usr/bin/env python3
"""Run all registered strategies on markets in a category and compare results.

Usage (development):
    python scripts/run_competition.py --tag soccer --freq 5min --cash 1000 --max-markets 50

Usage (final eval):
    python scripts/run_competition.py --tag soccer --freq 5min --cash 1000 --max-markets 50 --eval

Markets are split into training (development) and test (final evaluation) sets
when --holdout-fraction > 0. The split is deterministic — same DB state, same
split every time. Never use --eval during iteration; that leaks test-set signal
and invalidates your result.

Requires cached data (run `python -m src.cli.main fetch --with-trades --tag soccer` first).
"""

from __future__ import annotations

import argparse
import logging
import random
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
_HOLDOUT_SEED = 42


def _holdout_split(
    market_defs: list[MarketDef], fraction: float
) -> tuple[list[MarketDef], list[MarketDef]]:
    """Split markets into train/test sets.

    Deterministic for the same list (seed is fixed) — adding or removing a
    market may shift the boundary slightly, but re-running on identical data
    produces identical splits.
    """
    if fraction <= 0 or len(market_defs) < 2:
        return market_defs, []

    n = len(market_defs)
    n_test = max(3, int(n * fraction))
    n_test = min(n_test, n - 1)  # leave at least one for training

    rng = random.Random(_HOLDOUT_SEED)
    test_indices = set(rng.sample(range(n), n_test))

    train = [m for i, m in enumerate(market_defs) if i not in test_indices]
    test = [m for i, m in enumerate(market_defs) if i in test_indices]
    return train, test


def main():
    parser = argparse.ArgumentParser(
        description="Run strategy competition across markets in a category"
    )
    parser.add_argument("--tag", default="soccer", help="Market category tag")
    parser.add_argument("--freq", default="5min", help="Bar frequency")
    parser.add_argument("--cash", type=float, default=1000.0, help="Initial cash per market")
    parser.add_argument("--db", default="data/cache.db", help="SQLite cache path")
    parser.add_argument("--min-bars", type=int, default=_MIN_BARS, help="Minimum bars to include a market")
    parser.add_argument("--max-markets", type=int, default=_MAX_MARKETS, help="Max markets to test on")
    parser.add_argument(
        "--holdout-fraction", type=float, default=0.2,
        help="Fraction of markets held out for final evaluation (default: 0.2). "
             "Set to 0 to disable holdout and test on all markets.",
    )
    parser.add_argument(
        "--eval", action="store_true",
        help="Evaluate on the held-out test set instead of the training set. "
             "For final submission only — do NOT use during development.",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if args.eval and args.holdout_fraction <= 0:
        print("Error: --eval requires --holdout-fraction > 0")
        sys.exit(1)

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

        # Split into train / test (or use all markets if holdout is disabled)
        if args.holdout_fraction > 0:
            train_defs, test_defs = _holdout_split(market_defs, args.holdout_fraction)

            if args.eval:
                if len(test_defs) < 3:
                    print(
                        f"Error: only {len(test_defs)} test markets (need ≥3). "
                        f"Increase --max-markets (currently {args.max_markets})."
                    )
                    sys.exit(1)
                run_defs = test_defs
                mode_label = "TEST SET"
                lb_category = f"{args.tag}_test"
            else:
                run_defs = train_defs
                mode_label = "TRAINING SET"
                lb_category = f"{args.tag}_train"
        else:
            run_defs = market_defs
            mode_label = "ALL MARKETS"
            lb_category = args.tag

        print(f"Running on {len(run_defs)} markets [{mode_label}]")
        print(f"Strategies: {len(list_strategies())}")
        print()

        runner = CompetitionRunner(run_defs, initial_cash=args.cash)
        result = runner.run(list_strategies())

        print_comparison_report(result, mode=mode_label)

        lb = Leaderboard("data/leaderboard.db")
        for name, metrics in result.aggregate_metrics.items():
            lb.record_aggregate(metrics, name, category=lb_category)
        lb.close()


if __name__ == "__main__":
    main()
