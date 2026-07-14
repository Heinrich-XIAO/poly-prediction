"""Terminal + file-based reporting for backtest runs.

Two surfaces:
- `print_run_report(run, metrics)` — Rich table + summary, for CLI runs.
- `save_equity_plot(run, path)` — matplotlib equity curve PNG, for sharing.

Both are intentionally read-only; reports never mutate the Run object.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.sim.engine import Run


def print_run_report(run: Run, metrics: dict, console: Console | None = None) -> None:
    console = console or Console()

    summary = run.summary()
    header = (
        f"[bold cyan]{run.strategy_name}[/]  "
        f"[dim]run {run.run_id}[/]  "
        f"[dim]token {run.token_id[:12]}…[/]"
    )
    console.print(Panel.fit(header, border_style="cyan"))

    # ----- Summary table -----
    summary_tbl = Table(show_header=False, box=None, pad_edge=False)
    summary_tbl.add_column(style="dim")
    summary_tbl.add_column(justify="right")
    summary_tbl.add_row("initial cash", f"${summary['initial_cash']:,.2f}")
    summary_tbl.add_row(
        "final equity",
        f"[{'green' if summary['final_equity'] >= summary['initial_cash'] else 'red'}]"
        f"${summary['final_equity']:,.2f}[/]",
    )
    summary_tbl.add_row(
        "return",
        f"[{'green' if summary['return_pct'] >= 0 else 'red'}]{summary['return_pct']:+.2f}%[/]",
    )
    summary_tbl.add_row("# trades", str(summary["n_trades"]))
    summary_tbl.add_row("fees paid", f"${summary['fees_paid']:,.4f}")
    console.print(summary_tbl)
    console.print()

    # ----- Metrics table -----
    m_tbl = Table(title="Performance metrics", title_style="bold", header_style="bold")
    m_tbl.add_column("metric")
    m_tbl.add_column("value", justify="right")
    rows = [
        ("Total return",   f"{metrics['total_return'] * 100:+.2f}%"),
        ("CAGR",           f"{metrics['cagr'] * 100:+.2f}%"),
        ("Max drawdown",   f"{metrics['max_drawdown'] * 100:+.2f}%"),
        ("Sharpe",         f"{metrics['sharpe']:.3f}"),
        ("Sortino",        f"{metrics['sortino']:.3f}"),
        ("Calmar",         f"{metrics['calmar']:.3f}"),
        ("Hit rate",       f"{metrics['hit_rate'] * 100:.1f}%"),
        ("Avg win",        f"${metrics['avg_win']:.4f}"),
        ("Avg loss",       f"${metrics['avg_loss']:.4f}"),
        ("Profit factor",  f"{metrics['profit_factor']:.2f}"),
    ]
    for k, v in rows:
        m_tbl.add_row(k, v)
    console.print(m_tbl)
    console.print()

    # ----- Last few trades -----
    if run.trades:
        t_tbl = Table(title=f"Last {min(10, len(run.trades))} trades", header_style="bold")
        t_tbl.add_column("time")
        t_tbl.add_column("side")
        t_tbl.add_column("qty", justify="right")
        t_tbl.add_column("price", justify="right")
        t_tbl.add_column("notional", justify="right")
        t_tbl.add_column("fee", justify="right")
        t_tbl.add_column("reason", style="dim")
        for ft in run.trades[-10:]:
            color = "green" if ft.side == "BUY" else "red"
            t_tbl.add_row(
                ft.timestamp.strftime("%Y-%m-%d %H:%M"),
                f"[{color}]{ft.side}[/]",
                f"{ft.qty:.4f}",
                f"${ft.price:.4f}",
                f"${ft.notional:.2f}",
                f"${ft.fee:.4f}",
                ft.reason,
            )
        console.print(t_tbl)


def save_equity_plot(run: Run, path: str | Path) -> None:
    """Save an equity-curve PNG to `path`. Requires matplotlib."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 4), dpi=120)
    ax.plot(run.equity_curve.index, run.equity_curve.values, linewidth=1.2)
    ax.axhline(run.initial_cash, color="grey", linestyle="--", linewidth=0.8, alpha=0.5)
    ax.set_title(f"{run.strategy_name} — equity curve")
    ax.set_xlabel("time")
    ax.set_ylabel("equity (pUSD)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
