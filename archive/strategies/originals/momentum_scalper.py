"""Momentum Scalper with Multi-Factor Entry Confirmation.

Builds on the winning momentum_sma approach but adds:
1. RSI filter to avoid overbought entries
2. Volume confirmation for entries
3. Shorter lookback for more responsive signals
4. Tighter profit-taking to lock in gains across more markets

Key insight: The baseline momentum wins on trending markets but loses
on flat ones. We improve by being more selective (quality > quantity).
"""

from __future__ import annotations

from typing import Iterable

import numpy as np

from strategies.base import CashOutStrategy
from src.strategy.base import Bar, Order, PortfolioView, Side


class MomentumScalper(CashOutStrategy):
    """Enhanced SMA momentum with RSI + Volume gates."""

    def __init__(
        self,
        lookback: int = 15,
        entry_pct: float = 0.015,
        exit_pct: float = 0.015,
        rsi_period: int = 10,
        rsi_overbought: float = 72.0,
        rsi_oversold: float = 28.0,
        vol_spike: float = 1.1,
        position_size_usd: float = 100.0,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.lookback = lookback
        self.entry_pct = entry_pct
        self.exit_pct = exit_pct
        self.rsi_period = rsi_period
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold
        self.vol_spike = vol_spike
        self.position_size_usd = position_size_usd

    @property
    def params(self) -> dict:
        return {
            "lookback": self.lookback,
            "entry_pct": self.entry_pct,
            "exit_pct": self.exit_pct,
            "rsi_period": self.rsi_period,
            "rsi_overbought": self.rsi_overbought,
            "rsi_oversold": self.rsi_oversold,
            "vol_spike": self.vol_spike,
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

        # EXIT: price drops below SMA by exit threshold
        if held_qty > 0 and bar.close < sma_val * (1.0 - self.exit_pct):
            return [Order(token_id=bar.token_id, side=Side.SELL,
                          size=held_qty, reason="sma-exit")]

        # EXIT: RSI overbought (take profit)
        if held_qty > 0 and rsi_val > self.rsi_overbought:
            return [Order(token_id=bar.token_id, side=Side.SELL,
                          size=held_qty, reason="rsi-exit")]

        # ENTRY: price above SMA by entry threshold
        if held_qty == 0 and bar.close > sma_val * (1.0 + self.entry_pct):
            # Not overbought
            if rsi_val > self.rsi_overbought:
                return []
            # Volume confirmation
            if vol_ratio < self.vol_spike:
                return []
            if portfolio.cash < self.position_size_usd:
                return []
            qty = self.position_size_usd / bar.close
            return [Order(token_id=bar.token_id, side=Side.BUY,
                          size=qty, reason="sma-entry")]

        # SECONDARY ENTRY: bounce from oversold in uptrend
        if held_qty == 0 and rsi_val < self.rsi_oversold:
            # Check if still in uptrend (price above longer SMA)
            sma_long = self.sma(self.lookback * 2)
            if sma_long > 0 and bar.close > sma_long:
                if portfolio.cash < self.position_size_usd:
                    return []
                qty = self.position_size_usd / bar.close
                return [Order(token_id=bar.token_id, side=Side.BUY,
                              size=qty, reason="oversold-bounce")]

        return []
