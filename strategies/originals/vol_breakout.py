"""Volatility Breakout Strategy.

Key insight: Polymarket binary markets are flat ~97% of the time.
When they move, it's sudden. Catch the breakout with volume confirmation,
take quick profits, cut losses fast.
"""

from __future__ import annotations

from typing import Iterable

import numpy as np

from strategies.base import CashOutStrategy
from src.strategy.base import Bar, Order, PortfolioView, Side


class VolatilityBreakout(CashOutStrategy):
    """Buy breakouts confirmed by volume; exit quickly on profit or reversal."""

    def __init__(
        self,
        lookback: int = 20,
        breakout_threshold: float = 0.01,
        vol_spike: float = 2.0,
        rsi_period: int = 14,
        take_profit_pct: float = 0.08,
        stop_loss_pct: float = 0.05,
        position_size_usd: float = 100.0,
        min_volatility: float = 0.0003,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.lookback = lookback
        self.breakout_threshold = breakout_threshold
        self.vol_spike = vol_spike
        self.rsi_period = rsi_period
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.position_size_usd = position_size_usd
        self.min_volatility = min_volatility
        self._my_entry_price: float = 0.0

    @property
    def params(self) -> dict:
        return {
            "lookback": self.lookback,
            "breakout_threshold": self.breakout_threshold,
            "vol_spike": self.vol_spike,
            "take_profit_pct": self.take_profit_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "position_size_usd": self.position_size_usd,
            "min_volatility": self.min_volatility,
        }

    def _on_bar(self, bar: Bar, portfolio: PortfolioView) -> Iterable[Order]:
        if self.n_bars < self.lookback + 2:
            return []

        closes = self.closes
        held_qty = portfolio.position(bar.token_id).qty

        # Volatility gate
        returns = np.diff(closes[-self.lookback:]) / closes[-self.lookback:-1]
        returns = returns[~np.isnan(returns) & ~np.isinf(returns)]
        if len(returns) < 10:
            return []
        volatility = float(np.std(returns))
        if volatility < self.min_volatility:
            return []

        vol_ratio = self.volume_ratio(20)

        # EXIT logic
        if held_qty > 0 and self._my_entry_price > 0:
            pnl_pct = (bar.close - self._my_entry_price) / self._my_entry_price
            # Take profit
            if pnl_pct >= self.take_profit_pct:
                return [Order(token_id=bar.token_id, side=Side.SELL,
                              size=held_qty, reason="take-profit")]
            # Stop loss
            if pnl_pct <= -self.stop_loss_pct:
                return [Order(token_id=bar.token_id, side=Side.SELL,
                              size=held_qty, reason="stop-loss")]
            # Reversal exit: price drops below entry by more than half the stop
            if pnl_pct <= -self.stop_loss_pct * 0.5 and bar.close < closes[-2]:
                return [Order(token_id=bar.token_id, side=Side.SELL,
                              size=held_qty, reason="reversal-exit")]
            return []

        # ENTRY: breakout above recent range with volume
        recent_high = float(np.max(closes[-self.lookback:]))
        recent_low = float(np.min(closes[-self.lookback:]))
        price_range = recent_high - recent_low

        if price_range <= 0:
            return []

        # Bullish breakout: price breaks above recent high
        if bar.close > recent_high * (1.0 + self.breakout_threshold * 0.5):
            if vol_ratio < self.vol_spike:
                return []
            if portfolio.cash < self.position_size_usd:
                return []
            qty = self.position_size_usd / bar.close
            self._my_entry_price = bar.close
            return [Order(token_id=bar.token_id, side=Side.BUY,
                          size=qty, reason="breakout-up")]

        # Sharp momentum entry: price surges with volume
        price_change_3 = self.price_change(3)
        if (price_change_3 > self.breakout_threshold and
                vol_ratio >= self.vol_spike * 1.5):
            if portfolio.cash < self.position_size_usd:
                return []
            qty = self.position_size_usd / bar.close
            self._my_entry_price = bar.close
            return [Order(token_id=bar.token_id, side=Side.BUY,
                          size=qty, reason="momentum-surge")]

        return []
