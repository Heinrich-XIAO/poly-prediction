from __future__ import annotations

from collections import deque
from typing import Iterable

from strategies.base import CashOutStrategy
from src.strategy.base import Bar, Order, PortfolioView, Side


class MomentumSMA(CashOutStrategy):
    """SMA crossover momentum: buy on uptrend, sell on reversal."""

    def __init__(self, lookback: int = 20, entry_threshold: float = 0.02,
                 exit_threshold: float = 0.02, position_size_usd: float = 100.0, **kwargs):
        super().__init__(**kwargs)
        self.lookback = lookback
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
        self.position_size_usd = position_size_usd
        self._closes: deque[float] = deque(maxlen=lookback)

    @property
    def params(self) -> dict:
        return {
            "lookback": self.lookback,
            "entry_threshold": self.entry_threshold,
            "exit_threshold": self.exit_threshold,
            "position_size_usd": self.position_size_usd,
        }

    def _on_bar(self, bar: Bar, portfolio: PortfolioView) -> Iterable[Order]:
        self._closes.append(bar.close)
        if len(self._closes) < self.lookback:
            return []

        sma = sum(self._closes) / len(self._closes)
        held_qty = portfolio.position(bar.token_id).qty

        if held_qty > 0 and bar.close < sma * (1.0 - self.exit_threshold):
            return [Order(token_id=bar.token_id, side=Side.SELL, size=held_qty, reason="sma-exit")]

        if held_qty == 0 and bar.close > sma * (1.0 + self.entry_threshold):
            if portfolio.cash < self.position_size_usd:
                return []
            qty = self.position_size_usd / bar.close
            return [Order(token_id=bar.token_id, side=Side.BUY, size=qty, reason="sma-entry")]

        return []
