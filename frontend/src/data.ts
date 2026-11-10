/**
 * Loads the static data files and keeps them in IndexedDB.
 *
 * - meta.json is re-checked when the cached copy is older than {@link MAX_AGE_MS}
 *   (or when forced); otherwise the app starts from the local copy without any request.
 * - A country file is downloaded only when its hash in meta.json changes.
 * - When the network fails, the cached data is used and reported as such.
 */
import type { CountryFile, CountryMeta, Meta } from "./types";

export const MAX_AGE_MS = 4 * 60 * 60 * 1000;
const DATA_URL = "data/"; // relative to the page, works under any base path
const DB_NAME = "fuelprice";
const STORE = "kv";

interface CachedMeta {
  checkedAt: number;
  meta: Meta;
}

interface CachedCountry {
  hash: string;
  data: CountryFile;
}

// -- minimal IndexedDB key/value store ------------------------------------------

let dbPromise: Promise<IDBDatabase | null> | null = null;

function db(): Promise<IDBDatabase | null> {
  dbPromise ??= new Promise((resolve) => {
    try {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => req.result.createObjectStore(STORE);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null); // e.g. private mode: work without a cache
    } catch {
      resolve(null);
    }
  });
  return dbPromise;
}

async function idbGet<T>(key: string): Promise<T | undefined> {
  const d = await db();
  if (!d) return undefined;
  return new Promise((resolve) => {
    const req = d.transaction(STORE).objectStore(STORE).get(key);
    req.onsuccess = () => resolve(req.result as T | undefined);
    req.onerror = () => resolve(undefined);
  });
}

async function idbSet(key: string, value: unknown): Promise<void> {
  const d = await db();
  if (!d) return;
  await new Promise<void>((resolve) => {
    const tx = d.transaction(STORE, "readwrite");
    tx.objectStore(STORE).put(value, key);
    tx.oncomplete = () => resolve();
    tx.onerror = () => resolve(); // quota etc.: keep going without caching
  });
}

// -- public API ---------------------------------------------------------------------

export interface MetaResult {
  meta: Meta;
  /** When meta.json was last fetched from the network. */
  checkedAt: number;
  /** True when a refresh was due but the network request failed. */
  offline: boolean;
}

export async function loadMeta(opts: { force?: boolean } = {}): Promise<MetaResult> {
  const cached = await idbGet<CachedMeta>("meta");
  const fresh = cached && Date.now() - cached.checkedAt < MAX_AGE_MS;
  if (cached && fresh && !opts.force) return { ...cached, offline: false };
  try {
    const res = await fetch(`${DATA_URL}meta.json`, { cache: "no-store" });
    if (!res.ok) throw new Error(`meta.json: ${res.status}`);
    const meta = (await res.json()) as Meta;
    const entry: CachedMeta = { checkedAt: Date.now(), meta };
    await idbSet("meta", entry);
    return { ...entry, offline: false };
  } catch (err) {
    if (cached) return { ...cached, offline: true };
    throw err;
  }
}

export interface CountryResult {
  data: CountryFile;
  /** True when a newer version exists but could not be downloaded. */
  outdated: boolean;
}

/** Country data matching `meta.hash`, from the local cache when possible. */
export async function loadCountry(meta: CountryMeta): Promise<CountryResult> {
  const key = `country:${meta.code}`;
  const cached = await idbGet<CachedCountry>(key);
  if (cached && cached.hash === meta.hash) return { data: cached.data, outdated: false };
  if (!meta.file || !meta.hash) {
    if (cached) return { data: cached.data, outdated: true };
    throw new Error(meta.error ?? "no data published yet");
  }
  try {
    // The hash in the URL makes caches (browser, CDN) treat each version as a new file.
    const res = await fetch(`${DATA_URL}${meta.file}?v=${meta.hash}`);
    if (!res.ok) throw new Error(`${meta.file}: ${res.status}`);
    const data = (await res.json()) as CountryFile;
    await idbSet(key, { hash: meta.hash, data } satisfies CachedCountry);
    return { data, outdated: false };
  } catch (err) {
    if (cached) return { data: cached.data, outdated: true };
    throw err;
  }
}
