export type FuelCategory =
  | "petrol" | "diesel" | "premium_petrol" | "premium_diesel"
  | "lpg" | "cng" | "lng" | "hvo" | "other";

export type ServiceMode = "self" | "attended";

// -- static data files (written by `fuelprice-build`, see backend/src/fuelprice/export.py) --

export interface CountryMeta {
  code: string;
  name: string;
  currency: string;
  center: [number, number];
  zoom: number;
  has_service_modes: boolean;
  max_price_age_days: number | null;
  /** null when the source has never been fetched successfully. */
  file: string | null;
  hash: string | null;
  bytes?: number;
  stale: boolean;
  error: string | null;
  station_count: number;
  categories: FuelCategory[];
  data_date: string | null;
  fetched_at: string | null;
}

export interface Meta {
  v: 1;
  generated_at: string;
  countries: CountryMeta[];
}

/** [product_index, price, self (1 | 0 | null), updated_at (unix s) | null, seen_since (unix s) | null] */
export type PriceTuple = [number, number, 0 | 1 | null, number | null, number | null];

/** [id, name, brand, operator, address, city, province, lat, lon, prices] */
export type StationTuple = [string, string, string, string, string, string, string, number, number, PriceTuple[]];

export interface CountryFile {
  v: 1;
  data_date: string | null;
  fetched_at: string;
  products: [string, FuelCategory][];
  stations: StationTuple[];
}

// -- app-level shapes -----------------------------------------------------------

export interface PriceStats {
  min: number;
  max: number;
  p10: number;
  p90: number;
  median: number;
}

/** Cheapest matching price of one station, as shown on the map. */
export interface MapRow {
  country: string;
  currency: string;
  id: string;
  lat: number;
  lon: number;
  name: string;
  brand: string;
  price: number;
  product: string;
}

export interface MapData {
  fuel: FuelCategory;
  service: ServiceMode;
  rows: MapRow[];
  stats: PriceStats | null;
}

export interface Price {
  category: FuelCategory;
  product: string;
  price: number;
  self_service: boolean | null;
  /** When the source says the price was set. */
  updated_at: Date | null;
  /** For sources without timestamps: since when the price has been observed unchanged. */
  seen_since: Date | null;
}

export interface Station {
  id: string;
  name: string;
  brand: string;
  operator: string;
  address: string;
  city: string;
  province: string;
  lat: number;
  lon: number;
  prices: Price[];
}
