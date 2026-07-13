from __future__ import annotations

from dataclasses import dataclass, field
from typing import Type

from src.strategy.base import Strategy


@dataclass
class StrategyRecord:
    name: str
    strategy_class: Type[Strategy]
    default_params: dict = field(default_factory=dict)
    category_tags: list[str] = field(default_factory=list)
    description: str = ""


registry: dict[str, StrategyRecord] = {}


def register(record: StrategyRecord) -> StrategyRecord:
    registry[record.name] = record
    return record


def list_strategies(category: str | None = None) -> list[StrategyRecord]:
    recs = list(registry.values())
    if category:
        recs = [r for r in recs if category in r.category_tags]
    return sorted(recs, key=lambda r: r.name)
