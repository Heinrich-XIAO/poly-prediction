"""Performance statistics computed from an equity curve + trade log.

All metrics are computed in pUSD-denominated terms. Annualization assumes the
equity curve was sampled at the bar frequency, with `bars_per_year` derived
from the index's median spacing.

Numbers are reported as plain Python floats (not numpy scalars) so they
serialize cleanly to JSON for the run record.
"""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd


def total_return(equity: pd.Series) -> float:
    if len(equity) < 2:
        return 0.0
    start, end = float(equity.iloc[0]), float(equity.iloc[-1])
    if start <= 0:
        return 0.0
    return end / start - 1.0


def cagr(equity: pd.Series) -> float:
    """Annualized return based on actual elapsed time of the equity curve."""
    if len(equity) < 2:
        return 0.0
    start, end = float(equity.iloc[0]), float(equity.iloc[-1])
    if start <= 0 or end <= 0:
        return 0.0
    duration = (equity.index[-1] - equity.index[0]).total_seconds()
    years = duration / (365.25 * 24 * 3600)
    if years <= 0:
        return 0.0
    return (end / start) ** (1.0 / years) - 1.0


def max_drawdown(equity: pd.Series) -> float:
    """Largest peak-to-trough decline as a fraction of peak. Returns negative number."""
    if equity.empty:
        return 0.0
    running_peak = equity.cummax()
    drawdown = (equity - running_peak) / running_peak.replace(0, np.nan)
    mdd = drawdown.min()
    return float(mdd) if pd.notna(mdd) else 0.0


def sharpe(equity: pd.Series, *, risk_free_rate: float = 0.0) -> float:
    """Annualized Sharpe ratio computed on bar-frequency log returns."""
    if len(equity) < 3:
        return 0.0
    returns = np.log(equity / equity.shift(1)).dropna()
    if returns.std() == 0:
        return 0.0
    bars_per_year = _bars_per_year(equity.index)
    excess = returns.mean() - (risk_free_rate / bars_per_year)
    return float(excess / returns.std() * math.sqrt(bars_per_year))


def sortino(equity: pd.Series, *, risk_free_rate: float = 0.0) -> float:
    """Like Sharpe but penalizes only downside deviation."""
    if len(equity) < 3:
        return 0.0
    returns = np.log(equity / equity.shift(1)).dropna()
    downside = returns[returns < 0]
    if len(downside) == 0 or downside.std() == 0:
        return 0.0
    bars_per_year = _bars_per_year(equity.index)
    excess = returns.mean() - (risk_free_rate / bars_per_year)
    return float(excess / downside.std() * math.sqrt(bars_per_year))


def calmar(equity: pd.Series) -> float:
    mdd = max_drawdown(equity)
    if mdd == 0:
        return 0.0
    return float(cagr(equity) / abs(mdd))


def hit_rate(trades: Iterable) -> float:
    """Fraction of CLOSED positions that ended profitably.

    Operates on FilledTrade objects from engine.run().trades. A "trade pair"
    is a BUY followed by a SELL on the same token; we use FIFO matching and
    treat unrealized positions as ignored (not a loss).
    """
    pairs = _pair_trades(trades)
    if not pairs:
        return 0.0
    wins = sum(1 for buy, sell in pairs if (sell.price - buy.price) * buy.qty > 0)
    return wins / len(pairs)


def avg_win_loss(trades: Iterable) -> tuple[float, float]:
    """Return (avg_win, avg_loss) per closed trade pair, both in USD."""
    pairs = _pair_trades(trades)
    if not pairs:
        return 0.0, 0.0
    pnls = [(sell.price - buy.price) * min(buy.qty, sell.qty) for buy, sell in pairs]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    return float(avg_win), float(avg_loss)


def profit_factor(trades: Iterable) -> float:
    """Sum of winning PnL / abs(sum of losing PnL). Inf if no losses, 0 if no trades."""
    pairs = _pair_trades(trades)
    if not pairs:
        return 0.0
    pnls = [(sell.price - buy.price) * min(buy.qty, sell.qty) for buy, sell in pairs]
    gross_win = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    if gross_loss == 0:
        return float("inf") if gross_win > 0 else 0.0
    return float(gross_win / gross_loss)


def compute_all(equity: pd.Series, trades: Iterable, fees_paid: float) -> dict:
    """Bundle every metric into a single dict for the run record."""
    avg_w, avg_l = avg_win_loss(trades)
    mdd = max_drawdown(equity)
    return {
        "total_return": total_return(equity),
        "cagr": cagr(equity),
        "max_drawdown": mdd,
        "sharpe": sharpe(equity),
        "sortino": sortino(equity),
        "calmar": calmar(equity),
        "hit_rate": hit_rate(trades),
        "avg_win": avg_w,
        "avg_loss": avg_l,
        "profit_factor": profit_factor(trades),
        "n_trades": sum(1 for _ in trades),
        "fees_paid": float(fees_paid),
    }


# ---------- helpers ----------


def _bars_per_year(index: pd.DatetimeIndex) -> float:
    if len(index) < 2:
        return 252.0  # fallback to daily assumption
    spacing = (index[1:] - index[:-1]).to_series().median().total_seconds()
    if spacing <= 0:
        return 252.0
    return (365.25 * 24 * 3600) / spacing


def _pair_trades(trades: Iterable) -> list[tuple]:
    """FIFO-pair BUYs with SELLs for the same token. Open positions ignored."""
    open_buys: dict[str, list] = {}
    pairs: list[tuple] = []
    for t in trades:
        key = t.token_id
        if t.side == "BUY":
            open_buys.setdefault(key, []).append(t)
        elif t.side == "SELL":
            queue = open_buys.get(key, [])
            remaining = t.qty
            while remaining > 0 and queue:
                buy = queue[0]
                fill = min(buy.qty, remaining)
                pairs.append((buy, t))
                remaining -= fill
                buy_qty_left = buy.qty - fill
                if buy_qty_left <= 1e-12:
                    queue.pop(0)
                else:
                    # Mutate in-place to track partial fills; FilledTrade is a
                    # dataclass so this is fine.
                    object.__setattr__(buy, "qty", buy_qty_left)
    return pairs
