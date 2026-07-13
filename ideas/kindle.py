"""Fetch random words for strategy inspiration, as described in the prompt."""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

_WORDS_URL = "https://random-words-api.kushcreates.com/api"

_CONCEPT_MAP: dict[str, str] = {
    "cloud": "weather category markets — temperature, rainfall, natural events",
    "condensation": "regime-change detection — phase transitions in price behavior",
    "rust": "decay / mean-reversion — assets that degrade or revert over time",
    "storm": "volatility breakout — sudden price dislocations",
    "tide": "cyclic / seasonal patterns — reoccurring market rhythms",
    "shadow": "lagging indicator — price follows something else with delay",
    "echo": "momentum continuation — past patterns repeat",
    "bridge": "arbitrage / cross-market — connect related markets",
    "mirror": "pair trading — mirrored asset relationships",
    "seed": "early adoption — buy nascent markets before volume",
    "harvest": "take-profit / cash-out at seasonality peaks",
    "ice": "market freeze — low-liquidity regimes",
    "fire": "high-volatility regimes / hype cycles",
    "wind": "trend-following — directional moves with momentum",
    "stone": "static / range-bound — mean reversion in tight ranges",
    "wave": "oscillator-based — stochastic / RSI style entries",
    "crystal": "forward-looking — resolution date based positioning",
    "anchor": "reference price anchoring — relative value trades",
    "compass": "directional bias — news / sentiment driven",
    "forge": "synthetic asset construction — combining tokens",
}


def fetch_random_words(count: int = 5) -> list[str]:
    """Fetch *count* random words from the inspiration API."""
    try:
        r = httpx.get(f"{_WORDS_URL}?words={count}", timeout=10.0)
        r.raise_for_status()
        data: Any = r.json()
        if isinstance(data, list):
            words = []
            for item in data:
                if isinstance(item, dict):
                    words.append(str(item.get("word", str(item))))
                else:
                    words.append(str(item))
            return words
        if isinstance(data, dict):
            vals = list(data.values())
            if vals and isinstance(vals[0], dict):
                return [str(v.get("word", str(v))) for v in vals]
            return [str(v) for v in vals]
        return []
    except Exception:
        log.warning("failed to fetch random words, using fallback")
        return _fallback_words(count)


def map_words_to_concepts(words: list[str]) -> dict[str, str]:
    """Map each word to a strategy concept/hint."""
    return {w: _CONCEPT_MAP.get(w.lower(), "abstract concept — look for unexpected connections") for w in words}


def generate_strategy_hint(words: list[str]) -> str:
    """Combine words into a single strategy prompt."""
    concepts = map_words_to_concepts(words)
    parts = [f"'{w}' ({concepts[w]})" for w in words]
    return "Strategy seeds: " + "; ".join(parts)


def _fallback_words(n: int) -> list[str]:
    pool = ["horizon", "current", "drift", "pulse", "fold", "veil", "spark", "flow"]
    return pool[:n]
