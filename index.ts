import { createPublicClient } from "@polymarket/client";

const client = createPublicClient();

const firstSlug = "bitcoin-up-or-down-june-19-12am-et";

function createSlugGenerator(start: Date) {
  let current = new Date(start);
  let hasReachedFirstSlug = false;

  return () => {
    const months = [
      "january", "february", "march", "april", "may", "june",
      "july", "august", "september", "october", "november", "december"
    ];

    const month = months[current.getUTCMonth()];
    const day = current.getUTCDate();

    let hour = current.getUTCHours();
    const ampm = hour >= 12 ? "pm" : "am";
    hour = hour % 12;
    if (hour === 0) hour = 12;

    const slugWithoutYear = `bitcoin-up-or-down-${month}-${day}-${hour}${ampm}-et`;

    if (slugWithoutYear === firstSlug) {
      hasReachedFirstSlug = true;
    }

    const slug = hasReachedFirstSlug
      ? `bitcoin-up-or-down-${month}-${day}-${hour}${ampm}-${current.getUTCFullYear()}-et`
      : slugWithoutYear;

    // Move back one hour for the next call
    current.setUTCHours(current.getUTCHours() - 1);

    return {
      slug,
      time: current.getTime()/1000
    };
  };
}

const nextSlug = createSlugGenerator(new Date("2026-07-13T23:00:00-04:00"));

const checkNextSlug = async () => {
  const {slug, time} = nextSlug();
  try {
    const res = await client.fetchMarket({
      slug
    });
    console.log(res);
    try {
      if (!res.outcomes || !res.outcomes.yes || !res.outcomes.no || !res.outcomes.yes.tokenId || !res.outcomes.no.tokenId) {
        console.error(`No 'yes' or 'no' outcome found for market with slug: ${slug}`);
        return false;
      }
      const crypto_price_history = await (await fetch(`https://polymarket.com/api/crypto/price-history?symbol=BTC&eventStartTime=${encodeURIComponent(new Date(time*1000).toISOString().replace('.000', ''))}&variant=hourly&endDate=${encodeURIComponent(new Date(new Date(time*1000).getTime() + 60 * 60 * 1000).toISOString().replace(".000", ""))}`)).json();
      console.log(crypto_price_history);

      if (!res.conditionId) {
        console.error(`No condition ID found for market with slug: ${slug}`);
        return false;
      }
      const conditionId: string = res.conditionId;
      const yesTokenId = res.outcomes.yes.tokenId;
      const noTokenId = res.outcomes.no.tokenId;

      const allTrades = [];
      const paginator = await client.listTrades({ market: [conditionId], pageSize: 100 });
      for await (const page of paginator) {
        allTrades.push(...page.items);
      }

      const yes_trades = allTrades
        .filter(t => t.tokenId === yesTokenId && t.timestamp != null)
        .sort((a, b) => a.timestamp! - b.timestamp!);
      const no_trades = allTrades
        .filter(t => t.tokenId === noTokenId && t.timestamp != null)
        .sort((a, b) => a.timestamp! - b.timestamp!);

      console.log("yes tokenId:", yesTokenId);
      console.log("yes trades:", yes_trades);
      console.log("no tokenId:", noTokenId);
      console.log("no trades:", no_trades);
    } catch (error) {
      console.error(`Error fetching market history for slug: ${slug}`, error);
      return false;
    }
  } catch (error) {
    console.error(`Error fetching market for slug: ${slug}`, error);
    return false;
  }
  return true;
};
// while (await checkNextSlug()) {}
await checkNextSlug();