#!/usr/bin/env python3
"""Deep-dive into a Polymarket category: distributions, liquidity, resolution patterns.

Usage:
    python scripts/research_category.py --tag soccer [--freq 5min]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.statistics import category_distributions
from research.calendar_analysis import resolution_patterns
from src.data.store import Store
from rich.console import Console
from rich.table import Table

console = Console()


def main():
    parser = argparse.ArgumentParser(description="Research a market category")
    parser.add_argument("--tag", required=True, help="Category tag")
    parser.add_argument("--freq", default="5min", help="Bar frequency")
    parser.add_argument("--db", default="data/cache.db")
    args = parser.parse_args()

    with Store(args.db) as store:
        console.rule(f"[bold cyan]Category Research: {args.tag}[/bold cyan]")

        dist = category_distributions(store, args.tag, freq=args.freq)
        if not dist:
            console.print(f"[red]No markets found for tag '{args.tag}'. Run fetch first.[/]")
            sys.exit(1)

        console.print(f"\n[bold]Distribution:[/] {dist['n_markets']} markets")
        tbl = Table(header_style="bold")
        tbl.add_column("Metric")
        tbl.add_column("Value", justify="right")
        tbl.add_row("Markets", str(dist["n_markets"]))
        tbl.add_row("Avg price range", f"{dist['avg_price_range']:.4f}")
        tbl.add_row("Avg volume", f"{dist['avg_volume']:.0f}")
        tbl.add_row("Avg bars", f"{dist['avg_bars']:.0f}")
        console.print(tbl)

        res = resolution_patterns(store, tag=args.tag)
        if res:
            console.print(f"\n[bold]Resolution Patterns:[/] {res['n_markets']} markets")
            dow_tbl = Table(title="By Day of Week", header_style="bold")
            dow_tbl.add_column("Day")
            dow_tbl.add_column("Count", justify="right")
            for day, count in res.get("day_of_week", {}).items():
                dow_tbl.add_row(day, str(count))
            console.print(dow_tbl)


if __name__ == "__main__":
    main()
