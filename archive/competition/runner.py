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
class MarketDef:
    bars: pd.DataFrame
    token_id: str
    question: str
    tag: str


@dataclass
class MarketResult:
    token_id: str
    question: str
    tag: str
    n_bars: int
    runs: dict[str, Run] = field(default_factory=dict)
    metrics: dict[str, dict] = field(default_factory=dict)


@dataclass
class ComparisonResult:
    markets: list[MarketResult] = field(default_factory=list)
    initial_cash: float = 1000.0
    aggregate_metrics: dict[str, dict] = field(default_factory=dict)
    rankings: list[tuple[str, float]] = field(default_factory=list)


def _aggregate(metrics_list: list[dict]) -> dict:
    if not metrics_list:
        return {}
    n = len(metrics_list)
    total_return = sum(m["total_return"] for m in metrics_list)
    wins = sum(1 for m in metrics_list if m["total_return"] > 0)
    sharpe_values = [m["sharpe"] for m in metrics_list if m["sharpe"] is not None]
    dd_values = [m["max_drawdown"] for m in metrics_list]
    return {
        "total_return": total_return,
        "avg_return": total_return / n,
        "win_rate": wins / n,
        "avg_sharpe": sum(sharpe_values) / len(sharpe_values) if sharpe_values else 0.0,
        "avg_max_drawdown": sum(dd_values) / len(dd_values) if dd_values else 0.0,
        "n_markets": n,
        "n_markets_won": wins,
        "total_trades": sum(m["n_trades"] for m in metrics_list),
        "total_fees": sum(m["fees_paid"] for m in metrics_list),
    }


class CompetitionRunner:
    def __init__(
        self,
        markets: list[MarketDef],
        *,
        initial_cash: float = 1000.0,
        fee_rate: float = 0.02,
        slippage: str = "bar_vwap",
    ):
        self.markets = markets
        self.initial_cash = initial_cash
        self.fee_rate = fee_rate
        self.slippage = slippage

    def run(self, records: list[StrategyRecord]) -> ComparisonResult:
        from src.analytics.metrics import compute_all

        result = ComparisonResult(initial_cash=self.initial_cash)

        for md in self.markets:
            mres = MarketResult(
                token_id=md.token_id,
                question=md.question,
                tag=md.tag,
                n_bars=len(md.bars),
            )

            for rec in records:
                try:
                    strategy: Strategy = rec.strategy_class(
                        **rec.default_params, question=md.question, tag=md.tag
                    )
                    engine = Engine(
                        strategy,
                        md.bars,
                        token_id=md.token_id,
                        initial_cash=self.initial_cash,
                        fee_rate=self.fee_rate,
                        slippage=self.slippage,
                    )
                    run = engine.run()
                    metrics = compute_all(run.equity_curve, run.trades, run.fees_paid)
                    mres.runs[rec.name] = run
                    mres.metrics[rec.name] = metrics
                    log.info(
                        "%s on %s…: return=%.2f%% sharpe=%.3f trades=%d",
                        rec.name, md.token_id[:8], metrics["total_return"] * 100,
                        metrics["sharpe"], metrics["n_trades"],
                    )
                except Exception:
                    log.exception("strategy %s failed on %s…", rec.name, md.token_id[:8])

            result.markets.append(mres)

        # Aggregate per strategy across all markets
        strategy_names = {rec.name for rec in records}
        for name in strategy_names:
            metrics_list = [
                mres.metrics[name]
                for mres in result.markets
                if name in mres.metrics
            ]
            if metrics_list:
                result.aggregate_metrics[name] = _aggregate(metrics_list)

        result.rankings = sorted(
            [
                (name, m["total_return"])
                for name, m in result.aggregate_metrics.items()
            ],
            key=lambda x: x[1],
            reverse=True,
        )
        return result
