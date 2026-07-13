"""Detect price-vs-resolution discrepancies — "rumor pump & dump" patterns.

The prompt notes that rumours drive price but truth drives resolution.
This module flags markets where price moved opposite to eventual outcome.
"""

from __future__ import annotations

from src.data.store import Store


def price_resolution_discrepancy(store: Store, condition_id: str, resolved_outcome_index: int) -> dict | None:
    """Analyze whether price direction contradicted the final resolution.

    Returns a dict with summary stats, or None if insufficient data.
    """
    market = store.get_market(condition_id)
    if not market or not market.token_ids:
        return None
    token_id = market.token_ids[resolved_outcome_index]

    trades_df = store.trades_dataframe(token_id)
    if trades_df.empty:
        return None

    first_price = float(trades_df["price"].iloc[0])
    last_price = float(trades_df["price"].iloc[-1])
    mid_price = float(trades_df["price"].iloc[len(trades_df) // 2])
    low_price = float(trades_df["price"].min())
    high_price = float(trades_df["price"].max())

    # A discrepancy: price went down for the winning outcome (market doubted the truth)
    resolved_value = 1.0 if resolved_outcome_index == 0 else 0.0
    final_direction = last_price - first_price
    resolved_gap = abs(resolved_value - last_price)

    return {
        "condition_id": condition_id,
        "question": market.question[:80],
        "first_price": first_price,
        "mid_price": mid_price,
        "last_price": last_price,
        "low_price": low_price,
        "high_price": high_price,
        "price_direction": "up" if final_direction > 0 else "down",
        "resolution_gap": resolved_gap,
        "rumor_flag": final_direction < 0 and resolved_gap > 0.3,
    }
