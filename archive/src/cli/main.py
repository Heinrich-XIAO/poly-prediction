"""CLI entry point.

Subcommands:
  fetch      Pull markets + trades from Polymarket public APIs into the cache.
  list       Show cached markets, optionally filtered by tag.
  backtest   Run a strategy on a cached market, store the run, print a report.
  report     Re-render a stored run's report by run_id.
  runs       List recent backtest runs.

Run `python -m src.cli.main <command> --help` for per-command flags.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import importlib
import json
import logging
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from src.constants import DEFAULT_CACHE_DB, DEFAULT_FEE_RATE, DEFAULT_INITIAL_CASH
from src.data.fetcher import build_ohlc, fetch_markets, fetch_trades
from src.data.store import Store
from src.sim.engine import Engine
from src.analytics import metrics as metrics_mod
from src.analytics.report import print_run_report, save_equity_plot

console = Console()


# ---------- root group ----------


@click.group()
@click.option("--db", default=DEFAULT_CACHE_DB, help="SQLite cache path.")
@click.option("--verbose", "-v", is_flag=True, help="Verbose logging.")
@click.pass_context
def cli(ctx: click.Context, db: str, verbose: bool) -> None:
    """polymarket-backtest CLI."""
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    ctx.ensure_object(dict)
    ctx.obj["db"] = db


# ---------- fetch ----------


@cli.command()
@click.option("--tag", default=None, help="Tag slug filter (e.g. 'soccer', 'nba').")
@click.option("--closed/--open", default=False, help="Include closed markets.")
@click.option("--limit", default=500, show_default=True)
@click.option("--max-pages", default=10, show_default=True)
@click.option("--with-trades", is_flag=True, help="Also fetch trades for each market.")
@click.option("--since", default=None, help="ISO date — only fetch trades >= this.")
@click.pass_context
def fetch(
    ctx: click.Context,
    tag: str | None,
    closed: bool,
    limit: int,
    max_pages: int,
    with_trades: bool,
    since: str | None,
) -> None:
    """Pull markets (and optionally trades) into the local cache."""
    db = ctx.obj["db"]
    since_dt = dt.datetime.fromisoformat(since).replace(tzinfo=dt.timezone.utc) if since else None

    async def _go() -> None:
        with Store(db) as store:
            markets = await fetch_markets(
                store, tag=tag, closed=closed, limit=limit, max_pages=max_pages
            )
            console.print(f"[green]✓[/] cached {len(markets)} markets")
            if with_trades:
                for i, m in enumerate(markets, 1):
                    console.print(f"  [{i}/{len(markets)}] {m.question[:60]}…")
                    n = await fetch_trades(store, m.condition_id, since=since_dt)
                    console.print(f"      [green]+{n}[/] new trades")

    asyncio.run(_go())


# ---------- list ----------


@cli.command("list")
@click.option("--tag", default=None, help="Tag slug filter.")
@click.option("--limit", default=20, show_default=True)
@click.pass_context
def list_markets(ctx: click.Context, tag: str | None, limit: int) -> None:
    """List cached markets."""
    with Store(ctx.obj["db"]) as store:
        markets = store.list_markets(tag=tag)[:limit]
    if not markets:
        console.print("[yellow]no markets cached — run `fetch` first[/]")
        return
    tbl = Table(title=f"Cached markets" + (f" (tag={tag})" if tag else ""))
    tbl.add_column("conditionId", style="dim")
    tbl.add_column("question")
    tbl.add_column("ends")
    tbl.add_column("tokens", justify="right")
    for m in markets:
        tbl.add_row(
            m.condition_id[:12] + "…",
            (m.question[:60] + "…") if len(m.question) > 60 else m.question,
            (m.end_date or "")[:10],
            str(len(m.token_ids)),
        )
    console.print(tbl)


# ---------- backtest ----------


_BUILTIN_STRATEGIES = {
    "buy_and_hold": ("src.strategy.examples.buy_and_hold", "BuyAndHold"),
    "momentum":     ("src.strategy.examples.momentum", "MomentumSMA"),
}


@cli.command()
@click.option("--strategy", required=True, help="Built-in name or 'module:Class'.")
@click.option("--token-id", required=True, help="CLOB token ID to backtest.")
@click.option("--initial-cash", default=DEFAULT_INITIAL_CASH, show_default=True)
@click.option("--fee-rate", default=DEFAULT_FEE_RATE, show_default=True)
@click.option("--freq", default="1min", show_default=True, help="Bar frequency (pandas freq).")
@click.option("--start", default=None, help="ISO date inclusive.")
@click.option("--end", default=None, help="ISO date inclusive.")
@click.option("--slippage", default="bar_vwap", show_default=True,
              type=click.Choice(["bar_close", "bar_vwap", "linear_impact"]))
@click.option("--params", default="{}", help="JSON dict of strategy kwargs.")
@click.option("--save-plot", default=None, help="Path to save equity curve PNG.")
@click.pass_context
def backtest(
    ctx: click.Context,
    strategy: str,
    token_id: str,
    initial_cash: float,
    fee_rate: float,
    freq: str,
    start: str | None,
    end: str | None,
    slippage: str,
    params: str,
    save_plot: str | None,
) -> None:
    """Run a strategy on a cached market."""
    db = ctx.obj["db"]
    strat_kwargs = json.loads(params)
    strat = _instantiate_strategy(strategy, **strat_kwargs)

    start_dt = dt.datetime.fromisoformat(start).replace(tzinfo=dt.timezone.utc) if start else None
    end_dt = dt.datetime.fromisoformat(end).replace(tzinfo=dt.timezone.utc) if end else None

    with Store(db) as store:
        bars = build_ohlc(store, token_id, freq=freq, start=start_dt, end=end_dt)
        if bars.empty:
            console.print(f"[red]no trade data cached for token {token_id[:12]}…[/]")
            console.print("hint: run `fetch --with-trades` for the parent market first")
            return

        engine = Engine(
            strat,
            bars,
            token_id=token_id,
            initial_cash=initial_cash,
            fee_rate=fee_rate,
            slippage=slippage,
        )
        run = engine.run()
        m = metrics_mod.compute_all(run.equity_curve, run.trades, run.fees_paid)

        # Persist run
        store.insert_run({
            "run_id": run.run_id,
            "strategy_name": run.strategy_name,
            "params": run.params,
            "token_id": run.token_id,
            "start_ts": int(run.equity_curve.index[0].timestamp()),
            "end_ts": int(run.equity_curve.index[-1].timestamp()),
            "initial_cash": run.initial_cash,
            "final_equity": run.final_equity,
            "metrics": m,
            "trades": [_trade_to_dict(t) for t in run.trades],
            "equity_curve": [
                {"ts": int(idx.timestamp()), "eq": float(v)}
                for idx, v in run.equity_curve.items()
            ],
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        })

    print_run_report(run, m, console=console)
    if save_plot:
        save_equity_plot(run, save_plot)
        console.print(f"[green]✓[/] saved equity curve to {save_plot}")


# ---------- report ----------


@cli.command()
@click.argument("run_id")
@click.pass_context
def report(ctx: click.Context, run_id: str) -> None:
    """Re-render a stored run's report."""
    with Store(ctx.obj["db"]) as store:
        r = store.get_run(run_id)
    if not r:
        console.print(f"[red]run {run_id} not found[/]")
        return
    # Reconstruct enough of a Run for print_run_report
    import pandas as pd

    eq = pd.Series(
        data=[p["eq"] for p in r["equity_curve"]],
        index=pd.to_datetime([p["ts"] for p in r["equity_curve"]], unit="s", utc=True),
    )

    class _ReplayedRun:
        run_id = r["run_id"]
        strategy_name = r["strategy_name"]
        token_id = r["token_id"]
        initial_cash = r["initial_cash"]
        final_equity = r["final_equity"]
        equity_curve = eq
        trades = [_dict_to_trade(t) for t in r["trades"]]
        fees_paid = r["metrics"].get("fees_paid", 0.0)
        params = r["params"]
        bars = None

        @classmethod
        def summary(cls) -> dict:
            return {
                "initial_cash": cls.initial_cash,
                "final_equity": cls.final_equity,
                "return_pct": (cls.final_equity / cls.initial_cash - 1) * 100 if cls.initial_cash else 0,
                "n_trades": len(cls.trades),
                "fees_paid": cls.fees_paid,
            }

    print_run_report(_ReplayedRun, r["metrics"], console=console)


# ---------- runs ----------


@cli.command()
@click.option("--limit", default=20, show_default=True)
@click.pass_context
def runs(ctx: click.Context, limit: int) -> None:
    """Show recent backtest runs."""
    with Store(ctx.obj["db"]) as store:
        rows = store.list_runs(limit=limit)
    if not rows:
        console.print("[yellow]no runs yet[/]")
        return
    tbl = Table(title="Recent runs")
    tbl.add_column("run_id", style="dim")
    tbl.add_column("strategy")
    tbl.add_column("token", style="dim")
    tbl.add_column("return", justify="right")
    tbl.add_column("when", style="dim")
    for r in rows:
        ret = (r["final_equity"] / r["initial_cash"] - 1) * 100 if r["initial_cash"] else 0
        color = "green" if ret >= 0 else "red"
        tbl.add_row(
            r["run_id"],
            r["strategy_name"],
            r["token_id"][:10] + "…",
            f"[{color}]{ret:+.2f}%[/]",
            r["created_at"][:19],
        )
    console.print(tbl)


# ---------- helpers ----------


def _instantiate_strategy(spec: str, **kwargs):
    if spec in _BUILTIN_STRATEGIES:
        module, cls = _BUILTIN_STRATEGIES[spec]
    elif ":" in spec:
        module, cls = spec.split(":", 1)
    else:
        raise click.BadParameter(
            f"unknown strategy '{spec}' — use one of {list(_BUILTIN_STRATEGIES)} or 'module:Class'"
        )
    mod = importlib.import_module(module)
    klass = getattr(mod, cls)
    return klass(**kwargs)


def _trade_to_dict(t) -> dict:
    return {
        "timestamp": t.timestamp.isoformat(),
        "token_id": t.token_id,
        "side": t.side,
        "qty": t.qty,
        "price": t.price,
        "notional": t.notional,
        "fee": t.fee,
        "role": t.role,
        "reason": t.reason,
    }


def _dict_to_trade(d: dict):
    from src.sim.engine import FilledTrade
    return FilledTrade(
        timestamp=dt.datetime.fromisoformat(d["timestamp"]),
        token_id=d["token_id"],
        side=d["side"],
        qty=d["qty"],
        price=d["price"],
        notional=d["notional"],
        fee=d["fee"],
        role=d["role"],
        reason=d.get("reason", ""),
    )


if __name__ == "__main__":
    cli()
