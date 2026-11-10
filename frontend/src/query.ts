/** In-browser queries over one country's data file (what the API server used to do). */
import type { CountryFile, CountryMeta, FuelCategory, MapRow, ServiceMode, Station, StationTuple } from "./types";

type Mode = "self" | "attended" | "any";

export class CountryIndex {
  private byId = new Map<string, StationTuple>();
  private cache = new Map<string, MapRow[]>();

  constructor(
    readonly meta: CountryMeta,
    private file: CountryFile,
    /** Prices last updated before this (unix seconds) are ignored on the map. */
    private oldestAllowed: number | null = meta.max_price_age_days == null
      ? null
      : Date.now() / 1000 - meta.max_price_age_days * 86400,
  ) {
    for (const s of file.stations) this.byId.set(s[0], s);
  }

  /** Cheapest price per station for a fuel; mode is ignored for countries without service modes. */
  rows(fuel: FuelCategory, service: ServiceMode): MapRow[] {
    const mode: Mode = this.meta.has_service_modes ? service : "any";
    const key = `${fuel}|${mode}`;
    const hit = this.cache.get(key);
    if (hit) return hit;

    const products = this.file.products;
    const rows: MapRow[] = [];
    for (const [id, name, brand, , , , , lat, lon, prices] of this.file.stations) {
      let best: { price: number; product: string } | null = null;
      for (const [pi, price, self, updated, , suspect] of prices) {
        if (suspect) continue;
        if (products[pi][1] !== fuel) continue;
        if (mode !== "any" && self !== (mode === "self" ? 1 : 0)) continue;
        if (this.oldestAllowed !== null && updated !== null && updated < this.oldestAllowed) continue;
        if (!best || price < best.price) best = { price, product: products[pi][0] };
      }
      if (best) {
        rows.push({ country: this.meta.code, currency: this.meta.currency, id, lat, lon, name, brand, ...best });
      }
    }
    this.cache.set(key, rows);
    return rows;
  }

  station(id: string): Station | null {
    const s = this.byId.get(id);
    if (!s) return null;
    const [sid, name, brand, operator, address, city, province, lat, lon, prices] = s;
    const date = (t: number | null) => (t === null ? null : new Date(t * 1000));
    return {
      id: sid, name, brand, operator, address, city, province, lat, lon,
      prices: prices.map(([pi, price, self, updated, since, suspect]) => ({
        product: this.file.products[pi][0],
        category: this.file.products[pi][1],
        price,
        self_service: self === null ? null : self === 1,
        updated_at: date(updated),
        seen_since: date(since),
        suspect: suspect === 1,
      })),
    };
  }
}
