"""Adaptive Mean-Reversion Strategy with Multi-Factor Confirmation.

Inspired by: unrip (reversal), the way out (exit optimization), judgy (multi-factor),
parrs (spread analysis), amnic (adaptive lookback).

Key insight: Polymarket binary markets are mostly flat with occasional jumps.
Buy dips when multiple indicators confirm oversold, take quick profits.
"""

from __future__ import annotations

import re
from typing import Iterable

import numpy as np

from strategies.base import CashOutStrategy, with_cash_out
from src.strategy.base import Bar, Order, PortfolioView, Side


class AdaptiveReversion(CashOutStrategy):
    """Mean-reversion with Bollinger + RSI + Volume confirmation.

    Enters contrarian positions when price is overextended, exits quickly.
    Skips markets that are too quiet or too volatile.
    """

    def __init__(
        self,
        lookback: int = 30,
        bb_period: int = 20,
        bb_k: float = 2.0,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        vol_spike: float = 1.5,
        position_size_usd: float = 100.0,
        min_volatility: float = 0.001,
        max_volatility: float = 0.05,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.lookback = lookback
        self.bb_period = bb_period
        self.bb_k = bb_k
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.vol_spike = vol_spike
        self.position_size_usd = position_size_usd
        self.min_volatility = min_volatility
        self.max_volatility = max_volatility

    @property
    def params(self) -> dict:
        return {
            "lookback": self.lookback,
            "bb_period": self.bb_period,
            "bb_k": self.bb_k,
            "rsi_period": self.rsi_period,
            "rsi_oversold": self.rsi_oversold,
            "rsi_overbought": self.rsi_overbought,
            "vol_spike": self.vol_spike,
            "position_size_usd": self.position_size_usd,
            "min_volatility": self.min_volatility,
            "max_volatility": self.max_volatility,
        }

    def _on_bar(self, bar: Bar, portfolio: PortfolioView) -> Iterable[Order]:
        if self.n_bars < self.lookback:
            return []

        closes = self.closes
        vol_ratio = self.volume_ratio(20)
        rsi_val = self.rsi(self.rsi_period)
        bb_upper, bb_mid, bb_lower = self.bollinger_bands(self.bb_period, self.bb_k)

        # Calculate recent volatility (annualized from 5min bars)
        returns = np.diff(closes[-self.lookback:]) / closes[-self.lookback:-1]
        returns = returns[~np.isnan(returns) & ~np.isinf(returns)]
        if len(returns) < 10:
            return []
        volatility = float(np.std(returns))

        # Skip markets that are too quiet or too wild
        if volatility < self.min_volatility or volatility > self.max_volatility:
            return []

        held_qty = portfolio.position(bar.token_id).qty

        # EXIT: Sell when RSI is overbought or price hits upper band
        if held_qty > 0:
            if rsi_val > self.rsi_overbought or bar.close >= bb_upper:
                return [Order(
                    token_id=bar.token_id, side=Side.SELL,
                    size=held_qty, reason="reversion-exit",
                )]
            # Also exit if price reverts to mean
            if bar.close >= bb_mid:
                return [Order(
                    token_id=bar.token_id, side=Side.SELL,
                    size=held_qty, reason="mean-revert-exit",
                )]
            return []

        # ENTRY: Buy when oversold with volume confirmation
        if bar.close <= bb_lower and rsi_val < self.rsi_oversold and vol_ratio >= self.vol_spike:
            if portfolio.cash < self.position_size_usd:
                return []
            qty = self.position_size_usd / bar.close
            return [Order(
                token_id=bar.token_id, side=Side.BUY,
                size=qty, reason="reversion-entry",
            )]

        # Secondary entry: buy on sharp dip even without full BB break
        price_change_5 = self.price_change(5)
        if (price_change_5 < -0.02 and rsi_val < 35
                and vol_ratio >= self.vol_spike * 0.8):
            if portfolio.cash < self.position_size_usd:
                return []
            qty = self.position_size_usd / bar.close
            return [Order(
                token_id=bar.token_id, side=Side.BUY,
                size=qty, reason="dip-buy",
            )]

        return []
