"""Portfolio accounting for the backtest engine.

Tracks pUSD cash, per-token positions, realized + unrealized PnL, and fees
paid. All amounts are USD-denominated (no on-chain unit scaling here — that's
a concern for the real bot, not the simulator).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass
class Position:
    token_id: str
    qty: float = 0.0           # shares held (>=0; we don't model shorting in v0.1)
    avg_entry: float = 0.0     # cost-basis per share
    realized_pnl: float = 0.0  # PnL from closed portions of this position

    def market_value(self, mark: float) -> float:
        return self.qty * mark

    def unrealized_pnl(self, mark: float) -> float:
        return (mark - self.avg_entry) * self.qty


@dataclass
class Portfolio:
    """Single-currency (pUSD) portfolio.

    Polymarket's binary outcomes are non-negative shares — buying YES at $0.40
    and selling at $0.60 is a +$0.20/share gain. We don't model shorting in
    v0.1; sell orders without a positive position are rejected by the engine.
    """

    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    fees_paid: float = 0.0

    # ----- queries -----

    def position(self, token_id: str) -> Position:
        return self.positions.get(token_id, Position(token_id=token_id))

    def has_position(self, token_id: str) -> bool:
        p = self.positions.get(token_id)
        return p is not None and p.qty > 0

    def equity(self, marks: dict[str, float]) -> float:
        """Cash + sum of position market values at the given marks."""
        return self.cash + sum(p.qty * marks.get(p.token_id, 0.0) for p in self.positions.values())

    def total_realized_pnl(self) -> float:
        return sum(p.realized_pnl for p in self.positions.values())

    def total_unrealized_pnl(self, marks: dict[str, float]) -> float:
        return sum(p.unrealized_pnl(marks.get(p.token_id, 0.0)) for p in self.positions.values())

    # ----- mutations (engine-only; strategies don't call these directly) -----

    def buy(self, token_id: str, qty: float, price: float, fee: float) -> None:
        """Add to a long position; fee deducted from cash separately."""
        if qty <= 0 or price <= 0:
            return
        cost = qty * price
        if cost + fee > self.cash + 1e-9:
            raise InsufficientCashError(
                f"need {cost + fee:.6f} pUSD, have {self.cash:.6f}"
            )
        self.cash -= cost + fee
        self.fees_paid += fee
        pos = self.positions.setdefault(token_id, Position(token_id=token_id))
        new_qty = pos.qty + qty
        pos.avg_entry = (
            (pos.avg_entry * pos.qty + price * qty) / new_qty if new_qty > 0 else 0.0
        )
        pos.qty = new_qty

    def sell(self, token_id: str, qty: float, price: float, fee: float) -> None:
        """Reduce / close a long position. Realizes PnL on the closed portion."""
        pos = self.positions.get(token_id)
        if pos is None or pos.qty <= 0:
            raise NoPositionError(f"no position to sell for token {token_id}")
        qty = min(qty, pos.qty)
        proceeds = qty * price
        self.cash += proceeds - fee
        self.fees_paid += fee
        pos.realized_pnl += (price - pos.avg_entry) * qty
        pos.qty -= qty
        if pos.qty <= 1e-12:
            pos.qty = 0.0  # avoid floating-point dust

    def settle_at_resolution(self, token_id: str, payout_per_share: float) -> None:
        """Resolution forces a mark-to-payout settlement.

        For Polymarket binary markets, the winning outcome resolves to $1.00
        per share, the losing outcome to $0.00. Engines call this when a
        market resolves during the backtest window.
        """
        pos = self.positions.get(token_id)
        if pos is None or pos.qty <= 0:
            return
        proceeds = pos.qty * payout_per_share
        self.cash += proceeds
        pos.realized_pnl += (payout_per_share - pos.avg_entry) * pos.qty
        pos.qty = 0.0


class InsufficientCashError(Exception):
    pass


class NoPositionError(Exception):
    pass
