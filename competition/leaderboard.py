from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path


class Leaderboard:
    def __init__(self, db_path: str | Path = "data/leaderboard.db"):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS leaderboard (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id      TEXT NOT NULL,
                strategy    TEXT NOT NULL,
                category    TEXT,
                token_id    TEXT,
                initial_cash REAL NOT NULL,
                final_equity REAL NOT NULL,
                total_return REAL NOT NULL,
                sharpe      REAL,
                max_drawdown REAL,
                n_trades    INTEGER,
                fees_paid   REAL,
                params_json TEXT,
                created_at  TEXT NOT NULL
            )
        """)
        self._conn.commit()

    def record(self, run, metrics: dict, strategy_name: str, category: str | None = None) -> None:
        from src.constants import DEFAULT_CACHE_DB
        with self._conn:
            self._conn.execute("""
                INSERT INTO leaderboard
                    (run_id, strategy, category, token_id, initial_cash, final_equity,
                     total_return, sharpe, max_drawdown, n_trades, fees_paid, params_json, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                run.run_id, strategy_name, category, run.token_id,
                run.initial_cash, run.final_equity,
                metrics["total_return"], metrics["sharpe"], metrics["max_drawdown"],
                metrics["n_trades"], metrics["fees_paid"],
                json.dumps(run.params),
                dt.datetime.now(dt.timezone.utc).isoformat(),
            ))

    def rankings(self, category: str | None = None, limit: int = 20) -> list[dict]:
        sql = """
            SELECT strategy, AVG(total_return) as avg_return,
                   AVG(sharpe) as avg_sharpe, COUNT(*) as runs,
                   MAX(created_at) as last_run
            FROM leaderboard
        """
        params: list = []
        if category:
            sql += " WHERE category = ?"
            params.append(category)
        sql += " GROUP BY strategy ORDER BY avg_return DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def best_run(self, strategy_name: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM leaderboard WHERE strategy = ? ORDER BY total_return DESC LIMIT 1",
            (strategy_name,),
        ).fetchone()
        return dict(row) if row else None

    def close(self) -> None:
        self._conn.close()
