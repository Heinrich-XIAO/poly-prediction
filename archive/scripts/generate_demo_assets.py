"""Generate the demo assets shown in the README.

Runs a complete backtest pipeline against live Polymarket data, captures the
Rich terminal output as an SVG, and saves a matplotlib equity curve PNG.

Outputs (overwrites previous run):
  docs/terminal_output.svg
  docs/equity_curve.png

Run from repo root:
    python scripts/generate_demo_assets.py
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import sys
from pathlib import Path

# Allow `python scripts/generate_demo_assets.py` from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Force UTF-8 on Windows consoles so unicode in Rich output doesn't crash
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich.console import Console

from src.analytics import metrics as metrics_mod
from src.analytics.report import print_run_report, save_equity_plot
from src.data.fetcher import build_ohlc, fetch_markets, fetch_trades
from src.data.store import Store
from src.sim.engine import Engine
from src.strategy.examples.buy_and_hold import BuyAndHold
from src.strategy.examples.momentum import MomentumSMA

logging.basicConfig(level=logging.WARNING)
DB_PATH = "data/cache.db"
DOCS = Path("docs")


async def main() -> None:
    DOCS.mkdir(exist_ok=True)
    Path("data").mkdir(exist_ok=True)

    console = Console(record=True, width=110)

    with Store(DB_PATH) as store:
        # 1. Get a market with real trade volume — try a few tags.
        target = None
        token_id = None
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=14)
        for tag in ("soccer", "nba", "crypto", "politics", None):
            console.print(f"[cyan]fetching markets[/] (tag={tag})…")
            markets = await fetch_markets(store, tag=tag, limit=100, max_pages=1)
            if not markets:
                continue
            console.print(f"  got {len(markets)} markets, scanning for liquidity…")
            for m in markets[:30]:
                if not m.token_ids:
                    continue
                tok = m.token_ids[0]
                if store.trade_count(tok) < 100:
                    await fetch_trades(store, m.condition_id, since=since)
                if store.trade_count(tok) >= 100:
                    target = m
                    token_id = tok
                    break
            if target:
                break

        if not target or not token_id:
            console.print("[red]could not find a market with enough liquidity[/]")
            return

        console.print()
        console.rule(f"[bold cyan]Target market[/]")
        console.print(f"[bold]{target.question}[/]")
        console.print(f"  conditionId={target.condition_id[:16]}…")
        console.print(f"  tokenId={token_id[:16]}…")
        console.print(f"  tags={target.tags}")
        console.print(f"  cached trades: {store.trade_count(token_id)}")

        # 2. Build 5-minute bars across all available data.
        bars = build_ohlc(store, token_id, freq="5min")
        if bars.empty or len(bars) < 30:
            console.print(f"[red]not enough bars built ({len(bars)})[/]")
            return
        console.print(f"  built [bold]{len(bars)}[/] 5-minute bars\n")

    # 3. Run two strategies, capture the prettier one's report + equity curve.
    runs = {}
    for name, strat in [
        ("Buy and Hold",   BuyAndHold(allocation_pct=0.95)),
        ("Momentum (SMA)", MomentumSMA(lookback=20, entry_threshold=0.03,
                                       exit_threshold=0.03, position_size_usd=200.0)),
    ]:
        console.rule(f"[bold cyan]{name}[/]")
        engine = Engine(strat, bars, token_id=token_id, initial_cash=1000.0)
        run = engine.run()
        m = metrics_mod.compute_all(run.equity_curve, run.trades, run.fees_paid)
        print_run_report(run, m, console=console)
        runs[name] = run

    # 4. Save the Rich console as an SVG for the README.
    svg_path = DOCS / "terminal_output.svg"
    console.save_svg(str(svg_path), title="polymarket-backtest demo")
    console.print(f"[green]OK[/] saved terminal capture at {svg_path}")

    # 5. Save the equity curve PNG (use Buy and Hold by default — usually cleanest).
    primary = runs.get("Buy and Hold") or next(iter(runs.values()))
    png_path = DOCS / "equity_curve.png"
    save_equity_plot(primary, str(png_path))
    console.print(f"[green]OK[/] saved equity curve at {png_path}")


if __name__ == "__main__":
    asyncio.run(main())
