from __future__ import annotations

from typing import Iterable

from strategies.base import CashOutStrategy
from src.strategy.base import Bar, Order, PortfolioView, Side


class BuyAndHold(CashOutStrategy):
    """Buy once on the first bar with sufficient cash, then go flat on exit signal."""

    def __init__(self, allocation_pct: float = 0.95, **kwargs):
        super().__init__(**kwargs)
        self.allocation_pct = allocation_pct
        self._bought = False
        self._initial_cash: float | None = None

    @property
    def params(self) -> dict:
        return {"allocation_pct": self.allocation_pct}

    def _on_bar(self, bar: Bar, portfolio: PortfolioView) -> Iterable[Order]:
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
