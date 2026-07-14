#!/usr/bin/env python3
"""Fetch random words → generate strategy ideas → test them.

Usage:
    python scripts/explore.py [--count 5] [--tag soccer] [--freq 5min]

This is the ideation pipeline described in the prompt:
  1. Fetch N random words
  2. Map each word to a strategy concept
  3. Print hints for manual strategy creation
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ideas.kindle import fetch_random_words, map_words_to_concepts, generate_strategy_hint
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def main():
    parser = argparse.ArgumentParser(description="Explore random strategy ideas")
    parser.add_argument("--count", type=int, default=5, help="Number of random words")
    args = parser.parse_args()

    console.rule("[bold cyan]Strategy Idea Generator[/bold cyan]")

    words = fetch_random_words(args.count)
    if not words:
        console.print("[red]Failed to fetch words.[/]")
        sys.exit(1)

    console.print(f"\n[bold]Random words:[/] ", end="")
    console.print(" • ".join(f"[yellow]{w}[/]" for w in words))
    console.print()

    concepts = map_words_to_concepts(words)
    tbl = Table(header_style="bold")
    tbl.add_column("Word")
    tbl.add_column("Strategy Concept")
    for w in words:
        tbl.add_row(f"[yellow]{w}[/]", concepts[w])
    console.print(tbl)
    console.print()

    hint = generate_strategy_hint(words)
    console.print(Panel(hint, title="Strategy Seed", border_style="green"))
    console.print()

    console.print("[dim]Write your strategy in strategies/originals/ and run:[/]")
    console.print("[dim]  python scripts/run_competition.py[/]")


if __name__ == "__main__":
    main()
