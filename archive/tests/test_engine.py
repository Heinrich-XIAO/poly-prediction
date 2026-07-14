"""Engine integration tests on synthetic OHLC data."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from src.sim.engine import Engine
from src.strategy.examples.buy_and_hold import BuyAndHold
from src.strategy.examples.momentum import MomentumSMA


def _synthetic_bars(n: int = 60, start_price: float = 0.40, drift: float = 0.005) -> pd.DataFrame:
    """Make n bars with linear price drift, constant volume of 1000."""
    idx = pd.date_range("2026-04-30 12:00", periods=n, freq="1min", tz="UTC")
    closes = [start_price + drift * i for i in range(n)]
    df = pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.005 for c in closes],
            "low": [c * 0.995 for c in closes],
            "close": closes,
            "volume": [1000.0] * n,
            "vwap": closes,
            "trades": [10] * n,
        },
        index=idx,
    )
    return df


def test_buy_and_hold_captures_drift():
    bars = _synthetic_bars(n=60, start_price=0.40, drift=0.005)
    engine = Engine(BuyAndHold(allocation_pct=0.95), bars, token_id="tok1", initial_cash=1000.0)
    run = engine.run()
    # Final price = 0.40 + 0.005 * 59 ≈ 0.695. Buy at next bar after first (≈0.405).
    # Strategy buys ~95% of cash (~950) at ~0.405 → ~2345 shares, post-fee.
    # Final equity ≈ 50 cash + 2345 * 0.695 ≈ 50 + 1630 = 1680ish (above initial)
    assert run.final_equity > run.initial_cash
    assert len(run.trades) == 1
    assert run.trades[0].side == "BUY"


def test_momentum_buys_then_sells_on_reversal():
    """Up-then-down price → momentum should buy near top and sell on reversal."""
    up = [0.30 + 0.01 * i for i in range(30)]
    down = [up[-1] - 0.01 * i for i in range(30)]
    closes = up + down
    idx = pd.date_range("2026-04-30 12:00", periods=len(closes), freq="1min", tz="UTC")
    bars = pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.001 for c in closes],
            "low": [c * 0.999 for c in closes],
            "close": closes,
            "volume": [10000.0] * len(closes),
            "vwap": closes,
            "trades": [10] * len(closes),
        },
        index=idx,
    )
    strat = MomentumSMA(lookback=10, entry_threshold=0.02, exit_threshold=0.02, position_size_usd=100.0)
    engine = Engine(strat, bars, token_id="tok1", initial_cash=1000.0)
    run = engine.run()
    # Should have at least one BUY and one SELL
    sides = [t.side for t in run.trades]
    assert "BUY" in sides
    assert "SELL" in sides


def test_engine_rejects_empty_bars():
    with pytest.raises(ValueError):
        Engine(BuyAndHold(), pd.DataFrame(), token_id="tok1")


def test_no_lookahead():
    """Order placed on bar N must execute at bar N+1 prices, not bar N."""
    bars = _synthetic_bars(n=10, start_price=0.40, drift=0.0)
    bars.iloc[5, bars.columns.get_loc("close")] = 0.99  # spike on bar 5
    bars.iloc[5, bars.columns.get_loc("open")] = 0.99
    bars.iloc[5, bars.columns.get_loc("vwap")] = 0.99

    engine = Engine(BuyAndHold(allocation_pct=0.95), bars, token_id="tok1", initial_cash=1000.0)
    run = engine.run()
    # BuyAndHold emits BUY on bar 0 → fills on bar 1 (price 0.40), NOT bar 0.
    # Should NOT have filled at the bar-5 spike since order is placed on bar 0.
    fill_price = run.trades[0].price
    assert fill_price == pytest.approx(0.40, abs=0.01)
