from __future__ import annotations

from typing import Iterable

from src.strategy.base import Bar, Order, PortfolioView, Side, Strategy


def with_cash_out(
    strategy: Strategy,
    *,
    take_profit_pct: float | None = None,
    stop_loss_pct: float | None = None,
    max_hold_bars: int | None = None,
) -> Strategy:
    """Wrap any Strategy with automatic cash-out logic.

    Parameters
    ----------
    take_profit_pct : float, optional
        Exit position if unrealized PnL / cost basis exceeds this fraction.
    stop_loss_pct : float, optional
        Exit position if unrealized PnL drops below this fraction (negative).
    max_hold_bars : int, optional
        Exit position after this many bars regardless of price.

    Returns a Strategy-compatible wrapper.
    """
    return _CashOutWrapper(
        strategy,
        take_profit_pct=take_profit_pct,
        stop_loss_pct=stop_loss_pct,
        max_hold_bars=max_hold_bars,
    )


class CashOutStrategy(Strategy):
    """Base class for strategies with built-in cash-out hooks.

    Override ``on_bar`` as usual, and optionally override ``should_exit``
    to add take-profit / stop-loss / time-based exit logic.
    """

    def __init__(self, **kwargs):
        self._entry_bar: dict[str, int] = {}
        self._entry_price: dict[str, float] = {}
        self._bar_counter = 0

    def on_bar(self, bar: Bar, portfolio: PortfolioView) -> Iterable[Order]:
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


class _CashOutWrapper(Strategy):
    def __init__(
        self,
        inner: Strategy,
        take_profit_pct: float | None = None,
        stop_loss_pct: float | None = None,
        max_hold_bars: int | None = None,
    ):
        self._inner = inner
        self._tp = take_profit_pct
        self._sl = stop_loss_pct
        self._max_hold = max_hold_bars
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
