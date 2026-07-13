"""Smart Trend Rider: Volume-Weighted Momentum with Adaptive Exit.

Key insight: buy_and_hold wins by entering early and holding forever.
It only profits on markets that trend up from the start (3/15 markets).
Those 3 markets generate +8.48% total.

My edge: Enter early like buy_and_hold BUT:
1. Only enter when there's early directional signal (not random noise)
2. Exit when trend weakens (protect against reversals)
3. Use volume as conviction filter (skip dead markets)
4. Adapt position sizing based on volatility
"""

from __future__ import annotations

from typing import Iterable

import numpy as np

from strategies.base import CashOutStrategy
from src.strategy.base import Bar, Order, PortfolioView, Side


class SmartTrendRider(CashOutStrategy):
    """Enter early on directional moves, exit on trend weakness."""

    def __init__(
        self,
        entry_window: int = 3,
        min_move_pct: float = 0.008,
        trailing_pct: float = 0.12,
        trend_exit_pct: float = 0.04,
        position_size_pct: float = 0.45,
        min_price: float = 0.03,
        max_price: float = 0.97,
        min_volatility: float = 0.0005,
        max_volatility: float = 0.06,
        max_hold_bars: int = 200,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.entry_window = entry_window
        self.min_move_pct = min_move_pct
        self.trailing_pct = trailing_pct
        self.trend_exit_pct = trend_exit_pct
        self.position_size_pct = position_size_pct
        self.min_price = min_price
        self.max_price = max_price
        self.min_volatility = min_volatility
        self.max_volatility = max_volatility
        self.max_hold_bars = max_hold_bars
        self._peak_price: dict[str, float] = {}
        self._entry_bar: dict[str, int] = {}
        self._entry_price: dict[str, float] = {}

    @property
    def params(self) -> dict:
        return {
            "entry_window": self.entry_window,
            "min_move_pct": self.min_move_pct,
            "trailing_pct": self.trailing_pct,
            "trend_exit_pct": self.trend_exit_pct,
            "position_size_pct": self.position_size_pct,
            "min_price": self.min_price,
            "max_price": self.max_price,
            "min_volatility": self.min_volatility,
            "max_volatility": self.max_volatility,
            "max_hold_bars": self.max_hold_bars,
        }

    def _on_bar(self, bar: Bar, portfolio: PortfolioView) -> Iterable[Order]:
        closes = self.closes
        price = bar.close
        n = self.n_bars

        # Skip extreme prices
        if price < self.min_price or price > self.max_price:
            return []

        held_qty = portfolio.position(bar.token_id).qty

        # EXIT logic
        if held_qty > 0:
            if price > self._peak_price.get(bar.token_id, 0):
                self._peak_price[bar.token_id] = price

            peak = self._peak_price[bar.token_id]
            entry = self._entry_price.get(bar.token_id, price)
            bars_held = n - self._entry_bar.get(bar.token_id, n)

            # Trailing stop
            drawdown = (peak - price) / peak if peak > 0 else 0
            if drawdown >= self.trailing_pct:
                self._cleanup(bar.token_id)
                return [Order(token_id=bar.token_id, side=Side.SELL,
                              size=held_qty, reason="trailing-stop")]

            # Trend weakening: price drops below SMA(10) and we're still profitable
            if n >= 10:
                sma10 = float(np.mean(closes[-10:]))
                unrealized = (price - entry) / entry if entry > 0 else 0
                if price < sma10 and unrealized > 0.01 and drawdown > self.trend_exit_pct:
                    self._cleanup(bar.token_id)
                    return [Order(token_id=bar.token_id, side=Side.SELL,
                                  size=held_qty, reason="trend-weakening")]

            # Time stop
            if bars_held >= self.max_hold_bars:
                self._cleanup(bar.token_id)
                return [Order(token_id=bar.token_id, side=Side.SELL,
                              size=held_qty, reason="time-exit")]

            return []

        # ENTRY: Check after entry_window bars
        if n < self.entry_window:
            return []

        # Look at the first entry_window bars to detect direction
        initial_price = closes[0]
        if initial_price <= 0:
            return []

        # Current move from start
        move_pct = (price - initial_price) / initial_price

        # Need at least min_move_pct in the right direction
        if abs(move_pct) < self.min_move_pct:
            return []

        # Volatility check
        if n >= 20:
            recent = closes[-20:]
            rets = np.diff(recent) / recent[:-1]
            rets = rets[np.isfinite(rets)]
            if len(rets) >= 5:
                vol = float(np.std(rets))
                if vol < self.min_volatility or vol > self.max_volatility:
                    return []

        # Volume check: need some activity
        vol_ratio = self.volume_ratio(10)
        if vol_ratio < 0.5:
            return []

        # Confirm direction with SMA alignment
        if n >= 10:
            sma_fast = float(np.mean(closes[-5:]))
            sma_slow = float(np.mean(closes[-10:]))

            # Buy signal: price going up, fast > slow, move positive
            if move_pct > 0 and sma_fast >= sma_slow:
                budget = portfolio.cash * self.position_size_pct
                if budget < 10:
                    return []
                qty = budget / price
                self._peak_price[bar.token_id] = price
                self._entry_bar[bar.token_id] = n
                self._entry_price[bar.token_id] = price
                return [Order(token_id=bar.token_id, side=Side.BUY,
                              size=qty, reason="smart-entry")]

        return []

    def _cleanup(self, token_id: str):
        self._peak_price.pop(token_id, None)
        self._entry_bar.pop(token_id, None)
        self._entry_price.pop(token_id, None)
