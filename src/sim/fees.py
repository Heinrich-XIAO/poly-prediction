"""Polymarket fee models — V2 (post-April 22, 2026 cutover) and V1 fallback.

V2 fees are protocol-set per market, computed at match time, paid only by takers:

    fee = C * feeRate * p * (1 - p)

where C is the trade notional in USDC units, feeRate comes from
`getClobMarketInfo().fd.rate`, and p is the execution price in (0, 1).

The (1 - p) symmetry term is the easy thing to miss if you eyeball it as a
flat percentage. At p=0.5 the fee is feeRate/4 of notional; at p=0.9 it's
feeRate * 0.09 of notional — meaningfully cheaper at the extremes.

V1 had a flat `feeRateBps` embedded in the order; we keep a stub so backtests
that span the cutover can switch models per-bar.
"""

from __future__ import annotations

import datetime as dt
from enum import Enum

from src.constants import DEFAULT_FEE_RATE, V2_CUTOVER_UTC


class Role(str, Enum):
    TAKER = "taker"
    MAKER = "maker"


def _is_taker(role: Role | str) -> bool:
    return role == Role.TAKER or role == "taker"


def v2_fee(notional_usd: float, price: float, fee_rate: float, role: Role | str) -> float:
    """V2 fee formula. Returns absolute fee in USD (pUSD).

    - notional_usd: trade size in USD (price * shares)
    - price: execution price in (0, 1)
    - fee_rate: per-market rate, e.g. 0.02 for 2%
    - role: only takers pay; makers always pay zero
    """
    if not _is_taker(role):
        return 0.0
    p = max(0.0, min(1.0, price))
    return notional_usd * fee_rate * p * (1.0 - p)


def v1_fee(notional_usd: float, fee_rate_bps: float, role: Role | str) -> float:
    """V1 flat-bps fee model. Most V1 markets ran at 0 bps in practice."""
    if not _is_taker(role):
        return 0.0
    return notional_usd * (fee_rate_bps / 10_000.0)


def fee_for_trade(
    notional_usd: float,
    price: float,
    timestamp: dt.datetime,
    *,
    role: Role | str = Role.TAKER,
    fee_rate: float = DEFAULT_FEE_RATE,
    v1_fee_bps: float = 0.0,
) -> float:
    """Pick V1 or V2 fee model based on trade timestamp vs cutover."""
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=dt.timezone.utc)
    if timestamp < V2_CUTOVER_UTC:
        return v1_fee(notional_usd, v1_fee_bps, role)
    return v2_fee(notional_usd, price, fee_rate, role)
