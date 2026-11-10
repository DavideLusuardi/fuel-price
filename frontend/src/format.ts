import type { FuelCategory, PriceStats } from "./types";

export const FUEL_LABELS: Record<FuelCategory, string> = {
  petrol: "Petrol",
  diesel: "Diesel",
  premium_petrol: "Premium petrol",
  premium_diesel: "Premium diesel",
  lpg: "LPG",
  cng: "CNG (methane)",
  lng: "LNG",
  hvo: "HVO",
  other: "Other",
};

/** Fuels priced per kg rather than per litre. */
const PER_KG: ReadonlySet<FuelCategory> = new Set(["cng", "lng"]);

export function unit(fuel: FuelCategory): string {
  return PER_KG.has(fuel) ? "/kg" : "/l";
}

export function formatPrice(value: number, currency: string): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    minimumFractionDigits: 3,
    maximumFractionDigits: 3,
  }).format(value);
}

/** Short price for markers, e.g. "1.849". */
export function shortPrice(value: number): string {
  return value.toFixed(3);
}

export function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!,
  );
}

/** Position of a price on the [p10, p90] scale, clamped to [0, 1]. */
export function scale(value: number, stats: PriceStats | null): number {
  if (!stats || stats.p90 <= stats.p10) return 0.5;
  return Math.min(1, Math.max(0, (value - stats.p10) / (stats.p90 - stats.p10)));
}

/** Green (cheap) → amber → red (expensive). */
export function priceColor(t: number): string {
  const hue = 130 - 130 * t;
  return `hsl(${hue.toFixed(0)} 70% 38%)`;
}

export function relativeAge(when: Date | null): { text: string; old: boolean } {
  if (!when) return { text: "–", old: false };
  const ms = Date.now() - when.getTime();
  const days = Math.floor(ms / 86_400_000);
  const text = days <= 0 ? "today" : days === 1 ? "yesterday" : `${days} days ago`;
  return { text, old: days > 7 };
}

/** min/max/median and 10th/90th percentiles (linear interpolation, like Python's "inclusive"). */
export function computeStats(values: number[]): PriceStats | null {
  if (!values.length) return null;
  const v = [...values].sort((a, b) => a - b);
  const q = (p: number) => {
    const pos = (v.length - 1) * p;
    const lo = Math.floor(pos);
    const hi = Math.min(lo + 1, v.length - 1);
    return v[lo] + (v[hi] - v[lo]) * (pos - lo);
  };
  const r = (x: number) => Math.round(x * 1000) / 1000;
  return { min: v[0], max: v[v.length - 1], p10: r(q(0.1)), p90: r(q(0.9)), median: r(q(0.5)) };
}
