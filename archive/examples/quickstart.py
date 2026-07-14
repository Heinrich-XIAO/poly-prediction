"""End-to-end quickstart: fetch one market's trades, run two strategies, compare.

Usage:
    python examples/quickstart.py

This script:
  1. Picks the most-traded recent soccer market from Gamma.
  2. Pulls its trades into the local cache.
  3. Resamples to 5-minute bars.
  4. Runs BuyAndHold and MomentumSMA on the same data.
  5. Prints both reports side-by-side and saves equity curve PNGs.

Pre-cutover trades use the V1 fee model (typically 0 bps), post-cutover use V2.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from pathlib import Path

from rich.console import Console

from src.analytics import metrics as metrics_mod
from src.analytics.report import print_run_report, save_equity_plot
from src.data.fetcher import build_ohlc, fetch_markets, fetch_trades
from src.data.store import Store
from src.sim.engine import Engine
from src.strategy.examples.buy_and_hold import BuyAndHold
from src.strategy.examples.momentum import MomentumSMA

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
console = Console()
DB_PATH = "data/cache.db"


async def main() -> None:
    Path("data").mkdir(exist_ok=True)
    Path("plots").mkdir(exist_ok=True)

    with Store(DB_PATH) as store:
        # 1. Cache soccer markets if we haven't yet
        cached = store.list_markets(tag="soccer")
        if not cached:
            console.print("[cyan]fetching soccer markets…[/]")
            await fetch_markets(store, tag="soccer", limit=200, max_pages=2)
            cached = store.list_markets(tag="soccer")
        if not cached:
            console.print("[red]no soccer markets returned — Gamma API issue?[/]")
            return

        # 2. Pick the first market with at least one CLOB token
        target = next((m for m in cached if m.token_ids), None)
        if not target:
            console.print("[red]no tradable market found[/]")
            return
        token_id = target.token_ids[0]
        console.print(f"[bold]target market:[/] {target.question[:80]}")
        console.print(f"  conditionId={target.condition_id[:12]}…  tokenId={token_id[:12]}…")

        # 3. Fetch trades (last 14 days)
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=14)
        if store.trade_count(token_id) == 0:
            console.print(f"[cyan]fetching trades since {since.date()}…[/]")
            n = await fetch_trades(store, target.condition_id, since=since)
            console.print(f"  cached {n} trades")
        else:
            console.print(f"  using {store.trade_count(token_id)} cached trades")

        # 4. Build 5-minute bars
        bars = build_ohlc(store, token_id, freq="5min", start=since)
        if bars.empty:
            console.print("[red]no bars built — token had no trades in window[/]")
            return
        console.print(f"  built {len(bars)} bars")

    # 5. Run each strategy
    for name, strat in [
        ("buy_and_hold", BuyAndHold(allocation_pct=0.95)),
        ("momentum_sma", MomentumSMA(lookback=20, entry_threshold=0.02, exit_threshold=0.02)),
    ]:
        console.rule(f"[bold cyan]{name}[/]")
        engine = Engine(strat, bars, token_id=token_id, initial_cash=1000.0)
        run = engine.run()
        m = metrics_mod.compute_all(run.equity_curve, run.trades, run.fees_paid)
        print_run_report(run, m, console=console)
        save_equity_plot(run, f"plots/{name}.png")
        console.print(f"[dim]equity curve → plots/{name}.png[/]")


if __name__ == "__main__":
    asyncio.run(main())
