"""Event-driven backtest engine.

For each bar in chronological order the engine:

1. Marks the portfolio to the bar's close price.
2. Calls `strategy.on_bar(bar, portfolio_view)`. Strategies see a read-only
   view — they can't mutate the portfolio directly, only return Order objects.
3. Validates each order (size, cash, no shorting in v0.1, max participation).
4. Executes valid orders against the *next* bar's price (no lookahead) using
   the configured slippage model.
5. Applies V1/V2 fees based on the trade timestamp (cutover-aware).

The result is a Run object with the full equity curve, trade log, and
metrics, suitable for `analytics.report` to format.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import asdict, dataclass, field
from typing import Iterable

import pandas as pd

from src.constants import (
    DEFAULT_FEE_RATE,
    DEFAULT_INITIAL_CASH,
    DEFAULT_LINEAR_IMPACT_BPS,
    DEFAULT_MAX_PARTICIPATION,
    DEFAULT_SLIPPAGE_MODEL,
)
from src.sim.fees import Role, fee_for_trade
from src.sim.portfolio import InsufficientCashError, NoPositionError, Portfolio
from src.strategy.base import Bar, Order, Side, Strategy

log = logging.getLogger(__name__)


# ---------- Data classes ----------


@dataclass
class FilledTrade:
    timestamp: dt.datetime
    token_id: str
    side: str
    qty: float
    price: float          # executed price (after slippage)
    notional: float
    fee: float
    role: str
    reason: str = ""      # optional strategy-supplied tag


@dataclass
class Run:
    run_id: str
    strategy_name: str
    params: dict
    token_id: str
    initial_cash: float
    bars: pd.DataFrame
    equity_curve: pd.Series
    trades: list[FilledTrade]
    fees_paid: float
    final_equity: float

    def summary(self) -> dict:
        return {
            "run_id": self.run_id,
            "strategy": self.strategy_name,
            "initial_cash": self.initial_cash,
            "final_equity": self.final_equity,
            "return_pct": (self.final_equity / self.initial_cash - 1.0) * 100.0 if self.initial_cash else 0.0,
            "n_trades": len(self.trades),
            "fees_paid": self.fees_paid,
        }


# ---------- Engine ----------


class Engine:
    def __init__(
        self,
        strategy: Strategy,
        bars: pd.DataFrame,
        token_id: str,
        *,
        initial_cash: float = DEFAULT_INITIAL_CASH,
        fee_rate: float = DEFAULT_FEE_RATE,
        v1_fee_bps: float = 0.0,
        slippage: str = DEFAULT_SLIPPAGE_MODEL,
        impact_bps: float = DEFAULT_LINEAR_IMPACT_BPS,
        max_participation: float = DEFAULT_MAX_PARTICIPATION,
    ) -> None:
        if bars.empty:
            raise ValueError("cannot run backtest on empty bars")
        if "close" not in bars.columns:
            raise ValueError("bars DataFrame must contain at least 'close' column")

        self.strategy = strategy
        self.bars = bars.sort_index()
        self.token_id = token_id
        self.fee_rate = fee_rate
        self.v1_fee_bps = v1_fee_bps
        self.slippage = slippage
        self.impact_bps = impact_bps
        self.max_participation = max_participation

        self.portfolio = Portfolio(cash=initial_cash)
        self._initial_cash = initial_cash
        self._trades: list[FilledTrade] = []
        self._equity_history: list[tuple[dt.datetime, float]] = []
        self._pending_orders: list[Order] = []

    def run(self) -> Run:
        bars_iter = list(self.bars.itertuples())
        for i, row in enumerate(bars_iter):
            ts: dt.datetime = row.Index.to_pydatetime()
            close = float(row.close)

            # 1. Execute orders pending from the previous bar against this bar.
            if self._pending_orders:
                self._execute_pending(self._pending_orders, row, ts)
                self._pending_orders = []

            # 2. Mark portfolio to current close, snapshot equity.
            equity = self.portfolio.equity({self.token_id: close})
            self._equity_history.append((ts, equity))

            # 3. Strategy decides on next-bar orders.
            bar = Bar(
                timestamp=ts,
                token_id=self.token_id,
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=close,
                volume=float(getattr(row, "volume", 0.0)),
                vwap=float(getattr(row, "vwap", close)),
                trades=int(getattr(row, "trades", 0)),
            )
            try:
                new_orders = list(self.strategy.on_bar(bar, _PortfolioView(self.portfolio))) or []
            except Exception:  # noqa: BLE001 — strategies are user code
                log.exception("strategy.on_bar raised at %s", ts)
                new_orders = []
            self._pending_orders = [
                o for o in new_orders if self._validate_order(o, close)
            ]

        # Final equity at the last close (no more orders execute).
        last_close = float(self.bars["close"].iloc[-1])
        final_equity = self.portfolio.equity({self.token_id: last_close})

        equity_curve = pd.Series(
            data=[v for _, v in self._equity_history],
            index=pd.to_datetime([t for t, _ in self._equity_history], utc=True),
            name="equity",
        )

        return Run(
            run_id=uuid.uuid4().hex[:12],
            strategy_name=self.strategy.__class__.__name__,
            params=getattr(self.strategy, "params", {}),
            token_id=self.token_id,
            initial_cash=self._initial_cash,
            bars=self.bars,
            equity_curve=equity_curve,
            trades=self._trades,
            fees_paid=self.portfolio.fees_paid,
            final_equity=final_equity,
        )

    # ---------- internals ----------

    def _validate_order(self, order: Order, ref_price: float) -> bool:
        if order.size <= 0:
            log.debug("rejecting non-positive size: %s", order)
            return False
        if order.token_id != self.token_id:
            log.debug("rejecting order on foreign token: %s", order)
            return False
        if order.side == Side.BUY:
            est_cost = order.size * ref_price
            if est_cost > self.portfolio.cash * 1.05:  # 5% leniency for next-bar move
                log.debug("rejecting BUY (cash %.4f, est_cost %.4f)", self.portfolio.cash, est_cost)
                return False
        if order.side == Side.SELL:
            held = self.portfolio.position(order.token_id).qty
            if held <= 0:
                log.debug("rejecting SELL (no position)")
                return False
        return True

    def _execute_pending(self, orders: Iterable[Order], row, ts: dt.datetime) -> None:
        bar_volume = float(getattr(row, "volume", 0.0))
        bar_close = float(row.close)
        bar_vwap = float(getattr(row, "vwap", bar_close))

        for order in orders:
            qty = self._cap_to_participation(order.size, bar_volume)
            if qty <= 0:
                continue

            exec_price = self._slippage_price(order, bar_close, bar_vwap, qty, bar_volume)
            notional = qty * exec_price
            role = order.role
            fee = fee_for_trade(
                notional_usd=notional,
                price=exec_price,
                timestamp=ts,
                role=role,
                fee_rate=self.fee_rate,
                v1_fee_bps=self.v1_fee_bps,
            )

            try:
                if order.side == Side.BUY:
                    self.portfolio.buy(order.token_id, qty, exec_price, fee)
                else:
                    self.portfolio.sell(order.token_id, qty, exec_price, fee)
            except (InsufficientCashError, NoPositionError) as e:
                log.debug("order rejected at fill: %s", e)
                continue

            self._trades.append(
                FilledTrade(
                    timestamp=ts,
                    token_id=order.token_id,
                    side=order.side.value,
                    qty=qty,
                    price=exec_price,
                    notional=notional,
                    fee=fee,
                    role=str(role),
                    reason=order.reason,
                )
            )

    def _cap_to_participation(self, size: float, bar_volume: float) -> float:
        """Limit fill to a fraction of bar volume — avoids unrealistic prints."""
        if bar_volume <= 0:
            return 0.0  # no liquidity this bar, skip
        cap = bar_volume * self.max_participation
        return min(size, cap)

    def _slippage_price(
        self, order: Order, bar_close: float, bar_vwap: float, qty: float, bar_volume: float
    ) -> float:
        if self.slippage == "bar_close":
            return bar_close
        if self.slippage == "bar_vwap":
            return bar_vwap
        if self.slippage == "linear_impact":
            participation = qty / bar_volume if bar_volume else 0.0
            impact = (self.impact_bps / 10_000.0) * participation * 5.0  # 5x participation factor
            sign = 1.0 if order.side == Side.BUY else -1.0
            return bar_close * (1.0 + sign * impact)
        # Unknown model — fall back to close.
        return bar_close


class _PortfolioView:
    """Read-only proxy passed to strategies.

    Strategies should never mutate the portfolio. This wrapper exposes only
    query methods. If a strategy author tries to call buy/sell on this, they
    get an AttributeError, which is the right failure mode.
    """

    __slots__ = ("_p",)

    def __init__(self, p: Portfolio):
        self._p = p

    @property
    def cash(self) -> float:
        return self._p.cash

    @property
    def fees_paid(self) -> float:
        return self._p.fees_paid

    def position(self, token_id: str):
        return self._p.position(token_id)

    def has_position(self, token_id: str) -> bool:
        return self._p.has_position(token_id)

    def equity(self, marks: dict[str, float]) -> float:
        return self._p.equity(marks)
