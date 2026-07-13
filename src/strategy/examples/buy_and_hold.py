"""Buy-and-hold reference strategy.

Buys once on the first bar with sufficient cash, then does nothing. Useful as
a baseline — every other strategy needs to beat this on the same market.
"""

from __future__ import annotations

from typing import Iterable

from src.strategy.base import Bar, Order, PortfolioView, Side, Strategy


class BuyAndHold(Strategy):
    def __init__(self, allocation_pct: float = 0.95):
        """allocation_pct: fraction of starting cash to deploy on first fill (0..1)."""
        if not 0 < allocation_pct <= 1:
            raise ValueError("allocation_pct must be in (0, 1]")
        self.allocation_pct = allocation_pct
        self._bought = False
        self._initial_cash: float | None = None

    @property
    def params(self) -> dict:
        return {"allocation_pct": self.allocation_pct}

    def on_bar(self, bar: Bar, portfolio: PortfolioView) -> Iterable[Order]:
        if self._bought:
            return []
        if self._initial_cash is None:
            self._initial_cash = portfolio.cash
        if portfolio.cash <= 0 or bar.close <= 0:
            return []
        budget = self._initial_cash * self.allocation_pct
        qty = budget / bar.close
        self._bought = True
        return [Order(token_id=bar.token_id, side=Side.BUY, size=qty, reason="initial-buy")]
