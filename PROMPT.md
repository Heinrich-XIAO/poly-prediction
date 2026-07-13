# Goal

Create a profitable Polymarket trading strategy. Do not trade live — prove it via backtest. Beat every competitor registered in the competition runner.

---

## Step 1: Setup

```bash
# Check if venv exists
ls .venv/bin/activate 2>/dev/null && echo "venv exists" || echo "need to create venv"
```

If venv doesn't exist:
```bash
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

If venv exists:
```bash
source .venv/bin/activate
```

Verify imports work:
```bash
python -c "from strategies.base import CashOutStrategy; print('OK')"
```

## Step 2: Fetch market data

Fetch at least one tag. Pick the first tag that succeeds:
```bash
python -m src.cli.main fetch --tag soccer --with-trades --since 2026-06-01
```

If that fails or returns nothing, try the next:
```bash
python -m src.cli.main fetch --tag crypto --with-trades --since 2026-06-01
python -m src.cli.main fetch --tag politics --with-trades --since 2026-06-01
python -m src.cli.main fetch --tag weather --with-trades --since 2026-06-01
python -m src.cli.main fetch --tag nba --with-trades --since 2026-06-01
```

Stop when at least one tag has cached data (verify with `list` command):
```bash
python -m src.cli.main list --tag soccer --limit 5
```

Record which tags succeeded — you'll use them later.

## Step 3: Run the baseline competition

The competition tests every strategy on **every resolved past market** in the category with enough trade data. A strategy that only wins on one market will not rank well — it must perform consistently across many markets.

Run the competition on the tag with data:
```bash
python scripts/sandbox_run.py --tag soccer --freq 5min --cash 1000 --max-markets 20
```

Replace `soccer` with whichever tag succeeded. Record:
- The current leader's Total Return, Win Rate, and Avg Sharpe across all markets
- This aggregate score is what you must beat

Flags: `--min-bars` (default 20) filters out markets with too few bars. `--max-markets` (default 50) limits how many markets to test on.

## Step 4: Get inspired

Fetch 5 random words:
```bash
curl https://random-words-api.kushcreates.com/api?words=5
```

Map them to strategy concepts. For example, "cloud" → weather markets, "rust" → mean-reversion, "tide" → cyclic patterns.

You can also analyze which categories your competitors are weak in — try different `--tag` values with `run_competition.py` to see where each strategy loses.

## Step 5: Create a strategy

Your strategy will be tested on **every market** in the category, not a single cherry-picked one. It can choose to skip a market entirely (return no orders). Use `self.question` and `self.tag` to decide.

Write a new file in `strategies/originals/` or `strategies/hybrids/`. Your strategy must:

1. Subclass `CashOutStrategy` from `strategies/base.py`
2. Implement `_on_bar(self, bar, portfolio) -> list[Order]`
3. Use the indicator helpers and numpy arrays (see "Available tools" below)

Example skeleton:
```python
from strategies.base import CashOutStrategy
from src.strategy.base import Bar, Order, PortfolioView, Side
from typing import Iterable
import numpy as np
import re

class MyStrategy(CashOutStrategy):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # self.question and self.tag are set per-market

    def _on_bar(self, bar: Bar, portfolio: PortfolioView) -> Iterable[Order]:
        if self.n_bars < 20:
            return []
        # Example: skip markets that don't fit your niche
        if not re.search(r"win|defeat|beat", self.question, re.I):
            return []
        if bar.close < self.sma(20) * 0.95:
            return [Order(token_id=bar.token_id, side=Side.BUY,
                          size=100 / bar.close, reason="entry")]
        return []
```

## Step 6: Register and test

Edit `scripts/run_competition.py` — add your strategy to `_register_builtins()`:
```python
from strategies.originals.my_strategy import MyStrategy
register(StrategyRecord(
    name="my_strategy", strategy_class=MyStrategy,
    default_params={},
    category_tags=["soccer", "crypto"],
    description="My custom strategy.",
))
```

Run the competition (tests every strategy on **all markets** in the tag):
```bash
python scripts/sandbox_run.py --tag soccer --freq 5min --cash 1000 --max-markets 20
```

## Step 7: Iterate

Judging is based on the **aggregate leaderboard** — Total Return across all markets, Win Rate, and Avg Sharpe. A strategy that wins big on one market but loses on five others will rank below one that makes small steady profits on every market.

- If your strategy's aggregate Total Return beats the current leader → try to improve it further
- If it doesn't → create a new one. Try different indicators, parameter combinations, or a different approach entirely
- Try wrapping with cash-out: `with_cash_out(MyStrategy(), take_profit_pct=0.20, stop_loss_pct=-0.25)`
- Try different categories — your strategy might dominate in crypto but not soccer
- Use `--max-markets 50` for a broad test (your final test must be with 50 tests, otherwise, you have not truly beaten your competitors) or `--max-markets 5` for a quick sanity check
- Stop when no improvement has been made for 3 consecutive rounds

## Step 8: Deliver

Print the final results:
- The winning strategy code
- Its return and Sharpe vs every competitor
- The key insight that made it work

Make sure to write this in `agent_summaries/AGENT_<the current maximum number in there+1>.md`. If there is not a single file in there, start it at `AGENT_0.md`. If there is already a file there, format everything in a similar way as it.

---

## Reference: Available tools

Your strategy inherits from `CashOutStrategy` (in `strategies/base.py`), which provides:

**Bar history** (accumulated automatically each bar):
- `self.closes` — numpy array of all closing prices so far
- `self.volumes`, `self.highs`, `self.lows`, `self.opens`, `self.vwaps` — same
- `self.n_bars` — number of bars received so far
- `self.bars_df` — all bars as a pandas DataFrame

**Indicators** (PIT-safe — no future data):
- `self.sma(n)` — simple moving average
- `self.ema(n)` — exponential moving average
- `self.rsi(n=14)` — relative strength index (0–100)
- `self.bollinger_bands(n=20, k=2)` — returns `(upper, mid, lower)`
- `self.atr(n=14)` — average true range
- `self.macd(fast=12, slow=26, signal=9)` — returns `(macd_line, signal_line, histogram)`
- `self.stochastic(n=14, k_smooth=3)` — returns `(%K, %D)`
- `self.volume_ratio(n=20)` — current volume / average volume
- `self.price_change(n=1)` — price change over n bars
- `self.rolling_max(n)`, `self.rolling_min(n)`, `self.rolling_std(n)`

Use numpy and pandas directly:
```python
import numpy as np
returns = np.diff(self.closes) / self.closes[:-1]
volatility = np.std(returns[-20:])
```

## Reference: Cash-out

Most strategies lose because they hold too long. Wrap any strategy with take-profit/stop-loss:
```python
from strategies.base import with_cash_out
wrapped = with_cash_out(MyStrategy(), take_profit_pct=0.20, stop_loss_pct=-0.25)
```

## Reference: Question constraint

You **cannot** use the question text to make trading decisions based on your knowledge of the event outcome. This is backtesting past events — your training data may contain the answer, so using the question directly would be cheating.

Rules:
- You may look at ≤5 questions total (print them if debugging)
- Any question processing in code must use **simple regex only** (`re.search`, `re.match`, `re.findall`)
- Allowed: `re.search(r"temperature|high|low", self.question, re.I)` — detects category
- Forbidden: using the question to recall who actually won

## Reference: How Polymarket works

You buy shares — Yes or No. Markets resolve to Yes or No. If you bet right, you get $1/share. If wrong, you lose everything. The key difference from binary options: you can cash out at any time before resolution. Prices move based on probability — buy cheap when uncertain, sell expensive when confident, or hold to resolution.



NEVER COMMIT UNTIL YOU'VE ASKED THE USER WHETHER YOU SHOULD COMMIT.