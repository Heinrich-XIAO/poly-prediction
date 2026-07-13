"""Volume-Activated Buy and Hold.

Key insight: buy_and_hold works because it enters early. But it loses on markets
that go down. My edge: only enter when volume spikes suggest the market is about
to move, and use cash-out to protect profits.

Inspired by carbs (volume as energy) and buy_and_hold's proven early-entry edge.
"""

from __future__ import annotations

from typing import Iterable

import numpy as np

from strategies.base import CashOutStrategy, with_cash_out
from src.strategy.base import Bar, Order, PortfolioView, Side


class VolumeActivatedBuyHold(CashOutStrategy):
    """Buy when volume spikes signal directional move, with cash-out protection."""

    def __init__(
        self,
        vol_spike_threshold: float = 2.0,
        entry_window: int = 10,
        min_price: float = 0.03,
        max_price: float = 0.97,
        position_size_pct: float = 0.90,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.vol_spike_threshold = vol_spike_threshold
        self.entry_window = entry_window
        self.min_price = min_price
        self.max_price = max_price
        self.position_size_pct = position_size_pct
        self._bought = False

    @property
    def params(self) -> dict:
        return {
            "vol_spike_threshold": self.vol_spike_threshold,
            "entry_window": self.entry_window,
            "min_price": self.min_price,
            "max_price": self.max_price,
            "position_size_pct": self.position_size_pct,
        }

    def _on_bar(self, bar: Bar, portfolio: PortfolioView) -> Iterable[Order]:
        if self._bought:
            return []

        price = bar.close

        # Skip extreme prices
        if price < self.min_price or price > self.max_price:
            return []

        # Wait for entry window
        if self.n_bars < self.entry_window:
            return []

        # Check for volume spike
        vol_ratio = self.volume_ratio(10)

        if vol_ratio >= self.vol_spike_threshold:
            budget = portfolio.cash * self.position_size_pct
            if budget < 10:
                return []
            qty = budget / price
            self._bought = True
            return [Order(token_id=bar.token_id, side=Side.BUY,
                          size=qty, reason="vol-spike-entry")]

        return []
