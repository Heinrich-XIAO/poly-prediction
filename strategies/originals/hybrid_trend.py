"""Hybrid Trend + Breakout Strategy.

Combines momentum's trend-following with breakout's selectivity:
- SMA crossover for trend entries (like momentum)
- Volume + RSI filters for quality (like breakout)
- Trailing stop to lock in gains on trends
- Quick exit on reversal signals
"""

from __future__ import annotations

from typing import Iterable

import numpy as np

from strategies.base import CashOutStrategy
from src.strategy.base import Bar, Order, PortfolioView, Side


class HybridTrendBreakout(CashOutStrategy):
    """Trend following with breakout filters and trailing stop."""

    def __init__(
        self,
        lookback: int = 18,
        entry_pct: float = 0.015,
        exit_pct: float = 0.02,
        rsi_period: int = 10,
        rsi_max_entry: float = 70.0,
        vol_spike: float = 1.2,
        trailing_pct: float = 0.03,
        position_size_usd: float = 100.0,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.lookback = lookback
        self.entry_pct = entry_pct
        self.exit_pct = exit_pct
        self.rsi_period = rsi_period
        self.rsi_max_entry = rsi_max_entry
        self.vol_spike = vol_spike
        self.trailing_pct = trailing_pct
        self.position_size_usd = position_size_usd
        self._peak_price: float = 0.0

    @property
    def params(self) -> dict:
        return {
            "lookback": self.lookback,
            "entry_pct": self.entry_pct,
            "exit_pct": self.exit_pct,
            "rsi_period": self.rsi_period,
            "rsi_max_entry": self.rsi_max_entry,
            "vol_spike": self.vol_spike,
            "trailing_pct": self.trailing_pct,
            "position_size_usd": self.position_size_usd,
        }

    def _on_bar(self, bar: Bar, portfolio: PortfolioView) -> Iterable[Order]:
        if self.n_bars < self.lookback + 2:
            return []

        closes = self.closes
        sma_val = self.sma(self.lookback)
        if sma_val <= 0:
            return []

        rsi_val = self.rsi(self.rsi_period)
        vol_ratio = self.volume_ratio(20)
        held_qty = portfolio.position(bar.token_id).qty

        # EXIT logic
        if held_qty > 0:
            # Update peak price for trailing stop
            if bar.close > self._peak_price:
                self._peak_price = bar.close

            # Trailing stop: exit if price drops trailing_pct from peak
            if self._peak_price > 0:
                drawdown = (self._peak_price - bar.close) / self._peak_price
                if drawdown >= self.trailing_pct:
                    return [Order(token_id=bar.token_id, side=Side.SELL,
                                  size=held_qty, reason="trailing-stop")]

            # Trend exit: price drops below SMA by exit threshold
            if bar.close < sma_val * (1.0 - self.exit_pct):
                return [Order(token_id=bar.token_id, side=Side.SELL,
                              size=held_qty, reason="sma-exit")]

            return []

        # ENTRY logic: SMA breakout with filters
        if bar.close > sma_val * (1.0 + self.entry_pct):
            # Not overbought
            if rsi_val > self.rsi_max_entry:
                return []
            # Volume confirmation
            if vol_ratio < self.vol_spike:
                return []
            # Price should be making new local high (breakout confirmation)
            recent_high = float(np.max(closes[-self.lookback:]))
            if bar.close < recent_high * 0.99:
                return []
            if portfolio.cash < self.position_size_usd:
                return []
            qty = self.position_size_usd / bar.close
            self._peak_price = bar.close
            return [Order(token_id=bar.token_id, side=Side.BUY,
                          size=qty, reason="trend-breakout")]

        # Secondary: bounce from oversold in uptrend
        sma_long = self.sma(self.lookback * 2)
        if (rsi_val < 25 and sma_long > 0 and bar.close > sma_long
                and vol_ratio >= self.vol_spike * 0.8):
            if portfolio.cash < self.position_size_usd:
                return []
            qty = self.position_size_usd / bar.close
            self._peak_price = bar.close
            return [Order(token_id=bar.token_id, side=Side.BUY,
                          size=qty, reason="oversold-bounce")]

        return []
