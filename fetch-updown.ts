/**
 * Fetch all crypto 1-hour Up/Down market data from Polymarket.
 *
 * - Discovers all hourly updown events via the Gamma API
 * - Downloads every trade for each market via the Data API
 * - Stores everything in a local SQLite database (data/updown.db)
 *
 * Usage:  bun run fetch-updown.ts [--resume]
 */

import { Database } from "bun:sqlite";
import { mkdirSync } from "fs";
import { dirname } from "path";

// ── Config ───────────────────────────────────────────────────────────────────

const GAMMA_HOST = "https://gamma-api.polymarket.com";
const DATA_HOST = "https://data-api.polymarket.com";

const PAGE_SIZE = 100; // Gamma events per page
const TRADE_PAGE = 500; // Data API trades per page
const CONCURRENCY = 8; // parallel trade-fetch workers
const DB_PATH = "data/updown.db";

// ── SQLite setup ─────────────────────────────────────────────────────────────

mkdirSync(dirname(DB_PATH), { recursive: true });

const db = new Database(DB_PATH);
db.exec("PRAGMA journal_mode=WAL");
db.exec("PRAGMA synchronous=NORMAL");

db.exec(`
  CREATE TABLE IF NOT EXISTS events (
    id              TEXT PRIMARY KEY,
    title           TEXT,
    slug            TEXT,
    start_date      TEXT,
    end_date        TEXT,
    asset_type      TEXT,
    tags_json       TEXT,
    fetched_at      TEXT
  );

  CREATE TABLE IF NOT EXISTS markets (
    condition_id    TEXT PRIMARY KEY,
    event_id        TEXT,
    slug            TEXT,
    question        TEXT,
    outcomes_json   TEXT,
    token_ids_json  TEXT,
    end_date        TEXT,
    active          INTEGER,
    closed          INTEGER,
    fetched_at      TEXT
  );

  CREATE TABLE IF NOT EXISTS trades (
    tx_hash         TEXT PRIMARY KEY,
    condition_id    TEXT NOT NULL,
    token_id        TEXT NOT NULL,
    side            TEXT NOT NULL,
    size            REAL NOT NULL,
    price           REAL NOT NULL,
    timestamp       INTEGER NOT NULL,
    wallet          TEXT
  );
  CREATE INDEX IF NOT EXISTS idx_trades_cond_ts ON trades(condition_id, timestamp);
  CREATE INDEX IF NOT EXISTS idx_trades_token_ts ON trades(token_id, timestamp);

  CREATE TABLE IF NOT EXISTS fetch_log (
    condition_id    TEXT PRIMARY KEY,
    total_trades    INTEGER,
    last_offset     INTEGER,
    complete        INTEGER,
    updated_at      TEXT
  );
`);

const insertEvent = db.prepare(
  `INSERT OR IGNORE INTO events (id,title,slug,start_date,end_date,asset_type,tags_json,fetched_at)
   VALUES (?,?,?,?,?,?,?,?)`
);
const insertMarket = db.prepare(
  `INSERT OR IGNORE INTO markets (condition_id,event_id,slug,question,outcomes_json,token_ids_json,end_date,active,closed,fetched_at)
   VALUES (?,?,?,?,?,?,?,?,?,?)`
);
const upsertTrade = db.prepare(
  `INSERT OR IGNORE INTO trades (tx_hash,condition_id,token_id,side,size,price,timestamp,wallet)
   VALUES (?,?,?,?,?,?,?,?)`
);
const upsertFetchLog = db.prepare(
  `INSERT OR REPLACE INTO fetch_log (condition_id,total_trades,last_offset,complete,updated_at)
   VALUES (?,?,?,?,?)`
);
const getFetchLog = db.prepare(
  `SELECT * FROM fetch_log WHERE condition_id = ?`
);

// ── HTTP helpers ─────────────────────────────────────────────────────────────

async function fetchJSON(url: string, params?: Record<string, string>): Promise<any> {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  for (let attempt = 0; attempt < 5; attempt++) {
    try {
      const res = await fetch(url + qs, {
        headers: { Accept: "application/json" },
        signal: AbortSignal.timeout(30_000),
      });
      if (res.status === 200) return res.json();
      if (res.status === 429 || res.status >= 500) {
        await Bun.sleep(500 * 2 ** attempt);
        continue;
      }
      if (res.status >= 400) return null; // no more data
      throw new Error(`HTTP ${res.status}`);
    } catch (e: any) {
      if (attempt === 4) throw e;
      await Bun.sleep(500 * 2 ** attempt);
    }
  }
  return null;
}

// ── Discover all hourly updown events ────────────────────────────────────────

interface GammaEvent {
  id: string;
  title: string;
  slug: string;
  startDate: string;
  endDate: string;
  tags: Array<{ slug: string }>;
  markets: Array<{
    conditionId: string;
    slug: string;
    question: string;
    outcomes: string;
    clobTokenIds: string;
    endDate: string;
    active: boolean;
    closed: boolean;
  }>;
}

const ASSET_TAGS = new Set([
  "bitcoin", "ethereum", "solana", "xrp", "dogecoin", "bnb", "hype",
  "cardano", "polkadot", "chainlink", "litecoin", "avalanche",
  "polygon", "uniswap", "aave", "maker", "arbitrum", "optimism",
]);

function extractAsset(tags: Array<{ slug: string }>): string {
  for (const t of tags) {
    if (ASSET_TAGS.has(t.slug)) return t.slug;
  }
  return "unknown";
}

async function discoverEvents(): Promise<GammaEvent[]> {
  const all: GammaEvent[] = [];
  let offset = 0;
  let consecutiveEmpty = 0;

  console.log("🔍 Discovering hourly up/down events...");

  while (true) {
    const page = (await fetchJSON(`${GAMMA_HOST}/events`, {
      tag_slug: "up-or-down",
      recurrence: "hourly",
      limit: String(PAGE_SIZE),
      offset: String(offset),
    })) as GammaEvent[] | null;

    if (!page || page.length === 0) {
      consecutiveEmpty++;
      if (consecutiveEmpty >= 2) break;
      offset += PAGE_SIZE;
      continue;
    }
    consecutiveEmpty = 0;

    // Filter to genuine hourly updown events (tag is "1H" not "hourly")
    const hourly = page.filter((e) => {
      const slugs = (e.tags || []).map((t) => t.slug);
      return (slugs.includes("1H") || slugs.includes("hourly")) && slugs.includes("up-or-down");
    });

    all.push(...hourly);
    process.stdout.write(
      `\r  offset=${offset}  page=${page.length}  hourly=${hourly.length}  total=${all.length}`
    );

    if (page.length < PAGE_SIZE) break;
    offset += PAGE_SIZE;

    // Polymarket caps at ~2800 results; after that it loops
    if (offset > 10000) break;
  }

  console.log(`\n✅ Found ${all.length} hourly up/down events`);
  return all;
}

// ── Fetch trades for a single market ─────────────────────────────────────────

interface DataTrade {
  transactionHash: string;
  conditionId: string;
  asset: string;
  side: string;
  size: number;
  price: number;
  timestamp: number;
  proxyWallet: string;
}

async function fetchTradesForMarket(
  conditionId: string,
  resume?: { offset: number; count: number }
): Promise<number> {
  let offset = resume?.offset ?? 0;
  let totalInserted = resume?.count ?? 0;
  const seen = new Set<string>();

  while (true) {
    const page = (await fetchJSON(`${DATA_HOST}/trades`, {
      market: conditionId,
      limit: String(TRADE_PAGE),
      offset: String(offset),
    })) as DataTrade[] | null;

    if (!page || page.length === 0) break;

    const batch = db.transaction(() => {
      let n = 0;
      for (const t of page) {
        const hash = t.transactionHash;
        if (!hash || seen.has(hash)) continue;
        seen.add(hash);
        try {
          upsertTrade.run(
            hash,
            t.conditionId || conditionId,
            String(t.asset || ""),
            String(t.side || "BUY").toUpperCase(),
            Number(t.size || 0),
            Number(t.price || 0),
            Number(t.timestamp || 0),
            t.proxyWallet || null
          );
          n++;
        } catch { /* dup */ }
      }
      return n;
    })();

    totalInserted += batch;

    if (page.length < TRADE_PAGE) break;
    offset += TRADE_PAGE;
  }

  // Mark as complete
  upsertFetchLog.run(conditionId, totalInserted, offset, 1, new Date().toISOString());
  return totalInserted;
}

// ── Concurrency limiter ──────────────────────────────────────────────────────

async function runConcurrent<T>(
  items: T[],
  limit: number,
  fn: (item: T) => Promise<void>
): Promise<void> {
  const queue = [...items];
  const running = new Set<Promise<void>>();

  async function worker() {
    while (queue.length > 0) {
      const item = queue.shift()!;
      const p = fn(item).then(() => running.delete(p));
      running.add(p);
      if (running.size >= limit) await Promise.race(running);
    }
  }

  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, () => worker()));
}

// ── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  const resume = process.argv.includes("--resume");
  const start = performance.now();

  // 1. Discover all hourly updown events
  const events = await discoverEvents();

  // 2. Upsert events and markets into SQLite
  const now = new Date().toISOString();
  let newMarkets = 0;

  const marketTasks: Array<{ conditionId: string; eventId: string }> = [];

  for (const e of events) {
    const asset = extractAsset(e.tags || []);
    insertEvent.run(
      e.id, e.title, e.slug, e.startDate, e.endDate,
      asset, JSON.stringify(e.tags), now
    );

    for (const m of e.markets || []) {
      let outcomes: string[];
      try { outcomes = JSON.parse(m.outcomes); } catch { outcomes = []; }
      let tokenIds: string[];
      try { tokenIds = JSON.parse(m.clobTokenIds); } catch { tokenIds = []; }

      const before = db.query("SELECT 1 FROM markets WHERE condition_id = ?").get(m.conditionId);
      insertMarket.run(
        m.conditionId, e.id, m.slug, m.question,
        JSON.stringify(outcomes), JSON.stringify(tokenIds),
        m.endDate, m.active ? 1 : 0, m.closed ? 1 : 0, now
      );
      if (!before) newMarkets++;

      // Check if we already fetched this market
      const log = getFetchLog.get(m.conditionId) as any;
      if (resume && log?.complete) continue;

      marketTasks.push({ conditionId: m.conditionId, eventId: e.id });
    }
  }

  console.log(`📦 ${events.length} events, ${newMarkets} new markets, ${marketTasks.length} to fetch trades`);

  // 3. Fetch trades for all markets
  let fetchedCount = 0;
  let totalTrades = 0;

  await runConcurrent(marketTasks, CONCURRENCY, async (task) => {
    const log = getFetchLog.get(task.conditionId) as any;
    const resumeData = resume && log
      ? { offset: log.last_offset ?? 0, count: log.total_trades ?? 0 }
      : undefined;

    const n = await fetchTradesForMarket(task.conditionId, resumeData);
    totalTrades += n;
    fetchedCount++;
    if (fetchedCount % 20 === 0 || fetchedCount === marketTasks.length) {
      process.stdout.write(
        `\r  📥 ${fetchedCount}/${marketTasks.length} markets  ${totalTrades.toLocaleString()} trades`
      );
    }
  });

  console.log(`\n\n🎉 Done in ${((performance.now() - start) / 1000).toFixed(1)}s`);
  console.log(`   Markets: ${marketTasks.length}`);
  console.log(`   Trades:  ${totalTrades.toLocaleString()}`);
  console.log(`   DB:      ${DB_PATH}`);

  // Print asset summary
  const summary = db.query(`
    SELECT m.asset_type, COUNT(DISTINCT mk.condition_id) as markets, COUNT(t.tx_hash) as trades
    FROM events m
    LEFT JOIN markets mk ON mk.event_id = m.id
    LEFT JOIN trades t ON t.condition_id = mk.condition_id
    GROUP BY m.asset_type
    ORDER BY trades DESC
  `).all() as any[];

  if (summary.length) {
    console.log("\n  Asset          Markets   Trades");
    console.log("  ─────────────  ────────  ───────");
    for (const r of summary) {
      console.log(
        `  ${(r.asset_type || "unknown").padEnd(14)} ${String(r.markets).padStart(7)}  ${String(r.trades).padStart(7)}`
      );
    }
  }

  db.close();
}

main().catch((e) => {
  console.error("Fatal:", e);
  process.exit(1);
});
