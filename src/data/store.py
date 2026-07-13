"""SQLite cache for market metadata, raw trades, and resampled OHLC bars.

Designed for write-once-read-many. Trades come from the Polymarket Data API
(append-only, dedup by tx_hash), markets from Gamma (refreshed on demand),
OHLC is materialized lazily from trades on first access per (token_id, freq).

Schema is intentionally narrow — only fields the backtester actually consumes.
Add columns by extending the migrations list at the bottom of this file.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

import pandas as pd

from src.constants import DEFAULT_CACHE_DB

# ---------- Schema ----------

_SCHEMA = [
    # markets — one row per Polymarket market (a YES/NO pair shares a conditionId)
    """
    CREATE TABLE IF NOT EXISTS markets (
        condition_id     TEXT PRIMARY KEY,
        slug             TEXT,
        question         TEXT NOT NULL,
        neg_risk         INTEGER NOT NULL DEFAULT 0,
        start_date       TEXT,
        end_date         TEXT,
        outcomes_json    TEXT NOT NULL,   -- JSON array, e.g. ["Yes","No"]
        token_ids_json   TEXT NOT NULL,   -- JSON array of CLOB tokenIds aligned with outcomes
        tags_json        TEXT,            -- JSON array of tag slugs
        fee_rate         REAL,            -- per-market fee rate when known, else NULL
        fetched_at       TEXT NOT NULL
    );
    """,
    # trades — append-only, deduped by tx_hash
    """
    CREATE TABLE IF NOT EXISTS trades (
        tx_hash          TEXT PRIMARY KEY,
        condition_id     TEXT NOT NULL,
        token_id         TEXT NOT NULL,
        side             TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
        size             REAL NOT NULL,
        price            REAL NOT NULL,
        timestamp        INTEGER NOT NULL,    -- unix seconds
        wallet           TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_trades_token_ts ON trades(token_id, timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_trades_condition_ts ON trades(condition_id, timestamp);",
    # backtest_runs — record of each backtest invocation, for the report subcommand
    """
    CREATE TABLE IF NOT EXISTS backtest_runs (
        run_id           TEXT PRIMARY KEY,
        strategy_name    TEXT NOT NULL,
        params_json      TEXT NOT NULL,
        token_id         TEXT NOT NULL,
        start_ts         INTEGER NOT NULL,
        end_ts           INTEGER NOT NULL,
        initial_cash     REAL NOT NULL,
        final_equity     REAL NOT NULL,
        metrics_json     TEXT NOT NULL,
        trades_json      TEXT NOT NULL,
        equity_curve_json TEXT NOT NULL,
        created_at       TEXT NOT NULL
    );
    """,
]


# ---------- Models ----------


@dataclass
class Market:
    condition_id: str
    slug: str | None
    question: str
    neg_risk: bool
    start_date: str | None
    end_date: str | None
    outcomes: list[str]
    token_ids: list[str]
    tags: list[str]
    fee_rate: float | None
    fetched_at: str


@dataclass
class Trade:
    tx_hash: str
    condition_id: str
    token_id: str
    side: str  # 'BUY' | 'SELL'
    size: float
    price: float
    timestamp: int  # unix seconds
    wallet: str | None


# ---------- Store ----------


class Store:
    """Thin sqlite3 wrapper. Not thread-safe; one Store per backtest process."""

    def __init__(self, path: str | Path = DEFAULT_CACHE_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        for stmt in _SCHEMA:
            self._conn.execute(stmt)
        self._conn.commit()

    # ----- markets -----

    def upsert_markets(self, markets: Sequence[Market]) -> int:
        rows = [
            (
                m.condition_id,
                m.slug,
                m.question,
                int(m.neg_risk),
                m.start_date,
                m.end_date,
                json.dumps(m.outcomes),
                json.dumps(m.token_ids),
                json.dumps(m.tags),
                m.fee_rate,
                m.fetched_at,
            )
            for m in markets
        ]
        with self._conn:
            self._conn.executemany(
                """
                INSERT INTO markets
                  (condition_id, slug, question, neg_risk, start_date, end_date,
                   outcomes_json, token_ids_json, tags_json, fee_rate, fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(condition_id) DO UPDATE SET
                  slug=excluded.slug,
                  question=excluded.question,
                  neg_risk=excluded.neg_risk,
                  start_date=excluded.start_date,
                  end_date=excluded.end_date,
                  outcomes_json=excluded.outcomes_json,
                  token_ids_json=excluded.token_ids_json,
                  tags_json=excluded.tags_json,
                  fee_rate=COALESCE(excluded.fee_rate, markets.fee_rate),
                  fetched_at=excluded.fetched_at
                """,
                rows,
            )
        return len(rows)

    def get_market(self, condition_id: str) -> Market | None:
        row = self._conn.execute(
            "SELECT * FROM markets WHERE condition_id = ?", (condition_id,)
        ).fetchone()
        return _row_to_market(row) if row else None

    def get_market_by_token(self, token_id: str) -> Market | None:
        for row in self._conn.execute("SELECT * FROM markets"):
            if token_id in json.loads(row["token_ids_json"]):
                return _row_to_market(row)
        return None

    def list_markets(self, tag: str | None = None) -> list[Market]:
        rows = self._conn.execute("SELECT * FROM markets ORDER BY fetched_at DESC").fetchall()
        markets = [_row_to_market(r) for r in rows]
        if tag:
            markets = [m for m in markets if tag in m.tags]
        return markets

    # ----- trades -----

    def upsert_trades(self, trades: Sequence[Trade]) -> int:
        if not trades:
            return 0
        rows = [
            (t.tx_hash, t.condition_id, t.token_id, t.side, t.size, t.price, t.timestamp, t.wallet)
            for t in trades
        ]
        with self._conn:
            cur = self._conn.executemany(
                """
                INSERT OR IGNORE INTO trades
                  (tx_hash, condition_id, token_id, side, size, price, timestamp, wallet)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                rows,
            )
        return cur.rowcount

    def trades_dataframe(
        self,
        token_id: str,
        start_ts: int | None = None,
        end_ts: int | None = None,
    ) -> pd.DataFrame:
        """Pull trades for a token as a DataFrame indexed by timestamp (UTC)."""
        clauses = ["token_id = ?"]
        params: list = [token_id]
        if start_ts is not None:
            clauses.append("timestamp >= ?")
            params.append(start_ts)
        if end_ts is not None:
            clauses.append("timestamp <= ?")
            params.append(end_ts)
        sql = f"""
            SELECT timestamp, side, size, price
              FROM trades
             WHERE {' AND '.join(clauses)}
             ORDER BY timestamp ASC
        """
        df = pd.read_sql_query(sql, self._conn, params=params)
        if df.empty:
            return df
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        df = df.set_index("timestamp")
        return df

    def trade_count(self, token_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM trades WHERE token_id = ?", (token_id,)
        ).fetchone()
        return int(row["n"])

    # ----- runs -----

    def insert_run(self, run: dict) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO backtest_runs
                  (run_id, strategy_name, params_json, token_id, start_ts, end_ts,
                   initial_cash, final_equity, metrics_json, trades_json, equity_curve_json,
                   created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run["run_id"],
                    run["strategy_name"],
                    json.dumps(run["params"]),
                    run["token_id"],
                    run["start_ts"],
                    run["end_ts"],
                    run["initial_cash"],
                    run["final_equity"],
                    json.dumps(run["metrics"]),
                    json.dumps(run["trades"]),
                    json.dumps(run["equity_curve"]),
                    run["created_at"],
                ),
            )

    def get_run(self, run_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM backtest_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if not row:
            return None
        return {
            "run_id": row["run_id"],
            "strategy_name": row["strategy_name"],
            "params": json.loads(row["params_json"]),
            "token_id": row["token_id"],
            "start_ts": row["start_ts"],
            "end_ts": row["end_ts"],
            "initial_cash": row["initial_cash"],
            "final_equity": row["final_equity"],
            "metrics": json.loads(row["metrics_json"]),
            "trades": json.loads(row["trades_json"]),
            "equity_curve": json.loads(row["equity_curve_json"]),
            "created_at": row["created_at"],
        }

    def list_runs(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT run_id, strategy_name, token_id, final_equity, initial_cash, created_at "
            "FROM backtest_runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ----- lifecycle -----

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# ---------- helpers ----------


def _row_to_market(row: sqlite3.Row) -> Market:
    return Market(
        condition_id=row["condition_id"],
        slug=row["slug"],
        question=row["question"],
        neg_risk=bool(row["neg_risk"]),
        start_date=row["start_date"],
        end_date=row["end_date"],
        outcomes=json.loads(row["outcomes_json"]),
        token_ids=json.loads(row["token_ids_json"]),
        tags=json.loads(row["tags_json"]) if row["tags_json"] else [],
        fee_rate=row["fee_rate"],
        fetched_at=row["fetched_at"],
    )
