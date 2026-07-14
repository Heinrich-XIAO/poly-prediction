from __future__ import annotations

from typing import Iterable

import numpy as np

from src.strategy.base import Bar, Order, PortfolioView, Side, Strategy


def with_cash_out(
    strategy: Strategy,
    *,
    take_profit_pct: float | None = None,
    stop_loss_pct: float | None = None,
    max_hold_bars: int | None = None,
) -> Strategy:
    """Wrap any Strategy with automatic cash-out logic."""
    return _CashOutWrapper(
        strategy,
        take_profit_pct=take_profit_pct,
        stop_loss_pct=stop_loss_pct,
        max_hold_bars=max_hold_bars,
    )


class CashOutStrategy(Strategy):
    """Base class for strategies with built-in cash-out hooks and indicator helpers.

    Subclasses implement ``_on_bar(self, bar, portfolio)``.
    The base class accumulates bar data and provides numpy-backed helpers
    (SMA, RSI, Bollinger Bands, ATR, MACD, Stochastic, etc.) that are
    PIT-safe — they only see data up to the current bar, never future bars.

    Parameters
    ----------
    question : str
        The market question text. Available via self.question.
    tag : str
        The market category tag. Available via self.tag.
    """

    def __init__(self, question: str = "", tag: str = "", **kwargs):
        self.question = question
        self.tag = tag
        self._closes: list[float] = []
        self._opens: list[float] = []
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._volumes: list[float] = []
        self._vwaps: list[float] = []
        self._entry_bar: dict[str, int] = {}
        self._entry_price: dict[str, float] = {}
        self._bar_counter = 0

    # ─── Bar accumulation ──────────────────────────────────────────────

    def on_bar(self, bar: Bar, portfolio: PortfolioView) -> Iterable[Order]:
        self._closes.append(bar.close)
        self._opens.append(bar.open)
        self._highs.append(bar.high)
        self._lows.append(bar.low)
        self._volumes.append(bar.volume)
        self._vwaps.append(bar.vwap)

        orders = list(self._on_bar(bar, portfolio))

        for o in orders:
            if o.side == Side.BUY:
                self._entry_bar[o.token_id] = self._bar_counter
                self._entry_price[o.token_id] = bar.close

        for token_id in list(self._entry_bar.keys()):
            pos = portfolio.position(token_id)
            if pos.qty <= 0:
                del self._entry_bar[token_id]
                del self._entry_price[token_id]
                continue
            if self._should_exit(bar, token_id, pos):
                orders.append(Order(
                    token_id=token_id, side=Side.SELL,
                    size=pos.qty, reason="cash-out",
                ))

        self._bar_counter += 1
        return orders

    def _on_bar(self, bar: Bar, portfolio: PortfolioView) -> Iterable[Order]:
        return []

    def _should_exit(self, bar: Bar, token_id: str, position) -> bool:
        return False

    # ─── Numpy array views ─────────────────────────────────────────────

    @property
    def n_bars(self) -> int:
        return len(self._closes)

    @property
    def closes(self) -> np.ndarray:
        return np.array(self._closes, dtype=float)

    @property
    def opens(self) -> np.ndarray:
        return np.array(self._opens, dtype=float)

    @property
    def highs(self) -> np.ndarray:
        return np.array(self._highs, dtype=float)

    @property
    def lows(self) -> np.ndarray:
        return np.array(self._lows, dtype=float)

    @property
    def volumes(self) -> np.ndarray:
        return np.array(self._volumes, dtype=float)

    @property
    def vwaps(self) -> np.ndarray:
        return np.array(self._vwaps, dtype=float)

    @property
    def bars_df(self) -> "pd.DataFrame":
        """All bars as a pandas DataFrame indexed by bar number."""
        import pandas as pd
        return pd.DataFrame({
            "open": self._opens,
            "high": self._highs,
            "low": self._lows,
            "close": self._closes,
            "volume": self._volumes,
            "vwap": self._vwaps,
        })

    # ─── Indicators (PIT-safe: no future data) ─────────────────────────

    def sma(self, n: int) -> float:
        """Simple moving average of last n closes."""
        if n <= 0 or len(self._closes) < n:
            return 0.0
        return float(np.mean(self._closes[-n:]))

    def ema(self, n: int) -> float:
        """Exponential moving average over all bars, period=n."""
        if n <= 0 or not self._closes:
            return 0.0
        alpha = 2.0 / (n + 1)
        result = self._closes[0]
        for v in self._closes[1:]:
            result = alpha * v + (1.0 - alpha) * result
        return result

    def rsi(self, n: int = 14) -> float:
        """Relative Strength Index (0–100). Returns 50 if insufficient data."""
        if len(self._closes) <= n:
            return 50.0
        deltas = np.diff(self._closes[-(n + 1):])
        gains = float(deltas[deltas > 0].sum())
        losses = float((-deltas[deltas < 0]).sum())
        if losses == 0:
            return 100.0
        rs = gains / losses
        return 100.0 - (100.0 / (1.0 + rs))

    def bollinger_bands(self, n: int = 20, k: float = 2.0) -> tuple[float, float, float]:
        """(upper, middle, lower) Bollinger Bands. Returns (0,0,0) if insufficient data."""
        if n <= 0 or len(self._closes) < n:
            return (0.0, 0.0, 0.0)
        recent = np.array(self._closes[-n:], dtype=float)
        mean = float(np.mean(recent))
        std = float(np.std(recent, ddof=1))
        return (mean + k * std, mean, mean - k * std)

    def volume_ratio(self, n: int = 20) -> float:
        """Current volume / average volume over last n bars. Returns 1.0 if insufficient data."""
        if n <= 0 or len(self._volumes) < n:
            return 1.0
        avg_vol = float(np.mean(self._volumes[-n:]))
        if avg_vol == 0:
            return 1.0
        return self._volumes[-1] / avg_vol

    def price_change(self, n: int = 1) -> float:
        """Close price change over n bars. Returns 0.0 if insufficient data."""
        if n <= 0 or len(self._closes) <= n:
            return 0.0
        return self._closes[-1] - self._closes[-(n + 1)]

    def rolling_max(self, n: int) -> float:
        """Highest close over last n bars."""
        if n <= 0 or not self._closes:
            return 0.0
        if len(self._closes) < n:
            return float(max(self._closes))
        return float(max(self._closes[-n:]))

    def rolling_min(self, n: int) -> float:
        """Lowest close over last n bars."""
        if n <= 0 or not self._closes:
            return 0.0
        if len(self._closes) < n:
            return float(min(self._closes))
        return float(min(self._closes[-n:]))

    def rolling_std(self, n: int) -> float:
        """Standard deviation of closes over last n bars."""
        if n <= 1 or len(self._closes) < n:
            return 0.0
        return float(np.std(self._closes[-n:], ddof=1))

    def atr(self, n: int = 14) -> float:
        """Average True Range over last n bars (EMA-smoothed)."""
        if len(self._closes) < 2:
            return 0.0
        count = min(n, len(self._closes) - 1)
        trs: list[float] = []
        for i in range(len(self._closes) - count, len(self._closes)):
            high = self._highs[i]
            low = self._lows[i]
            prev_close = self._closes[i - 1]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
        if not trs:
            return 0.0
        # EMA-smoothed ATR
        alpha = 2.0 / (count + 1)
        result = trs[0]
        for tr in trs[1:]:
            result = alpha * tr + (1.0 - alpha) * result
        return result

    def macd(self, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[float, float, float]:
        """(macd_line, signal_line, histogram). Returns (0,0,0) if insufficient data."""
        if len(self._closes) < slow:
            return (0.0, 0.0, 0.0)
        closes = np.array(self._closes, dtype=float)
        fast_ema = self._ema_array(closes, fast)
        slow_ema = self._ema_array(closes, slow)
        macd_line = fast_ema - slow_ema
        # Signal line: EMA of MACD line
        # We need enough data points for signal
        if len(macd_line) < signal:
            return (float(macd_line[-1]), 0.0, float(macd_line[-1]))
        signal_line = self._ema_array(macd_line, signal)
        macd_val = float(macd_line[-1])
        signal_val = float(signal_line[-1])
        return (macd_val, signal_val, macd_val - signal_val)

    def stochastic(self, n: int = 14, k_smooth: int = 3) -> tuple[float, float]:
        """(%K, %D) Stochastic Oscillator (0–100). Returns (50,50) if insufficient data."""
        if len(self._closes) < n:
            return (50.0, 50.0)
        k_values: list[float] = []
        for i in range(len(self._closes) - n, len(self._closes)):
            start = max(0, i - n + 1)
            window_high = max(self._highs[start: i + 1])
            window_low = min(self._lows[start: i + 1])
            denom = window_high - window_low
            if denom == 0:
                k_values.append(50.0)
            else:
                k_values.append((self._closes[i] - window_low) / denom * 100.0)
        k_val = k_values[-1]
        if len(k_values) >= k_smooth:
            d_val = float(np.mean(k_values[-k_smooth:]))
        else:
            d_val = float(np.mean(k_values))
        return (k_val, d_val)

    # ─── Internal helpers ───────────────────────────────────────────────

    @staticmethod
    def _ema_array(arr: np.ndarray, n: int) -> np.ndarray:
        """Compute EMA over an array, returning an array of same length."""
        if len(arr) == 0:
            return arr
        alpha = 2.0 / (n + 1)
        result = np.empty_like(arr, dtype=float)
        result[0] = arr[0]
        for i in range(1, len(arr)):
            result[i] = alpha * arr[i] + (1.0 - alpha) * result[i - 1]
        return result


class _CashOutWrapper(Strategy):
    def __init__(
        self,
        inner: Strategy,
        take_profit_pct: float | None = None,
        stop_loss_pct: float | None = None,
        max_hold_bars: int | None = None,
        question: str = "",
        tag: str = "",
    ):
        self._inner = inner
        self._tp = take_profit_pct
        self._sl = stop_loss_pct
        self._max_hold = max_hold_bars
        self.question = question
        self.tag = tag
        self._entry_bar: dict[str, int] = {}
        self._entry_price: dict[str, float] = {}
        self._bar_counter = 0

    def on_bar(self, bar: Bar, portfolio: PortfolioView) -> Iterable[Order]:
        orders = list(self._inner.on_bar(bar, portfolio))

        for o in orders:
            if o.side == Side.BUY:
                self._entry_bar[o.token_id] = self._bar_counter
                self._entry_price[o.token_id] = bar.close

        for token_id in list(self._entry_bar.keys()):
            pos = portfolio.position(token_id)
            if pos.qty <= 0:
                del self._entry_bar[token_id]
                del self._entry_price[token_id]
                continue

            entry_price = self._entry_price.get(token_id, bar.close)
            unrealized_pct = (bar.close - entry_price) / entry_price if entry_price else 0.0
            bars_held = self._bar_counter - self._entry_bar.get(token_id, 0)

            if self._tp is not None and unrealized_pct >= self._tp:
                orders.append(Order(token_id=token_id, side=Side.SELL, size=pos.qty, reason="take-profit"))
            elif self._sl is not None and unrealized_pct <= -abs(self._sl):
                orders.append(Order(token_id=token_id, side=Side.SELL, size=pos.qty, reason="stop-loss"))
            elif self._max_hold is not None and bars_held >= self._max_hold:
                orders.append(Order(token_id=token_id, side=Side.SELL, size=pos.qty, reason="max-hold"))

        self._bar_counter += 1
        return orders
