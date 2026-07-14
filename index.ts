import { createPublicClient } from "@polymarket/client";
import { mkdirSync } from "fs";

const client = createPublicClient();
const et = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  month: "long",
  day: "numeric",
  hour: "numeric",
  hour12: true,
});

const firstSlugDate = new Date("2025-06-19T04:00:00Z"); // June 19, 2025 12am ET

function slugFromDate(d: Date): string {
  const parts = et.formatToParts(d);
  const month = parts.find((p) => p.type === "month")!.value.toLowerCase();
  const day = parts.find((p) => p.type === "day")!.value;
  const hour = parts.find((p) => p.type === "hour")!.value;
  const ampm = parts.find((p) => p.type === "dayPeriod")!.value.toLowerCase();
  return `bitcoin-up-or-down-${month}-${day}-${hour}${ampm}-et`;
}

function generateSlugs(start: Date): { slug: string; time: number }[] {
  const results: { slug: string; time: number }[] = [];
  let current = new Date(start);

  while (current >= firstSlugDate) {
    results.push({ slug: slugFromDate(current), time: current.getTime() / 1000 });
    current.setUTCHours(current.getUTCHours() - 1);
  }

  return results;
}

function cryptoUrl(time: number): string {
  const start = new Date(time * 1000).toISOString().replace(".000", "");
  const end = new Date(time * 1000 + 3600 * 1000).toISOString().replace(".000", "");
  return `https://polymarket.com/api/crypto/price-history?symbol=BTC&eventStartTime=${encodeURIComponent(start)}&variant=hourly&endDate=${encodeURIComponent(end)}`;
}

const tradeSem = new (class {
  max = 4; pending = 0; queue: Array<() => void> = [];
  async acquire() {
    if (this.pending < this.max) { this.pending++; return; }
    await new Promise<void>((r) => this.queue.push(r));
    this.pending++;
  }
  release() {
    this.pending--;
    const next = this.queue.shift();
    if (next) { this.pending++; next(); }
  }
})();

async function fetchAllTrades(conditionId: string, signal: AbortSignal): Promise<any[]> {
  await tradeSem.acquire();
  try {
    const result = await Promise.race([
      fetchTradesPages(conditionId, signal),
      new Promise<any[]>((_, reject) =>
        setTimeout(() => reject(new Error("trade sem timeout")), 50000)
      ),
    ]);
    return result;
  } finally {
    tradeSem.release();
  }
}

async function fetchTradesPages(conditionId: string, signal: AbortSignal): Promise<any[]> {
  const allTrades: any[] = [];
  const paginator = await client.listTrades({ market: [conditionId], pageSize: 100 });
  let pages = 0;
  for await (const page of paginator) {
    allTrades.push(...page.items);
    if (signal.aborted || ++pages >= 10) break;
  }
  return allTrades;
}

async function downloadOne(slug: string, time: number): Promise<any> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30000);
  const signal = controller.signal;

  try {
    const [market, crypto_price_history] = await Promise.all([
      client.fetchMarket({ slug }),
      fetch(cryptoUrl(time), { signal }).then((r) => r.json()),
    ]);

    if (
      !market.conditionId ||
      !market.outcomes?.yes?.tokenId ||
      !market.outcomes?.no?.tokenId
    ) {
      return null;
    }

    const conditionId: string = market.conditionId;
    const yesTokenId = market.outcomes.yes.tokenId;
    const noTokenId = market.outcomes.no.tokenId;

    let yes_trades: any[] = [];
    let no_trades: any[] = [];
    try {
      const allTrades = await fetchAllTrades(conditionId, signal);
      yes_trades = allTrades
        .filter((t: any) => t.tokenId === yesTokenId && t.timestamp != null)
        .sort((a: any, b: any) => a.timestamp - b.timestamp);
      no_trades = allTrades
        .filter((t: any) => t.tokenId === noTokenId && t.timestamp != null)
        .sort((a: any, b: any) => a.timestamp - b.timestamp);
    } catch (e) {
      process.stderr.write(`\x1b[33m⚠\x1b[0m trades failed for ${slug}: ${(e as any)?.message ?? e}\n`);
    }

    return { slug, time, market, crypto_price_history, yes_trades, no_trades };
  } finally {
    clearTimeout(timer);
  }
}

async function downloadWithRetry(slug: string, time: number, retries = 3): Promise<any> {
  for (let i = 0; i < retries; i++) {
    try {
      const result = await Promise.race([
        downloadOne(slug, time),
        new Promise<any>((_, reject) =>
          setTimeout(() => reject(new Error("timeout")), 120000)
        ),
      ]);
      return result;
    } catch (e) {
      if (i === retries - 1) throw e;
      await new Promise((r) => setTimeout(r, 1000 * (i + 1)));
    }
  }
}

const BAR_WIDTH = 50;

function pacmanBar(current: number, total: number, label: string) {
  const pct = total > 0 ? Math.round((current / total) * 100) : 0;
  const filled = total > 0 ? Math.round((current / total) * BAR_WIDTH) : 0;

  let bar = "";
  for (let i = 0; i < BAR_WIDTH; i++) {
    if (i < filled) {
      const pos = i / BAR_WIDTH;
      if (pos < 0.33) bar += "\x1b[32m#\x1b[0m";
      else if (pos < 0.66) bar += "\x1b[33m#\x1b[0m";
      else bar += "\x1b[31m#\x1b[0m";
    } else {
      bar += "\x1b[2m.\x1b[0m";
    }
  }

  const slug = label.length > 55 ? label.slice(0, 52) + "..." : label;
  process.stderr.write(
    `\r\x1b[K[\x1b[36m>\x1b[0m] ${bar} ${String(pct).padStart(3)}%  (${current}/${total}) ${slug}`
  );
}

async function main() {
  const startTime = new Date();
  // Round down to current hour in ET
  startTime.setMinutes(0, 0, 0);
  const slugs = generateSlugs(startTime);
  const total = slugs.length;

  try {
    mkdirSync("data", { recursive: true });
  } catch {}

  const concurrency = 50;
  let done = 0;
  let noData = 0;
  let errorSlugs: string[] = [];

  process.stderr.write(`\x1b[36m::\x1b[0m Snapshotting ${total} BTC hourly markets\n`);

  for (let i = 0; i < slugs.length; i += concurrency) {
    const batch = slugs.slice(i, i + concurrency);

    const results = await Promise.allSettled(
      batch.map(async ({ slug, time }) => {
        const data = await downloadWithRetry(slug, time);
        if (data) {
          await Bun.write(`data/${slug}.json`, JSON.stringify(data, null, 2));
        }
        return { slug: slug, ok: data !== null };
      })
    );

    for (let j = 0; j < results.length; j++) {
      const r = results[j]!;
      if (r.status === "fulfilled") {
        done++;
        if (!r.value.ok) noData++;
        pacmanBar(done, total, r.value.slug);
      } else {
        done++;
        errorSlugs.push(batch[j]!.slug);
      }
    }
  }

  // Retry errored slugs
  let retried = 0;
  for (const slug of errorSlugs) {
    if (slug === "unknown") { noData++; continue; }
    const entry = slugs.find((s) => s.slug === slug);
    if (!entry) { noData++; continue; }
    try {
      const data = await downloadWithRetry(entry.slug, entry.time, 5);
      if (data) {
        await Bun.write(`data/${entry.slug}.json`, JSON.stringify(data, null, 2));
        retried++;
        pacmanBar(done, total, entry.slug);
      } else {
        noData++;
      }
    } catch {
      noData++;
    }
  }

  process.stderr.write("\n");
  if (retried > 0) {
    process.stderr.write(`\x1b[33m::\x1b[0m ${retried} recovered on retry\n`);
  }
  if (noData > 0) {
    process.stderr.write(`\x1b[33m::\x1b[0m ${noData} markets had no data\n`);
  }
  process.stderr.write(`\x1b[32m::\x1b[0m Done — ${done - noData} markets saved to data/\n`);
}

await main();
