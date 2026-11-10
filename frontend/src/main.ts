import "./style.css";
import { loadCountry, loadMeta, MAX_AGE_MS, type MetaResult } from "./data";
import { computeStats, escapeHtml, formatPrice, FUEL_LABELS, priceColor, scale, unit } from "./format";
import { PriceMap, rowKey } from "./map";
import { CountryIndex } from "./query";
import type { CountryMeta, FuelCategory, MapData, MapRow, ServiceMode } from "./types";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const countriesBox = $<HTMLDetailsElement>("countries");
const countriesSummary = $<HTMLElement>("countries-summary");
const countriesMenu = $<HTMLDivElement>("countries-menu");
const fuelSel = $<HTMLSelectElement>("fuel");
const serviceBox = $<HTMLDivElement>("service");
const statusEl = $<HTMLSpanElement>("status");
const refreshBtn = $<HTMLButtonElement>("refresh");
const cheapestEl = $<HTMLOListElement>("cheapest");
const legendEl = $<HTMLDivElement>("legend");
const panel = $<HTMLElement>("panel");

const FUEL_ORDER = Object.keys(FUEL_LABELS) as FuelCategory[];
/** How often to check, while the app stays open, whether the data got older than MAX_AGE_MS. */
const STALENESS_CHECK_MS = 10 * 60_000;

let countries: CountryMeta[] = [];
let metaInfo: MetaResult | null = null;
let current: MapData | null = null;
let loadSeq = 0;
/** Loaded country data, kept per version (hash) so toggling countries is instant. */
const indexes = new Map<string, { hash: string | null; index: CountryIndex; outdated: boolean }>();

const priceMap = new PriceMap(
  $("map"),
  (country, id) => indexes.get(country)?.index.station(id) ?? null,
  panel,
);

// -- state <-> URL -------------------------------------------------------------

interface State {
  countries: string[];
  fuel: FuelCategory;
  service: ServiceMode;
}

const params = new URLSearchParams(location.search);
const state: State = {
  countries: (params.get("country") ?? "").split(",").filter(Boolean),
  fuel: (params.get("fuel") as FuelCategory) ?? "diesel",
  service: params.get("service") === "attended" ? "attended" : "self",
};

/** Initial map position from `?at=lat,lon,zoom`, if present and valid. */
function initialView(): { center: [number, number]; zoom: number } | null {
  const [lat, lon, zoom] = (params.get("at") ?? "").split(",").map(Number);
  if ([lat, lon, zoom].some((n) => !Number.isFinite(n))) return null;
  return { center: [lat, lon], zoom };
}

function saveState(): void {
  const c = priceMap.map.getCenter();
  const at = `${c.lat.toFixed(4)},${c.lng.toFixed(4)},${priceMap.map.getZoom()}`;
  const p = new URLSearchParams({
    country: state.countries.join(","),
    fuel: state.fuel,
    service: state.service,
    at,
  });
  // URLSearchParams encodes "," as %2C; keep the URL readable.
  history.replaceState(null, "", `?${p.toString().replace(/%2C/g, ",")}`);
}

const selected = (): CountryMeta[] => countries.filter((c) => state.countries.includes(c.code));
const available = (c: CountryMeta) => Boolean(c.file) || indexes.has(c.code);

// -- controls ------------------------------------------------------------------

/** Default country from the browser locale (region first, then language), else the first one. */
function guessCountry(): string {
  const usable = countries.filter(available);
  const codes = new Set(usable.map((c) => c.code));
  const langToCountry: Record<string, string> = { sl: "si", en: "gb", da: "dk", el: "gr", cs: "cz" };
  for (const tag of navigator.languages ?? [navigator.language]) {
    const [lang, region] = tag.toLowerCase().split("-");
    if (region && codes.has(region)) return region;
    const fromLang = langToCountry[lang] ?? lang;
    if (codes.has(fromLang)) return fromLang;
  }
  return usable[0]?.code ?? countries[0]?.code ?? "";
}

function renderCountries(): void {
  const known = new Set(countries.map((c) => c.code));
  state.countries = state.countries.filter((c) => known.has(c));
  if (!state.countries.length) state.countries = [guessCountry()];
  countriesMenu.innerHTML =
    countries
      .map((c) => {
        const ok = available(c);
        const note = !ok ? "unavailable" : c.station_count.toLocaleString();
        return `<label class="${ok ? "" : "unavailable"}" title="${ok ? "" : escapeHtml(c.error ?? "")}">
          <input type="checkbox" value="${c.code}" ${state.countries.includes(c.code) ? "checked" : ""} ${ok ? "" : "disabled"}>
          ${escapeHtml(c.name)}<small>${note}</small></label>`;
      })
      .join("") + `<div class="menu-actions"><button type="button" data-action="all">All</button></div>`;
  renderCountriesSummary();
}

function renderCountriesSummary(): void {
  const sel = selected();
  const usable = countries.filter(available);
  countriesSummary.textContent =
    sel.length === usable.length && usable.length > 1
      ? "All countries"
      : sel.length <= 2
        ? sel.map((c) => c.name).join(", ")
        : `${sel.length} countries`;
  // Never allow deselecting the last country.
  for (const box of countriesMenu.querySelectorAll<HTMLInputElement>("input")) {
    const c = countries.find((x) => x.code === box.value);
    box.disabled = !c || !available(c) || (sel.length === 1 && box.checked);
  }
}

function renderControls(): void {
  const sel = selected();
  const cats = new Set(sel.flatMap((c) => c.categories));
  let fuels = FUEL_ORDER.filter((f) => cats.has(f));
  if (!fuels.length) fuels = ["petrol", "diesel"];
  if (!fuels.includes(state.fuel)) state.fuel = fuels.includes("diesel") ? "diesel" : fuels[0];
  fuelSel.innerHTML = fuels.map((f) => `<option value="${f}">${FUEL_LABELS[f]}</option>`).join("");
  fuelSel.value = state.fuel;
  serviceBox.hidden = !sel.some((c) => c.has_service_modes);
  for (const b of serviceBox.querySelectorAll<HTMLButtonElement>("button")) {
    b.setAttribute("aria-pressed", String(b.dataset.value === state.service));
  }
}

function setStatus(text: string, kind: "" | "warn" | "error" = ""): void {
  statusEl.textContent = text;
  statusEl.className = `status ${kind}`;
}

function ago(ms: number): string {
  const min = Math.round((Date.now() - ms) / 60_000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  const h = Math.round(min / 60);
  return h < 48 ? `${h} h ago` : `${Math.round(h / 24)} days ago`;
}

// -- data ----------------------------------------------------------------------

async function getIndex(c: CountryMeta): Promise<{ index: CountryIndex; outdated: boolean }> {
  const have = indexes.get(c.code);
  if (have && have.hash === c.hash) return have;
  const { data, outdated } = await loadCountry(c);
  const entry = { hash: outdated ? (have?.hash ?? null) : c.hash, index: new CountryIndex(c, data), outdated };
  indexes.set(c.code, entry);
  return entry;
}

/** Load every selected country (from the local cache when possible) and merge them into one layer. */
async function loadStations(opts: { fit?: boolean } = {}): Promise<void> {
  const sel = selected();
  if (!sel.length) return;
  const seq = ++loadSeq;
  if (sel.some((c) => indexes.get(c.code)?.hash !== c.hash)) setStatus("Loading stations…");

  const results = await Promise.allSettled(sel.map(getIndex));
  if (seq !== loadSeq) return; // a newer load started meanwhile

  const rows: MapRow[] = [];
  const dates: string[] = [];
  const warnings: string[] = [];
  const errors: string[] = [];
  results.forEach((res, i) => {
    const c = sel[i];
    if (res.status === "rejected") {
      errors.push(`${c.name}: ${res.reason instanceof Error ? res.reason.message : res.reason}`);
      return;
    }
    rows.push(...res.value.index.rows(state.fuel, state.service));
    const date = c.data_date ? new Date(c.data_date).toLocaleDateString() : "unknown date";
    dates.push(sel.length > 1 ? `${c.name} ${date}` : `data of ${date}`);
    if (res.value.outdated) warnings.push(`${c.name}: using saved data, download failed`);
    else if (c.stale) warnings.push(`${c.name}: source unreachable at last update`);
  });

  current = { fuel: state.fuel, service: state.service, rows, stats: computeStats(rows.map((r) => r.price)) };
  priceMap.setData(current);
  if (opts.fit) priceMap.fitToData();
  renderLegend();
  renderCheapest();

  const parts = [`${rows.length.toLocaleString()} stations`, ...dates];
  if (metaInfo) parts.push(metaInfo.offline ? `⚠ offline, saved ${ago(metaInfo.checkedAt)}` : `checked ${ago(metaInfo.checkedAt)}`);
  parts.push(...warnings.map((w) => `⚠ ${w}`), ...errors.map((e) => `failed: ${e}`));
  setStatus(parts.join(" · "), errors.length ? "error" : warnings.length || metaInfo?.offline ? "warn" : "");
}

/** Re-check meta.json (always when forced, otherwise only if older than MAX_AGE_MS) and reload changed data. */
async function refresh(force: boolean): Promise<void> {
  if (!force && metaInfo && Date.now() - metaInfo.checkedAt < MAX_AGE_MS) return;
  refreshBtn.disabled = true;
  try {
    metaInfo = await loadMeta({ force: true });
    countries = metaInfo.meta.countries;
    renderCountries();
    renderControls();
    await loadStations();
  } catch (err) {
    setStatus(`Update failed: ${err}`, "error");
  } finally {
    refreshBtn.disabled = false;
  }
}

// -- side panel ----------------------------------------------------------------

function renderCheapest(): void {
  if (!current) return;
  const rows = priceMap.cheapestInView(10);
  if (!rows.length) {
    cheapestEl.innerHTML = `<li class="empty">No stations in view</li>`;
    return;
  }
  const multi = state.countries.length > 1;
  cheapestEl.innerHTML = rows
    .map((r) => {
      const color = priceColor(scale(r.price, current!.stats));
      const tag = multi ? `<em class="cc">${r.country.toUpperCase()}</em> ` : "";
      return `<li><button type="button" data-key="${escapeHtml(rowKey(r))}">
        <b style="color:${color}">${formatPrice(r.price, r.currency)}</b>
        <span class="info"><span class="title">${tag}${escapeHtml(r.name)}</span><small>${escapeHtml(r.brand)} · ${escapeHtml(r.product)}</small></span>
      </button></li>`;
    })
    .join("");
}

function renderLegend(): void {
  const s = current?.stats;
  if (!s || !current) {
    legendEl.innerHTML = "";
    return;
  }
  const currencies = [...new Set(current.rows.map((r) => r.currency))];
  const f = (v: number) => formatPrice(v, currencies[0]);
  const withModes = selected().filter((c) => c.has_service_modes);
  const service = withModes.length
    ? ` · ${current.service}${withModes.length < state.countries.length ? ` (${withModes.map((c) => c.code.toUpperCase()).join(", ")})` : ""}`
    : "";
  const mixed = currencies.length > 1 ? `<p>⚠ Mixed currencies (${currencies.join(", ")}): colors are not comparable.</p>` : "";
  legendEl.innerHTML = `
    <div class="bar"></div>
    <div class="labels"><span>≤ ${f(s.p10)}</span><span>${f(s.median)}</span><span>≥ ${f(s.p90)}</span></div>
    <p>${FUEL_LABELS[current.fuel]}${service}, price ${unit(current.fuel)}. Range ${f(s.min)} – ${f(s.max)}</p>${mixed}`;
}

// -- events --------------------------------------------------------------------

countriesMenu.addEventListener("change", (e) => {
  const box = e.target as HTMLInputElement;
  const set = new Set(state.countries);
  if (box.checked) set.add(box.value);
  else set.delete(box.value);
  // Keep a stable (alphabetical) order for the URL.
  state.countries = countries.map((c) => c.code).filter((c) => set.has(c));
  renderCountriesSummary();
  renderControls();
  saveState();
  void loadStations({ fit: box.checked });
});

countriesMenu.addEventListener("click", (e) => {
  if ((e.target as HTMLElement).closest("button")?.dataset.action !== "all") return;
  state.countries = countries.filter(available).map((c) => c.code);
  renderCountries();
  renderControls();
  saveState();
  void loadStations({ fit: true });
});

// Close the country menu when clicking elsewhere or pressing Escape.
document.addEventListener("click", (e) => {
  if (countriesBox.open && !countriesBox.contains(e.target as Node)) countriesBox.open = false;
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") countriesBox.open = false;
});

fuelSel.addEventListener("change", () => {
  state.fuel = fuelSel.value as FuelCategory;
  saveState();
  void loadStations();
});

serviceBox.addEventListener("click", (e) => {
  const value = (e.target as HTMLElement).closest("button")?.dataset.value as ServiceMode | undefined;
  if (!value || value === state.service) return;
  state.service = value;
  renderControls();
  saveState();
  void loadStations();
});

refreshBtn.addEventListener("click", () => void refresh(true));
$("locate").addEventListener("click", () => priceMap.locate());

cheapestEl.addEventListener("click", (e) => {
  const key = (e.target as HTMLElement).closest<HTMLButtonElement>("button[data-key]")?.dataset.key;
  if (key) priceMap.focus(key);
});

$("panel-toggle").addEventListener("click", (e) => {
  const collapsed = panel.classList.toggle("collapsed");
  (e.currentTarget as HTMLElement).setAttribute("aria-expanded", String(!collapsed));
});

priceMap.map.on("moveend", () => {
  renderCheapest();
  saveState();
});

// While the app stays open (or comes back to the foreground), refresh once the data is older than 4 h.
window.setInterval(() => void refresh(false), STALENESS_CHECK_MS);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") void refresh(false);
});

// -- boot ----------------------------------------------------------------------

async function boot(): Promise<void> {
  try {
    // Uses the saved copy when it is less than 4 h old; otherwise checks for new data.
    metaInfo = await loadMeta();
  } catch (err) {
    setStatus(`Cannot load data (offline and nothing saved yet): ${err}`, "error");
    return;
  }
  countries = metaInfo.meta.countries;
  if (!countries.length) {
    setStatus("No countries in the published data", "error");
    return;
  }
  renderCountries();
  renderControls();
  const view = initialView();
  const first = selected()[0] ?? countries[0];
  priceMap.setView(view?.center ?? first.center, view?.zoom ?? first.zoom);
  saveState();
  // Without an explicit position, frame all selected countries once loaded.
  await loadStations({ fit: !view && state.countries.length > 1 });
}

void boot();
