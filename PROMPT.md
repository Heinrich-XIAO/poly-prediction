Your end goal, is to create an algorithm that is profitable on polymarket. However, immediately running on polymarket is too risky, so instead, you will run this command to backtest:
```bash
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && python -m src.cli.main fetch --tag soccer --with-trades --since 2026-06-01 && python scripts/run_competition.py --tag soccer --freq 5min --cash 1000
```

In the directory that you are currently in, there are a number of strategies. These are your competitors. You must beat these competitors by outperforming them. Look at what they're doing, combine them, modify them, improve on them and iterate upon them, or just make your own one.

It is hard to come by original ideas, since your competitors are running similarly archetected AI models, so curl https://random-words-api.kushcreates.com/api?words=5 to get five random words to inspire yourself. Your strategy doesn't have to relate to the words directly. For example, if one of the words is condensation, you might try to implement regime changes since condensation goes from gaseous to liquid. Of course, you want to be as different as possible, so actually implementing a regime change would be incredibly lazy.

Polymarket tends to not have the best category separation, so try to check whether your strategy works well on only a subset of the markets in a certain category and what similarities they have with eachother. Sometimes, it might just be that they're completely different. Or, it might just be that the only difference between the two types of markets is that one of them resolves yes and one of them resolves no and so your strategy only works with one of them.

Try to find areas with little to no competition. This is where the five random words come in. If one of the words is cloud, you might try to look into the weather category of prediction. Weather has a completely different distribution then other categories. For example, hottest temperature in a day in a certain city usually is certain after a certain point since the warmest time of day is usually a bit after noon.

Do research. The niches often require a bit of research. Maybe one sports team always plays against a certain other team. If you heard that online, maybe analyze some statistics on whether or not that's actually true. Rumours are often not as reliable as you think, and when rumours are false, prices follow the rumour, but resolution always follows the truth.

NEVER BE TOO CONFIDENT. Doubt everything that you haven't explicitly checked.

CASHING OUT IS IMPORTANT. It is often that people predict then hold. That's usually a bad strategy, because you're relying on the information from one time. Use `strategies/base.py`'s `with_cash_out(strategy, take_profit_pct=0.20, stop_loss_pct=-0.25)` to add exit logic to any strategy.

How polymarket works: First, you can buy shares. You can buy Yes, and you can buy No. In the end, all markets resolve to either Yes or No. If you bet on the wrong one, you lose all of your investment. If you bet on the right one, you get $1 per share, so you gain the differce between $1 and the initial price of one share. The big difference between this and a binary option, is that you CAN cash out in the middle.

Write your strategies in `strategies/originals/` or `strategies/hybrids/`. Subclass `CashOutStrategy` from `strategies/base.py` and implement `_on_bar(self, bar, portfolio) -> list[Order]`.
