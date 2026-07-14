import { createPublicClient } from "@polymarket/client";

const client = createPublicClient();

function createSlugGenerator(start: Date) {
  let current = new Date(start);

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

    const slug = `bitcoin-up-or-down-${month}-${day}-${hour}${ampm}-et`;

    // Move back one hour for the next call
    current.setUTCHours(current.getUTCHours() - 1);

    return slug;
  };
}

const nextSlug = createSlugGenerator(new Date("2026-07-13T23:00:00-04:00"));

const checkNextSlug = async () => {
  const slug = nextSlug();
  const res = await client.fetchMarket({
    slug
  })
  console.log(res);
};
checkNextSlug();