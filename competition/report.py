from __future__ import annotations

from rich.console import Console
from rich.table import Table

from competition.runner import ComparisonResult


def print_comparison_report(result: ComparisonResult, console: Console | None = None) -> None:
    console = console or Console()
    console.rule("[bold cyan]Competition Results[/bold cyan]")
    console.print(f"token: {result.token_id[:16]}…  bars: {len(result.bars)}  cash: ${result.initial_cash:.0f}")
    console.print()

    tbl = Table(title="Strategy Leaderboard", header_style="bold")
    tbl.add_column("Rank", justify="right", style="dim")
    tbl.add_column("Strategy")
    tbl.add_column("Return", justify="right")
    tbl.add_column("Sharpe", justify="right")
    tbl.add_column("Max DD", justify="right")
    tbl.add_column("Trades", justify="right")
    tbl.add_column("Fees", justify="right")

    for rank, (name, ret) in enumerate(result.rankings, 1):
        m = result.metrics[name]
        ret_color = "green" if ret >= 0 else "red"
        tbl.add_row(
            str(rank),
            name,
            f"[{ret_color}]{ret * 100:+.2f}%[/]",
            f"{m['sharpe']:.2f}",
            f"{m['max_drawdown'] * 100:.1f}%",
            str(m["n_trades"]),
            f"${m['fees_paid']:.2f}",
        )
    console.print(tbl)


def print_leaderboard(rows: list[dict], console: Console | None = None) -> None:
    console = console or Console()
    tbl = Table(title="All-Time Leaderboard", header_style="bold")
    tbl.add_column("Strategy")
    tbl.add_column("Avg Return", justify="right")
    tbl.add_column("Avg Sharpe", justify="right")
    tbl.add_column("Runs", justify="right")
    tbl.add_column("Last Run", style="dim")

    for r in rows:
        color = "green" if r["avg_return"] >= 0 else "red"
        tbl.add_row(
            r["strategy"],
            f"[{color}]{r['avg_return'] * 100:+.2f}%[/]",
            f"{r['avg_sharpe']:.2f}",
            str(r["runs"]),
            (r["last_run"] or "")[:10],
        )
    console.print(tbl)
