#!/usr/bin/env python3
"""Study optimal cash-out timing for a strategy.

Compares a strategy with different take-profit / stop-loss parameters
to find the best exit thresholds.

Usage:
    python scripts/cash_out_study.py --tag soccer --freq 5min
"""

from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.store import Store
from src.data.fetcher import build_ohlc
from src.sim.engine import Engine
from src.analytics.metrics import compute_all
from strategies.builtin.buy_and_hold import BuyAndHold
from strategies.base import with_cash_out
from rich.console import Console
from rich.table import Table

console = Console()


def main():
    parser = argparse.ArgumentParser(description="Study cash-out timing")
    parser.add_argument("--tag", default="soccer", help="Market category tag")
    parser.add_argument("--freq", default="5min", help="Bar frequency")
    parser.add_argument("--db", default="data/cache.db")
    args = parser.parse_args()

    with Store(args.db) as store:
        markets = store.list_markets(tag=args.tag)
        if not markets:
            console.print(f"[red]No markets for tag '{args.tag}'[/]")
            sys.exit(1)

        target = next((m for m in markets if m.token_ids), None)
        if not target:
            sys.exit(1)

        token_id = target.token_ids[0]
        bars = build_ohlc(store, token_id, freq=args.freq)
        if bars.empty:
            sys.exit(1)

        console.rule(f"[bold cyan]Cash-Out Study: {target.question[:60]}[/]")
        console.print(f"{len(bars)} bars @ {args.freq}\n")

        tp_values = [None, 0.10, 0.20, 0.50, 1.0]
        sl_values = [None, -0.10, -0.25, -0.50]

        tbl = Table(header_style="bold")
        tbl.add_column("TP")
        tbl.add_column("SL")
        tbl.add_column("Return", justify="right")
        tbl.add_column("Sharpe", justify="right")
        tbl.add_column("Trades", justify="right")
        tbl.add_column("Fees", justify="right")

        for tp, sl in itertools.product(tp_values, sl_values):
            base = BuyAndHold(allocation_pct=0.95)
            wrapped = with_cash_out(base, take_profit_pct=tp, stop_loss_pct=sl)
            engine = Engine(wrapped, bars, token_id=token_id, initial_cash=1000.0)
            run = engine.run()
            m = compute_all(run.equity_curve, run.trades, run.fees_paid)

            tp_label = f"{tp * 100:.0f}%" if tp else "none"
            sl_label = f"{sl * 100:.0f}%" if sl else "none"
            ret_color = "green" if m["total_return"] >= 0 else "red"

            tbl.add_row(
                tp_label, sl_label,
                f"[{ret_color}]{m['total_return'] * 100:+.2f}%[/]",
                f"{m['sharpe']:.2f}",
                str(m["n_trades"]),
                f"${m['fees_paid']:.2f}",
            )

        console.print(tbl)


if __name__ == "__main__":
    main()
