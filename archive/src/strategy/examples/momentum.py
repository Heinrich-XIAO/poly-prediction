"""Simple SMA-crossover momentum strategy.

Goes long when close crosses above the SMA by `entry_threshold`, exits when
close crosses below by `exit_threshold`. Demonstrates the typical pattern:
maintain rolling state in `__init__`-initialized buffers, emit Orders.

Don't expect this to make money on prediction markets — it's an example, not
an alpha. Useful as a sanity check on the engine.
"""

from __future__ import annotations

from collections import deque
from typing import Iterable

from src.strategy.base import Bar, Order, PortfolioView, Side, Strategy


class MomentumSMA(Strategy):
    def __init__(
        self,
        lookback: int = 20,
        entry_threshold: float = 0.02,  # close > sma * (1 + entry_threshold) → buy
        exit_threshold: float = 0.02,   # close < sma * (1 - exit_threshold) → sell
        position_size_usd: float = 100.0,
    ):
        if lookback < 2:
            raise ValueError("lookback must be >= 2")
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

    def on_bar(self, bar: Bar, portfolio: PortfolioView) -> Iterable[Order]:
        self._closes.append(bar.close)
        if len(self._closes) < self.lookback:
            return []

        sma = sum(self._closes) / len(self._closes)
        held_qty = portfolio.position(bar.token_id).qty

        # Exit first — never overlap a sell with a fresh buy on the same bar.
        if held_qty > 0 and bar.close < sma * (1.0 - self.exit_threshold):
            return [Order(token_id=bar.token_id, side=Side.SELL, size=held_qty, reason="sma-exit")]

        # Entry only when flat.
        if held_qty == 0 and bar.close > sma * (1.0 + self.entry_threshold):
            if portfolio.cash < self.position_size_usd:
                return []
            qty = self.position_size_usd / bar.close
            return [Order(token_id=bar.token_id, side=Side.BUY, size=qty, reason="sma-entry")]

        return []
