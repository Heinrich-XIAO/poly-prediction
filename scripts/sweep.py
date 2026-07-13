#!/usr/bin/env python3
"""Quick param sweep for momentum_adaptive."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.store import Store
from src.data.fetcher import build_ohlc
from src.sim.engine import Engine
from src.analytics.metrics import compute_all
from strategies.originals.momentum_trailing import MomentumAdaptive

results = []
for trailing in [0.05, 0.08, 0.10, 0.12, 0.15, 0.20]:
    for entry in [0.015, 0.02, 0.025, 0.03]:
        total_ret = 0
        n_wins = 0
        n_markets = 0
        total_sharpe = 0
        total_trades = 0

        with Store('data/cache.db') as store:
            markets = store.list_markets()
            for m in markets:
                if not m.token_ids:
                    continue
                bars = build_ohlc(store, m.token_ids[0], freq='5min')
                if len(bars) < 20:
                    continue
                n_markets += 1

                strategy = MomentumAdaptive(
                    entry_threshold=entry, trailing_pct=trailing
                )
                engine = Engine(
                    strategy, bars, token_id=m.token_ids[0],
                    initial_cash=1000, fee_rate=0.02, slippage='bar_vwap'
                )
                run = engine.run()
                metrics = compute_all(run.equity_curve, run.trades, run.fees_paid)
                total_ret += metrics['total_return'] * 100
                total_sharpe += metrics['sharpe'] if metrics['sharpe'] else 0
                total_trades += metrics['n_trades']
                if metrics['total_return'] > 0:
                    n_wins += 1

        avg_sharpe = total_sharpe / n_markets if n_markets else 0
        results.append((trailing, entry, total_ret, n_wins, n_markets, avg_sharpe, total_trades))

results.sort(key=lambda x: x[2], reverse=True)
print(f'{"Trail%":>6} {"Entry%":>7} {"Ret%":>6} {"Win":>4} {"AvgSh":>6} {"Trades":>6}')
for t, e, ret, w, n, sh, tr in results[:10]:
    print(f'{t*100:6.1f} {e*100:7.1f} {ret:+6.2f} {w}/{n} {sh:6.3f} {tr:6d}')
