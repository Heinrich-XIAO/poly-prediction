"""Momentum with Adaptive Exit.

Uses momentum_sma's proven entry logic but with two exit modes:
1. Fast exit: SMA breakdown (like original) - captures quick reversals
2. Slow exit: Wider trailing stop - holds through minor pullbacks

The key insight: on Weinstein, momentum_sma exits at -9% drawdown because
SMA crossover triggers. A wider trailing stop would hold longer and capture
more of the trend.
"""

from __future__ import annotations

from typing import Iterable

from strategies.base import CashOutStrategy
from src.strategy.base import Bar, Order, PortfolioView, Side


class MomentumAdaptive(CashOutStrategy):
    """Momentum SMA entry + adaptive exit (SMA or trailing)."""

    def __init__(
        self,
        lookback: int = 20,
        entry_threshold: float = 0.02,
        trailing_pct: float = 0.08,
        position_size_usd: float = 100.0,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.lookback = lookback
        self.entry_threshold = entry_threshold
        self.trailing_pct = trailing_pct
        self.position_size_usd = position_size_usd
        self._peak_price: float = 0.0

    @property
    def params(self) -> dict:
        return {
            "lookback": self.lookback,
            "entry_threshold": self.entry_threshold,
            "trailing_pct": self.trailing_pct,
            "position_size_usd": self.position_size_usd,
        }

    def _on_bar(self, bar: Bar, portfolio: PortfolioView) -> Iterable[Order]:
        if self.n_bars < self.lookback:
            return []

        sma = self.sma(self.lookback)
        if sma <= 0:
            return []

        held_qty = portfolio.position(bar.token_id).qty

        # EXIT logic
        if held_qty > 0:
            if bar.close > self._peak_price:
                self._peak_price = bar.close

            # Trailing stop exit (wider - 8%)
            drawdown = (self._peak_price - bar.close) / self._peak_price if self._peak_price > 0 else 0
            if drawdown >= self.trailing_pct:
                self._peak_price = 0.0
                return [Order(token_id=bar.token_id, side=Side.SELL,
                              size=held_qty, reason="trailing-stop")]

            # SMA exit (tight - like original)
            if bar.close < sma * (1.0 - self.entry_threshold):
                self._peak_price = 0.0
                return [Order(token_id=bar.token_id, side=Side.SELL,
                              size=held_qty, reason="sma-exit")]

            return []

        # ENTRY: same as momentum_sma
        if bar.close > sma * (1.0 + self.entry_threshold):
            if portfolio.cash < self.position_size_usd:
                return []
            qty = self.position_size_usd / bar.close
            self._peak_price = bar.close
            return [Order(token_id=bar.token_id, side=Side.BUY,
                          size=qty, reason="sma-entry")]

        return []
