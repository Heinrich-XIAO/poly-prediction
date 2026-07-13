Your end goal, is to create an algorithm that is profitable on polymarket. However, immediately running on polymarket is too risky, so instead, you will run this command to backtest:
```bash
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && python -m src.cli.main fetch --tag soccer --with-trades --since 2026-06-01 && python scripts/run_competition.py --tag soccer --freq 5min --cash 1000
```

In the directory that you are currently in, there are a number of strategies. These are your competitors. You must beat these competitors by outperforming them. Look at what they're doing, combine them, modify them, improve on them and iterate upon them, or just make your own one.

To compare your strategy against competitors at any time:
```bash
python scripts/run_competition.py --tag <category> --freq <bar_freq> --cash <initial_cash>
```

It is hard to come by original ideas, since your competitors are running similarly archetected AI models, so curl https://random-words-api.kushcreates.com/api?words=5 to get five random words to inspire yourself. Or use the built-in tool:
```bash
python scripts/explore.py --count 5
```
Your strategy doesn't have to relate to the words directly. For example, if one of the words is condensation, you might try to implement regime changes since condensation goes from gaseous to liquid. Of course, you want to be as different as possible, so actually implementing a regime change would be incredibly lazy.

Polymarket tends to not have the best category separation, so try to check whether your strategy works well on only a subset of the markets in a certain category and what similarities they have with eachother. Sometimes, it might just be that they're completely different. Or, it might just be that the only difference between the two types of markets is that one of them resolves yes and one of them resolves no and so your strategy only works with one of them. Research a category with:
```bash
python scripts/research_category.py --tag <category>
```

Try to find areas with little to no competition. This is where the five random words come in. If one of the words is cloud, you might try to look into the weather category of prediction. Weather has a completely different distribution then other categories. For example, hottest temperature in a day in a certain city usually is certain after a certain point since the warmest time of day is usually a bit after noon.

Do research. The niches often require a bit of research. Maybe one sports team always plays against a certain other team. If you heard that online, maybe analyze some statistics on whether or not that's actually true. Rumours are often not as reliable as you think, and when rumours are false, prices follow the rumour, but resolution always follows the truth.

NEVER BE TOO CONFIDENT. Doubt everything that you haven't explicitly checked.

CASHING OUT IS IMPORTANT. It is often that people predict then hold. That's usually a bad strategy, because you're relying on the information from one time. Use the cash-out wrapper to test take-profit and stop-loss thresholds:
```bash
python scripts/cash_out_study.py --tag <category> --freq <bar_freq>
```
To add cash-out to any strategy, wrap it with `with_cash_out(strategy, take_profit_pct=0.20, stop_loss_pct=-0.25)` from `strategies.base`.

How polymarket works: First, you can buy shares. You can buy Yes, and you can buy No. In the end, all markets resolve to either Yes or No. If you bet on the wrong one, you lose all of your investment. If you bet on the right one, you get $1 per share, so you gain the differce between $1 and the initial price of one share. The big difference between this and a binary option, is that you CAN cash out in the middle.

## Architecture reference

```
poly-prediction/
├── src/                          # Backtest engine, data fetchers, fees, analytics
│   ├── sim/engine.py             # Engine(strategy, bars, token_id) → Run
│   ├── data/fetcher.py           # fetch_markets, fetch_trades, build_ohlc
│   ├── data/store.py             # SQLite cache (Store)
│   └── analytics/metrics.py      # compute_all(run) → {sharpe, sortino, drawdown, ...}
├── competition/                  # Compare strategies head-to-head
│   ├── registry.py               # register(StrategyRecord), list_strategies(category)
│   ├── runner.py                 # CompetitionRunner(bars, token_id).run(records)
│   └── leaderboard.py            # SQLite-backed rankings
├── strategies/                   # Your strategies live here
│   ├── base.py                   # with_cash_out(strat, tp, sl, max_bars) wrapper
│   ├── builtin/                  # buy_and_hold, momentum_sma (competitors)
│   ├── hybrids/                  # → write combined strategies here
│   └── originals/                # → write original strategies here
├── ideas/                        # Ideation tools
│   ├── kindle.py                 # fetch_random_words(n) → strategy hints
│   ├── categories.py             # analyze_category_performance(store, strategy)
│   └── niches.py                 # find_uncrowded_niches(perf_dict)
├── research/                     # Research tools
│   ├── statistics.py             # category_distributions, token_volume_profile
│   ├── rumors.py                 # price_resolution_discrepancy(condition_id)
│   └── calendar_analysis.py      # resolution_patterns(tag)
└── scripts/
    ├── explore.py                # Random words → strategy ideas
    ├── run_competition.py        # Run all strategies, compare results
    ├── research_category.py      # Deep-dive into a category
    └── cash_out_study.py         # Grid-search TP/SL thresholds
```

### How to write a strategy

Write a class in `strategies/originals/` or `strategies/hybrids/`:

```python
from strategies.base import CashOutStrategy
from src.strategy.base import Bar, Order, PortfolioView, Side
from typing import Iterable

class MyStrategy(CashOutStrategy):
    def __init__(self, param1=0.5, **kwargs):
        super().__init__(**kwargs)
        self.param1 = param1

    def _on_bar(self, bar: Bar, portfolio: PortfolioView) -> Iterable[Order]:
        # Inspect bar.close, bar.volume, portfolio.cash, portfolio.position(token_id)
        if bar.close < 0.30 and portfolio.cash > 100:
            return [Order(token_id=bar.token_id, side=Side.BUY, size=100 / bar.close, reason="entry")]
        return []

    # Optional: override _should_exit for custom exit logic
    def _should_exit(self, bar, token_id, position) -> bool:
        return False  # or use with_cash_out wrapper instead
```

Then register it in `config/competitors.yaml` or in `scripts/run_competition.py` and re-run the competition.
