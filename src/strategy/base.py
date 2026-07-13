"""Strategy interface + Order / Bar primitives.

Subclass `Strategy` and implement `on_bar`. Return zero or more `Order`s; the
engine handles the rest (validation, slippage, fees, fills, PnL).

Strategies receive a read-only portfolio view — the engine enforces that. If
you find yourself wanting to mutate the portfolio, you're trying to bypass the
validation/fee pipeline. Don't.
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Protocol

from src.sim.fees import Role


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class Bar:
    """OHLCV bar passed to strategies, one per period."""

    timestamp: dt.datetime
    token_id: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float
    trades: int


@dataclass(frozen=True)
class Order:
    """Strategy-emitted order. Filled at the next bar."""

    token_id: str
    side: Side
    size: float
    role: Role = Role.TAKER  # default to taker; flip to MAKER for limit-style sims
    reason: str = ""         # optional tag, surfaces in trade log


class PortfolioView(Protocol):
    """Type alias for what strategies see. The engine passes a real read-only proxy."""

    @property
    def cash(self) -> float: ...

    def position(self, token_id: str): ...

    def has_position(self, token_id: str) -> bool: ...

    def equity(self, marks: dict[str, float]) -> float: ...


class Strategy(ABC):
    """Subclass and implement `on_bar`."""

    @property
    def params(self) -> dict:
        """Override to return the strategy's hyperparameters for logging."""
        return {}

    @abstractmethod
    def on_bar(self, bar: Bar, portfolio: PortfolioView) -> Iterable[Order]:
        """Called once per bar. Return zero or more Orders to fill at next bar."""
        ...
