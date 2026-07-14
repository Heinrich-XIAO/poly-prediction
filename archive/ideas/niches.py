"""Find under-explored market categories with favourable conditions."""

from __future__ import annotations

from competition.registry import list_strategies


def find_uncrowded_niches(
    category_performance: dict[str, dict],
    min_markets: int = 3,
    min_positive_rate: float = 0.5,
) -> list[tuple[str, float, float]]:
    """Identify categories with high win-rate but few competing strategies.

    Returns list of (category, mean_return, positive_rate) sorted by
    positive_rate descending.
    """
    n_strategies = len(list_strategies())
    candidates = []
    for cat, perf in category_performance.items():
        if perf["n_markets"] < min_markets:
            continue
        if perf["positive_rate"] < min_positive_rate:
            continue
        # Fewer strategies targeting this category -> less crowded
        specialization = sum(
            1 for s in list_strategies() if cat in s.category_tags
        )
        if specialization <= max(1, n_strategies // 3):
            candidates.append((cat, perf["mean_return"], perf["positive_rate"]))

    return sorted(candidates, key=lambda x: x[2], reverse=True)
