"""MACD Trend Follower with incremental state (no O(n²) recalculation).

Tracks MACD state bar-by-bar for O(1) per-bar cost.
Buys on bullish MACD crossover when trend and volume confirm.
Exits on bearish crossover or short-SMA break.
"""

from __future__ import annotations

from typing import Iterable

import numpy as np

from strategies.base import CashOutStrategy
from src.strategy.base import Bar, Order, PortfolioView, Side


class MacdTrendFollower(CashOutStrategy):
    """MACD trend follower with incremental state tracking."""

    def __init__(
        self,
        fast: int = 12,
        slow: int = 26,
        signal_len: int = 9,
        rsi_period: int = 14,
        rsi_max_entry: float = 75.0,
        vol_lookback: int = 100,
        min_volatility: float = 0.0005,
        vol_spike: float = 1.0,
        position_size_usd: float = 150.0,
        exit_sma: int = 10,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.fast = fast
        self.slow = slow
        self.signal_len = signal_len
        self.rsi_period = rsi_period
        self.rsi_max_entry = rsi_max_entry
        self.vol_lookback = vol_lookback
        self.min_volatility = min_volatility
        self.vol_spike = vol_spike
        self.position_size_usd = position_size_usd
        self.exit_sma = exit_sma

        # Incremental EMA state
        self._fast_ema: float = 0.0
        self._slow_ema: float = 0.0
        self._signal_ema: float = 0.0
        self._macd_line: float = 0.0
        self._prev_histogram: float = 0.0
        self._ema_initialized: bool = False
        self._bar_count: int = 0

    @property
    def params(self) -> dict:
        return {
            "fast": self.fast, "slow": self.slow, "signal_len": self.signal_len,
            "rsi_max_entry": self.rsi_max_entry,
            "min_volatility": self.min_volatility,
            "vol_spike": self.vol_spike,
            "position_size_usd": self.position_size_usd,
            "exit_sma": self.exit_sma,
        }

    def _update_ema(self, price: float) -> tuple[float, float, float]:
        """Incrementally update MACD EMAs. Returns (macd_line, signal_line, histogram)."""
        alpha_fast = 2.0 / (self.fast + 1)
        alpha_slow = 2.0 / (self.slow + 1)
        alpha_signal = 2.0 / (self.signal_len + 1)

        self._bar_count += 1

        if not self._ema_initialized:
            self._fast_ema = price
            self._slow_ema = price
            self._signal_ema = 0.0
            self._ema_initialized = True
            self._macd_line = 0.0
            return (0.0, 0.0, 0.0)

        self._fast_ema = alpha_fast * price + (1 - alpha_fast) * self._fast_ema
        self._slow_ema = alpha_slow * price + (1 - alpha_slow) * self._slow_ema
        self._macd_line = self._fast_ema - self._slow_ema
        self._signal_ema = alpha_signal * self._macd_line + (1 - alpha_signal) * self._signal_ema
        histogram = self._macd_line - self._signal_ema

        return (self._macd_line, self._signal_ema, histogram)

    def _on_bar(self, bar: Bar, portfolio: PortfolioView) -> Iterable[Order]:
        macd_val, signal_val, histogram = self._update_ema(bar.close)

        # Need enough bars for slow EMA to stabilize
        if self._bar_count < self.slow + 5:
            self._prev_histogram = histogram
            return []

        rsi_val = self.rsi(self.rsi_period)
        vol_ratio = self.volume_ratio(20)
        sma_short = self.sma(self.exit_sma)

        # Volatility gate using rolling window
        closes = self.closes
        lookback = min(self.vol_lookback, len(closes) - 1)
        if lookback < 20:
            self._prev_histogram = histogram
            return []
        returns = np.diff(closes[-lookback:]) / closes[-lookback:-1]
        returns = returns[~np.isnan(returns) & ~np.isinf(returns)]
        if len(returns) < 10:
            self._prev_histogram = histogram
            return []
        volatility = float(np.std(returns))
        if volatility < self.min_volatility:
            self._prev_histogram = histogram
            return []

        held_qty = portfolio.position(bar.token_id).qty

        # EXIT: bearish MACD crossover or price below short SMA
        if held_qty > 0:
            if histogram < 0 and self._prev_histogram >= 0:
                self._prev_histogram = histogram
                return [Order(token_id=bar.token_id, side=Side.SELL,
                              size=held_qty, reason="macd-cross-exit")]
            if sma_short > 0 and bar.close < sma_short * 0.998:
                self._prev_histogram = histogram
                return [Order(token_id=bar.token_id, side=Side.SELL,
                              size=held_qty, reason="sma-exit")]
            self._prev_histogram = histogram
            return []

        # ENTRY: bullish MACD crossover
        if histogram > 0 and self._prev_histogram <= 0:
            if rsi_val > self.rsi_max_entry:
                self._prev_histogram = histogram
                return []
            if vol_ratio < self.vol_spike:
                self._prev_histogram = histogram
                return []
            slow_sma = self.sma(self.slow)
            if slow_sma > 0 and bar.close < slow_sma:
                self._prev_histogram = histogram
                return []
            if portfolio.cash < self.position_size_usd:
                self._prev_histogram = histogram
                return []
            qty = self.position_size_usd / bar.close
            self._prev_histogram = histogram
            return [Order(token_id=bar.token_id, side=Side.BUY,
                          size=qty, reason="macd-bull-cross")]

        self._prev_histogram = histogram
        return []
