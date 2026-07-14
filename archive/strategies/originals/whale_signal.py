"""Whale Signal v6: MACD Entry + Dual Exit (Trailing Stop + SMA).

Same proven entry logic as macd_trend but with a dual exit:
1. Trailing stop (10%) to capture big trends
2. SMA(10) exit to cut losses early

The insight from Agent 0: dual exit mechanisms outperform single exits.
The 10% trailing stop holds through minor pullbacks, while the SMA exit
catches early reversals before the trailing stop triggers.

Entry: identical to macd_trend (MACD crossover + trend + RSI + volume + volatility)
Exit: trailing stop (10%) OR SMA(10) break OR time-based (30 bars)
"""

from __future__ import annotations

from typing import Iterable

import numpy as np

from strategies.base import CashOutStrategy
from src.strategy.base import Bar, Order, PortfolioView, Side


class WhaleSignal(CashOutStrategy):
    """MACD entry with trailing stop exit."""

    def __init__(
        self,
        fast: int = 12,
        slow: int = 26,
        signal_len: int = 9,
        rsi_period: int = 14,
        rsi_max_entry: float = 80.0,
        vol_lookback: int = 100,
        min_volatility: float = 0.0003,
        vol_spike: float = 0.7,
        position_size_usd: float = 150.0,
        trailing_pct: float = 0.10,
        max_hold_bars: int = 30,
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
        self.trailing_pct = trailing_pct
        self.max_hold_bars = max_hold_bars
        self.exit_sma = exit_sma

        self._fast_ema: float = 0.0
        self._slow_ema: float = 0.0
        self._signal_ema: float = 0.0
        self._macd_line: float = 0.0
        self._prev_histogram: float = 0.0
        self._ema_initialized: bool = False
        self._bar_count: int = 0
        self._peak_price: float = 0.0
        self._whale_entry_bar: int = 0

    @property
    def params(self) -> dict:
        return {
            "fast": self.fast, "slow": self.slow, "signal_len": self.signal_len,
            "rsi_max_entry": self.rsi_max_entry,
            "min_volatility": self.min_volatility,
            "vol_spike": self.vol_spike,
            "position_size_usd": self.position_size_usd,
            "trailing_pct": self.trailing_pct,
            "max_hold_bars": self.max_hold_bars,
            "exit_sma": self.exit_sma,
        }

    def _update_ema(self, price: float) -> tuple[float, float, float]:
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

        if self._bar_count < self.slow + 5:
            self._prev_histogram = histogram
            return []

        rsi_val = self.rsi(self.rsi_period)
        vol_ratio = self.volume_ratio(20)
        sma_short = self.sma(self.exit_sma)

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

        pos = portfolio.position(bar.token_id)
        held_qty = pos.qty if pos else 0

        if held_qty > 0:
            if bar.close > self._peak_price:
                self._peak_price = bar.close

            # Trailing stop exit
            drawdown = (self._peak_price - bar.close) / self._peak_price if self._peak_price > 0 else 0
            if drawdown >= self.trailing_pct:
                self._peak_price = 0.0
                self._whale_entry_bar = 0
                return [Order(token_id=bar.token_id, side=Side.SELL,
                              size=held_qty, reason="whale-trailing-stop")]

            # SMA exit (catch early reversals)
            if sma_short > 0 and bar.close < sma_short * 0.998:
                self._peak_price = 0.0
                self._whale_entry_bar = 0
                return [Order(token_id=bar.token_id, side=Side.SELL,
                              size=held_qty, reason="whale-sma-exit")]

            # Time-based exit
            bars_held = self.n_bars - self._whale_entry_bar
            if bars_held >= self.max_hold_bars:
                self._peak_price = 0.0
                self._whale_entry_bar = 0
                return [Order(token_id=bar.token_id, side=Side.SELL,
                              size=held_qty, reason="whale-time-exit")]

            self._prev_histogram = histogram
            return []

        # ENTRY: positive MACD histogram (not just crossover) with filters
        if histogram > 0:
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
            self._peak_price = bar.close
            self._whale_entry_bar = self.n_bars
            self._prev_histogram = histogram
            return [Order(token_id=bar.token_id, side=Side.BUY,
                          size=qty, reason="whale-macd-entry")]

        self._prev_histogram = histogram
        return []
