"""Polymarket V2 constants and protocol parameters.

Sourced from docs.polymarket.com/v2-migration and the cheatsheet repo. Keep
this file as the single source of truth — every other module imports from here.
"""

from __future__ import annotations

# ---------- Chain ----------

POLYGON_CHAIN_ID = 137
USDC_DECIMALS = 6
USDC_SCALE = 10 ** USDC_DECIMALS  # multiply USD by this to get on-chain units

# ---------- Endpoints ----------

GAMMA_HOST = "https://gamma-api.polymarket.com"
DATA_HOST = "https://data-api.polymarket.com"
CLOB_HOST = "https://clob.polymarket.com"
CLOB_HOST_STAGING = "https://clob-v2.polymarket.com"

# ---------- V2 contracts (post-April 22, 2026 cutover) ----------

V2_EXCHANGE_STANDARD = "0xE111180000d2663C0091e4f400237545B87B996B"
V2_EXCHANGE_NEG_RISK = "0xe2222d279d744050d28e00520010520000310F59"

# ---------- V1 contracts (legacy, kept for historical backtests) ----------

V1_EXCHANGE_STANDARD = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
V1_EXCHANGE_NEG_RISK = "0xC5d563A36AE78145C45a50134d48A1215220f80a"

# ---------- EIP-712 domain versions ----------
# Exchange domain version flipped from "1" to "2" at cutover.
# ClobAuth domain version stays at "1" — easy to conflate, see migration kit.

V2_EXCHANGE_DOMAIN_VERSION = "2"
V1_EXCHANGE_DOMAIN_VERSION = "1"
CLOB_AUTH_DOMAIN_VERSION = "1"

# ---------- Fee defaults ----------
# V2 fees are protocol-set per-market via getClobMarketInfo().fd.rate.
# Use this default when metadata is missing or for quick what-if sims.

DEFAULT_FEE_RATE = 0.02  # 2%, the most common per-market rate as of cutover

# Cutover boundary — bars before this use V1 fee model, after use V2.
import datetime as _dt
V2_CUTOVER_UTC = _dt.datetime(2026, 4, 22, 11, 0, 0, tzinfo=_dt.timezone.utc)

# ---------- Backtest engine defaults ----------

DEFAULT_BAR_FREQ = "1min"
DEFAULT_INITIAL_CASH = 1000.0  # pUSD
DEFAULT_MAX_PARTICIPATION = 0.30  # max 30% of bar volume per fill
DEFAULT_SLIPPAGE_MODEL = "bar_vwap"
DEFAULT_LINEAR_IMPACT_BPS = 20.0  # for the linear_impact slippage model

# ---------- Cache ----------

DEFAULT_CACHE_DB = "data/cache.db"
