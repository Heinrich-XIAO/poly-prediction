"""Sanity tests for the fee model. Run with: pytest tests/"""

from __future__ import annotations

import datetime as dt

import pytest

from src.constants import V2_CUTOVER_UTC
from src.sim.fees import Role, fee_for_trade, v1_fee, v2_fee


class TestV2Fee:
    def test_taker_pays_at_midpoint(self):
        # $100 notional, 2% rate, p=0.5 → 100 * 0.02 * 0.5 * 0.5 = 0.5
        assert v2_fee(100.0, 0.5, 0.02, Role.TAKER) == pytest.approx(0.5)

    def test_taker_pays_less_at_extremes(self):
        # p=0.9 → 100 * 0.02 * 0.9 * 0.1 = 0.18
        assert v2_fee(100.0, 0.9, 0.02, Role.TAKER) == pytest.approx(0.18)
        assert v2_fee(100.0, 0.1, 0.02, Role.TAKER) == pytest.approx(0.18)

    def test_maker_pays_zero(self):
        assert v2_fee(100.0, 0.5, 0.02, Role.MAKER) == 0.0

    def test_price_clamped_to_unit_interval(self):
        # Out-of-range prices clamp; fee is zero at the boundaries
        assert v2_fee(100.0, 1.5, 0.02, Role.TAKER) == 0.0
        assert v2_fee(100.0, -0.1, 0.02, Role.TAKER) == 0.0


class TestV1Fee:
    def test_flat_bps(self):
        # 50 bps on $100 → $0.50
        assert v1_fee(100.0, 50.0, Role.TAKER) == pytest.approx(0.50)

    def test_maker_zero_v1(self):
        assert v1_fee(100.0, 50.0, Role.MAKER) == 0.0


class TestCutoverDispatch:
    def test_pre_cutover_uses_v1(self):
        before = V2_CUTOVER_UTC - dt.timedelta(days=1)
        # V1 with 0 bps default → zero fee
        assert fee_for_trade(100.0, 0.5, before) == 0.0
        # With explicit 50 bps
        assert fee_for_trade(100.0, 0.5, before, v1_fee_bps=50.0) == pytest.approx(0.50)

    def test_post_cutover_uses_v2(self):
        after = V2_CUTOVER_UTC + dt.timedelta(days=1)
        assert fee_for_trade(100.0, 0.5, after, fee_rate=0.02) == pytest.approx(0.5)

    def test_naive_datetime_assumed_utc(self):
        naive = V2_CUTOVER_UTC.replace(tzinfo=None) + dt.timedelta(days=1)
        assert fee_for_trade(100.0, 0.5, naive, fee_rate=0.02) == pytest.approx(0.5)
