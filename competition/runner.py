from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field

import pandas as pd

from competition.registry import StrategyRecord
from src.sim.engine import Engine, Run
from src.strategy.base import Strategy

log = logging.getLogger(__name__)


@dataclass
class ComparisonResult:
    bars: pd.DataFrame
    token_id: str
    initial_cash: float
    runs: dict[str, Run] = field(default_factory=dict)
    metrics: dict[str, dict] = field(default_factory=dict)
    rankings: list[tuple[str, float]] = field(default_factory=list)


class CompetitionRunner:
    def __init__(
        self,
        bars: pd.DataFrame,
        token_id: str,
        *,
        initial_cash: float = 1000.0,
        fee_rate: float = 0.02,
        slippage: str = "bar_vwap",
        question: str = "",
        tag: str = "",
    ):
        self.bars = bars
        self.token_id = token_id
        self.initial_cash = initial_cash
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.question = question
        self.tag = tag

    def run(self, records: list[StrategyRecord]) -> ComparisonResult:
        from src.analytics.metrics import compute_all

        result = ComparisonResult(
            bars=self.bars,
            token_id=self.token_id,
            initial_cash=self.initial_cash,
        )

        for rec in records:
            try:
                strategy: Strategy = rec.strategy_class(**rec.default_params, question=self.question, tag=self.tag)
                engine = Engine(
                    strategy,
                    self.bars,
                    token_id=self.token_id,
                    initial_cash=self.initial_cash,
                    fee_rate=self.fee_rate,
                    slippage=self.slippage,
                )
                run = engine.run()
                m = compute_all(run.equity_curve, run.trades, run.fees_paid)
                result.runs[rec.name] = run
                result.metrics[rec.name] = m
                log.info("%s: return=%.2f%% sharpe=%.3f trades=%d",
                         rec.name, m["total_return"] * 100, m["sharpe"], m["n_trades"])
            except Exception:
                log.exception("strategy %s failed", rec.name)

        result.rankings = sorted(
            [(name, result.metrics[name]["total_return"]) for name in result.runs],
            key=lambda x: x[1],
            reverse=True,
        )
        return result
