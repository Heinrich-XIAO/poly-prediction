from __future__ import annotations

from rich.console import Console
from rich.table import Table

from competition.runner import ComparisonResult


def print_comparison_report(result: ComparisonResult, console: Console | None = None) -> None:
    console = console or Console()
    console.rule("[bold cyan]Competition Results[/bold cyan]")
    console.print(f"Markets: {len(result.markets)}  Cash/ market: ${result.initial_cash:.0f}")
    console.print()

    # Aggregate leaderboard
    tbl = Table(title="Aggregate Leaderboard (all markets)", header_style="bold")
    tbl.add_column("Rank", justify="right", style="dim")
    tbl.add_column("Strategy")
    tbl.add_column("Total Return", justify="right")
    tbl.add_column("Avg Return", justify="right")
    tbl.add_column("Win Rate", justify="right")
    tbl.add_column("Avg Sharpe", justify="right")
    tbl.add_column("Avg Max DD", justify="right")
    tbl.add_column("Trades", justify="right")
    tbl.add_column("Fees", justify="right")

    for rank, (name, _) in enumerate(result.rankings, 1):
        m = result.aggregate_metrics[name]
        color = "green" if m["total_return"] >= 0 else "red"
        tbl.add_row(
            str(rank),
            name,
            f"[{color}]{m['total_return'] * 100:+.2f}%[/]",
            f"{m['avg_return'] * 100:+.2f}%",
            f"{m['win_rate'] * 100:.0f}%",
            f"{m['avg_sharpe']:.2f}",
            f"{m['avg_max_drawdown'] * 100:.1f}%",
            str(m["total_trades"]),
            f"${m['total_fees']:.2f}",
        )
    console.print(tbl)
    console.print()

    # Per-market detail
    console.rule("[dim]Per-Market Detail[/dim]")
    for mres in result.markets:
        console.print(f"\n[bold]{mres.question[:60]}[/bold]  ({mres.n_bars} bars)")
        sub = Table(header_style="dim")
        sub.add_column("Strategy")
        sub.add_column("Return", justify="right")
        sub.add_column("Sharpe", justify="right")
        sub.add_column("Max DD", justify="right")
        sub.add_column("Trades", justify="right")
        sub.add_column("Fees", justify="right")

        for name, _ in result.rankings:
            if name not in mres.metrics:
                sub.add_row(name, "[dim]skipped[/dim]", "", "", "", "")
                continue
            met = mres.metrics[name]
            sc = "green" if met["total_return"] >= 0 else "red"
            sub.add_row(
                name,
                f"[{sc}]{met['total_return'] * 100:+.2f}%[/]",
                f"{met['sharpe']:.2f}",
                f"{met['max_drawdown'] * 100:.1f}%",
                str(met["n_trades"]),
                f"${met['fees_paid']:.2f}",
            )
        console.print(sub)


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
