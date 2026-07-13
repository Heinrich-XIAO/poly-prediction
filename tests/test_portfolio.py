"""Portfolio accounting sanity tests."""

from __future__ import annotations

import pytest

from src.sim.portfolio import InsufficientCashError, NoPositionError, Portfolio


def test_buy_then_sell_realizes_pnl():
    p = Portfolio(cash=1000.0)
    p.buy("tok1", qty=100.0, price=0.40, fee=0.0)
    assert p.cash == pytest.approx(960.0)
    assert p.position("tok1").qty == 100.0
    assert p.position("tok1").avg_entry == pytest.approx(0.40)

    p.sell("tok1", qty=100.0, price=0.60, fee=0.0)
    assert p.cash == pytest.approx(1020.0)
    assert p.position("tok1").qty == 0.0
    assert p.position("tok1").realized_pnl == pytest.approx(20.0)


def test_average_entry_correct_on_multiple_buys():
    p = Portfolio(cash=1000.0)
    p.buy("tok1", qty=50.0, price=0.20, fee=0.0)
    p.buy("tok1", qty=50.0, price=0.40, fee=0.0)
    # Total: 100 shares at avg 0.30
    assert p.position("tok1").qty == 100.0
    assert p.position("tok1").avg_entry == pytest.approx(0.30)


def test_insufficient_cash_raises():
    p = Portfolio(cash=10.0)
    with pytest.raises(InsufficientCashError):
        p.buy("tok1", qty=100.0, price=0.40, fee=0.0)


def test_sell_without_position_raises():
    p = Portfolio(cash=100.0)
    with pytest.raises(NoPositionError):
        p.sell("tok1", qty=10.0, price=0.50, fee=0.0)


def test_resolution_settles_to_payout():
    p = Portfolio(cash=1000.0)
    p.buy("yes", qty=200.0, price=0.30, fee=0.0)  # spent 60
    p.settle_at_resolution("yes", payout_per_share=1.0)  # YES wins, payout $1
    assert p.position("yes").qty == 0.0
    # Realized PnL = (1.0 - 0.30) * 200 = 140
    assert p.position("yes").realized_pnl == pytest.approx(140.0)
    assert p.cash == pytest.approx(1000.0 - 60.0 + 200.0)  # 1140


def test_equity_includes_unrealized():
    p = Portfolio(cash=500.0)
    p.buy("tok1", qty=100.0, price=0.40, fee=0.0)
    eq = p.equity({"tok1": 0.55})
    # cash 460 + 100 * 0.55 = 515
    assert eq == pytest.approx(515.0)


def test_fees_tracked():
    p = Portfolio(cash=1000.0)
    p.buy("tok1", qty=100.0, price=0.40, fee=0.50)
    p.sell("tok1", qty=100.0, price=0.60, fee=0.30)
    assert p.fees_paid == pytest.approx(0.80)
