"""Async ingestion of market metadata and trades from Polymarket public APIs.

- Markets come from Gamma (`/events`, `/markets`). One Gamma "event" can hold
  multiple markets (e.g. tournament with several matches), each market has a
  YES/NO token pair.
- Trades come from the Data API (`/trades`), filtered by `market` (conditionId)
  and paginated via `offset`. Endpoint is undocumented but stable.

The fetcher is rate-limit-friendly: bounded concurrency via a semaphore,
exponential backoff on 429/5xx, and resume-from-last-seen-timestamp logic so
incremental pulls only fetch new tail data.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from typing import Any, Iterable

import httpx

from src.constants import DATA_HOST, GAMMA_HOST
from src.data.store import Market, Store, Trade

log = logging.getLogger(__name__)

# Bound to keep us friendly with the public APIs. Gamma + Data API have no
# documented limits but degrade gracefully when overloaded.
_SEMAPHORE_SIZE = 8
_PAGE_SIZE = 500
_MAX_RETRIES = 5
_BACKOFF_BASE = 0.5

# SOCKS5 proxy to bypass GFW
_PROXY_URL = "socks5://185.103.103.140:1080"


# ---------- Markets ----------


async def fetch_markets(
    store: Store,
    *,
    tag: str | None = None,
    closed: bool = False,
    limit: int = 500,
    max_pages: int = 10,
    client: httpx.AsyncClient | None = None,
) -> list[Market]:
    """Fetch active markets from Gamma `/markets` and persist to the store.

    `tag` filters by tag_slug (e.g. 'soccer', 'nba', 'crypto', 'politics').
    Returns the list of Market objects upserted this call.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=30.0, proxy=_PROXY_URL)
    try:
        markets: list[Market] = []
        offset = 0
        for _ in range(max_pages):
            params: dict[str, Any] = {
                "closed": str(closed).lower(),
                "limit": str(limit),
                "offset": str(offset),
            }
            if tag:
                params["tag_slug"] = tag
            data = await _get_with_retry(client, f"{GAMMA_HOST}/markets", params=params)
            if not isinstance(data, list) or not data:
                break
            page = [_parse_gamma_market(m) for m in data if _is_clob_market(m)]
            # Gamma API doesn't return tags in the response — inject the
            # tag_slug used for filtering so list_markets(tag=...) works.
            if tag:
                for m in page:
                    if tag not in m.tags:
                        m.tags = [*m.tags, tag]
            markets.extend(page)
            if len(data) < limit:
                break
            offset += limit
        if markets:
            store.upsert_markets(markets)
            log.info("fetched %d markets (tag=%s)", len(markets), tag)
        return markets
    finally:
        if own_client:
            await client.aclose()


def _is_clob_market(m: dict) -> bool:
    """Skip markets without CLOB token IDs — those aren't tradable on the orderbook."""
    return bool(m.get("clobTokenIds")) and bool(m.get("conditionId"))


def _parse_gamma_market(m: dict) -> Market:
    fetched_at = dt.datetime.now(dt.timezone.utc).isoformat()
    # Gamma serializes some array fields as JSON strings — handle both.
    token_ids = m.get("clobTokenIds")
    if isinstance(token_ids, str):
        token_ids = json.loads(token_ids)
    outcomes = m.get("outcomes")
    if isinstance(outcomes, str):
        outcomes = json.loads(outcomes)
    tags = m.get("tags") or []
    if tags and isinstance(tags[0], dict):
        tags = [t.get("slug") for t in tags if t.get("slug")]
    return Market(
        condition_id=m["conditionId"],
        slug=m.get("slug"),
        question=m.get("question") or m.get("title") or "",
        neg_risk=bool(m.get("negRisk")),
        start_date=m.get("startDate"),
        end_date=m.get("endDate"),
        outcomes=list(outcomes or []),
        token_ids=list(token_ids or []),
        tags=list(tags),
        fee_rate=None,  # populated separately via getClobMarketInfo if needed
        fetched_at=fetched_at,
    )


# ---------- Trades ----------


async def fetch_trades(
    store: Store,
    condition_id: str,
    *,
    since: dt.datetime | None = None,
    until: dt.datetime | None = None,
    page_size: int = _PAGE_SIZE,
    max_pages: int = 200,
    client: httpx.AsyncClient | None = None,
) -> int:
    """Pull trades for a market and append them to the store.

    Returns the number of new rows inserted. The Data API returns trades sorted
    by timestamp DESC; we walk pages until we cross `since` (or run out of data).
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=30.0, proxy=_PROXY_URL)
    since_ts = int(since.timestamp()) if since else None
    until_ts = int(until.timestamp()) if until else None

    inserted = 0
    try:
        sem = asyncio.Semaphore(_SEMAPHORE_SIZE)
        offset = 0
        for _ in range(max_pages):
            try:
                async with sem:
                    page = await _get_with_retry(
                        client,
                        f"{DATA_HOST}/trades",
                        params={
                            "market": condition_id,
                            "limit": str(page_size),
                            "offset": str(offset),
                        },
                    )
            except EndOfPagination:
                # API hit its offset limit; stop and keep what we have.
                break
            if not isinstance(page, list) or not page:
                break
            trades = list(_parse_data_api_trades(page, condition_id))
            if until_ts is not None:
                trades = [t for t in trades if t.timestamp <= until_ts]
            if since_ts is not None:
                # Stop once we cross the since boundary, but still ingest the
                # tail of this page to avoid losing in-window rows.
                trades = [t for t in trades if t.timestamp >= since_ts]
                if len(trades) < len(page):
                    inserted += store.upsert_trades(trades)
                    break
            inserted += store.upsert_trades(trades)
            if len(page) < page_size:
                break
            offset += page_size
        log.info("fetched %d trades for condition_id=%s", inserted, condition_id[:10])
        return inserted
    finally:
        if own_client:
            await client.aclose()


def _parse_data_api_trades(page: Iterable[dict], condition_id: str) -> Iterable[Trade]:
    for t in page:
        tx_hash = t.get("transactionHash") or t.get("tx_hash")
        if not tx_hash:
            continue
        try:
            yield Trade(
                tx_hash=tx_hash,
                condition_id=t.get("conditionId") or condition_id,
                token_id=str(t.get("asset") or t.get("token_id") or ""),
                side=str(t.get("side", "BUY")).upper(),
                size=float(t.get("size", 0.0)),
                price=float(t.get("price", 0.0)),
                timestamp=int(t.get("timestamp") or 0),
                wallet=t.get("proxyWallet") or t.get("user") or None,
            )
        except (TypeError, ValueError):
            continue


# ---------- HTTP helper ----------


class EndOfPagination(Exception):
    """Raised when the API returns a 4xx other than 429 — treat as no-more-data."""


async def _get_with_retry(client: httpx.AsyncClient, url: str, params: dict) -> Any:
    """GET with retry on transient errors. 4xx (other than 429) signals stop."""
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            r = await client.get(url, params=params)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                await asyncio.sleep(_BACKOFF_BASE * (2 ** attempt))
                continue
            if 400 <= r.status_code < 500:
                # Polymarket Data API returns 400 past its pagination limit.
                # Caller treats this as "no more pages."
                raise EndOfPagination(f"{r.status_code} from {url}")
            r.raise_for_status()
        except EndOfPagination:
            raise
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            last_exc = e
            await asyncio.sleep(_BACKOFF_BASE * (2 ** attempt))
    raise RuntimeError(f"giving up on {url} after {_MAX_RETRIES} retries") from last_exc


# ---------- OHLC bar construction ----------


def build_ohlc(
    store: Store,
    token_id: str,
    *,
    freq: str = "1min",
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
) -> "pd.DataFrame":
    """Resample raw trades into OHLCV bars at the given pandas frequency.

    Returns a DataFrame indexed by bar-start timestamp (UTC) with columns:
        open, high, low, close, volume, vwap, trades

    Bars with no trades are forward-filled on the close price (open=high=low=
    close=prev_close, volume=0, trades=0). This avoids gaps in event-driven
    backtests where the strategy expects a bar per period.
    """
    import pandas as pd  # local to keep import light at module load

    df = store.trades_dataframe(
        token_id,
        start_ts=int(start.timestamp()) if start else None,
        end_ts=int(end.timestamp()) if end else None,
    )
    if df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "vwap", "trades"])

    df["notional"] = df["price"] * df["size"]
    grouped = df.groupby(pd.Grouper(freq=freq))
    ohlc = grouped["price"].agg(["first", "max", "min", "last"]).rename(
        columns={"first": "open", "max": "high", "min": "low", "last": "close"}
    )
    volume = grouped["size"].sum().rename("volume")
    notional = grouped["notional"].sum()
    trades = grouped.size().rename("trades")
    vwap = (notional / volume.replace(0, pd.NA)).rename("vwap")

    bars = ohlc.join([volume, vwap, trades])
    # Forward-fill close into empty bars to keep continuous price.
    bars["close"] = bars["close"].ffill()
    bars["open"] = bars["open"].fillna(bars["close"])
    bars["high"] = bars["high"].fillna(bars["close"])
    bars["low"] = bars["low"].fillna(bars["close"])
    bars["vwap"] = bars["vwap"].fillna(bars["close"])
    bars["volume"] = bars["volume"].fillna(0.0)
    bars["trades"] = bars["trades"].fillna(0).astype(int)
    return bars
