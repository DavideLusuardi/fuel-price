# Fuel price map

A web map of fuel stations showing the price of the selected fuel. Each country's data
source is a **plugin**. Five countries ship today:

| Country | Source | Stations | Notes |
|---|---|---|---|
| Italia (`it`) | MIMIT Osservaprezzi API (CSV open data as fallback) | ~21,600 | live, self/attended prices, estimated per-price dates |
| Slovenija (`si`) | goriva.si JSON API | ~540 | one price per fuel, no timestamps |
| Hrvatska (`hr`) | mzoe-gor.hr (Ministry of Economy), gzipped JSON | ~870 | one price per fuel, no timestamps |
| France (`fr`) | prix-carburants open data (Ministry of the Economy), zipped XML | ~9,400 | refreshed every ~10 min, exact per-price dates, no station names or brands |
| España (`es`) | Ministry for the Ecological Transition (MITECO) REST service, JSON | ~11,500 | refreshed every 30 min, one price per fuel, no timestamps |

There is no server. The app is a static site that reads pre-built data files:

```
 sources (one per country plugin)              GitHub Actions, every 2 h
        │                                     ┌──────────────────────────────┐
        └──────────────► fuelprice-build ────►│ data/meta.json, it.json, ... │
                         (Python plugins)     └──────────────┬───────────────┘
                                                             │ static hosting (GitHub Pages)
                                                             ▼
                                        browser: IndexedDB cache, refreshed when older than 4 h
```

- **`backend/`** (Python 3.12) holds the country plugins and the `fuelprice-build` command. It fetches every source, normalizes the data and writes compact JSON files (`export.py` describes the format). It is not a server: it only runs at build time.
- **`frontend/`** (Vite, TypeScript, Leaflet, markercluster) is the web app. Markers show the price, colored from green (cheap) to red, and clusters show the lowest price inside them. Several countries can be shown at once.

A build job is needed because the Italian and Slovenian sources don't send CORS headers (and the Italian API rate-limits). That means a browser can't read them directly, while it can read files published next to the app.

## How the app keeps data fresh

- Everything downloaded is saved in the browser's **IndexedDB**. A reopened app starts from the saved copy without waiting for the network.
- When the saved data is **older than 4 hours**, the app re-checks `meta.json`, which is small. It then downloads a country again only if that country's file has changed (`hash` in `meta.json`). Slovenia and Croatia often stay unchanged between builds, so those checks download nothing. Only the countries you select are downloaded.
- While the app stays open, it checks again every 10 minutes and whenever the tab comes back to the foreground. **↻ Update** forces a check.
- Offline, the app keeps using the saved data and says so ("⚠ offline, saved 5 h ago").

## Run locally

```bash
cd frontend
npm install
npm run data   # fetch all sources into frontend/public/data (needs uv; ~5 s)
npm run dev    # http://localhost:5173
```

`npm run build` produces a self-contained static site in `frontend/dist/`, data included, that any static file server can host.

## Deploy to GitHub Pages

`.github/workflows/deploy.yml` runs every 2 hours, on every push to `main`, and on demand. It runs the tests, fetches the data, builds the app and publishes it.

1. Push the repository to GitHub.
2. Under **Settings → Pages**, set **Source: GitHub Actions**.
3. Run the workflow once from the **Actions** tab, or push.

Notes:
- GitHub pauses scheduled workflows in repositories with no activity for 60 days. Re-enable the workflow from the Actions tab, or push a commit.
- If a source is down during a build, the previous published data for that country is republished and marked stale. The app shows a warning for it.

## Tests

```bash
cd backend && uv run pytest
```

## Price dates

- Prices that haven't been updated for more than `max_price_age` (7 days by default) are left out of the map and the rankings. They still appear in the station popup, marked as old.
- Prices that look wrong are left out of the map and the rankings too, and shown crossed out in the popup. The build compares each price with nearby stations selling the same fuel in the same service mode. A price is flagged if it is more than 12% below their median and no nearby station has about the same price (so real local price levels, like duty-free Livigno, are kept), or if it is more than twice the median (typos). CNG and LNG prices vary much more between stations, so for them the margin is 35% instead of 12%. A plugin can widen the 12% with `outlier_low` where real low prices are common: Spain uses 25% for its discount chains. The rules and thresholds are in `backend/src/fuelprice/core/outliers.py`. The build log shows how many prices were flagged per country.
- Slovenia and Croatia publish no per-price dates, so the build records them itself. Each price gets the time a build first saw it at its current value (`seen_since`), and the popup shows this as **"Unchanged since"**. This history builds up from the first deployment, so on day one every price shows that day. These observed dates don't remove prices from the map. Regulated prices often stay unchanged for weeks, so that wouldn't be a sign the price is outdated.

## Adding a country

1. Create a plugin by subclassing `fuelprice.core.CountryPlugin`:

   ```python
   # backend/src/fuelprice/plugins/france/__init__.py
   from datetime import UTC, datetime
   import httpx
   from fuelprice.core import CountryPlugin, Dataset, FuelCategory, Price, Station

   class FrancePlugin(CountryPlugin):
       code = "fr"
       name = "France"
       currency = "EUR"
       center = (46.6, 2.4)
       zoom = 6
       has_service_modes = False          # the source has a single price per fuel

       async def fetch(self, client: httpx.AsyncClient) -> Dataset:
           resp = await client.get("https://…", timeout=60)
           resp.raise_for_status()
           stations = [
               Station(id=..., name=..., lat=..., lon=..., prices=[
                   Price(category=FuelCategory.DIESEL, product="Gazole", price=1.79,
                         self_service=None, updated_at=...),
               ]),
           ]
           return Dataset(stations=stations, data_date=None, fetched_at=datetime.now(UTC))
   ```

2. Register it in `backend/pyproject.toml`, then run `uv sync`:

   ```toml
   [project.entry-points."fuelprice.countries"]
   it = "fuelprice.plugins.italy:ItalyPlugin"
   fr = "fuelprice.plugins.france:FrancePlugin"
   ```

The core and the frontend need no changes, and the next build publishes the new country. The country shows up in the selector together
with the fuel categories it actually has. A plugin can also live in its own pip package, as
long as it declares the same entry-point group.

Guidelines for plugins:
- Map product names to the shared `FuelCategory` values. Keep the original name in `Price.product`, because the UI shows it.
- Fetch independent requests concurrently (`asyncio.gather`), because the build runs all plugins together.
- Keep parsing in pure functions so it can be tested against fixture files. See `plugins/italy/parser.py` and `tests/test_italy_parser.py`.
- Raise an exception when a fetch fails. The build then republishes the previous data, marked stale.
- If the source has no per-price timestamps, leave `updated_at` empty. The build fills `seen_since` for those prices.

## Italy data notes

The plugin uses two official MIMIT sources and tries them in this order:

1. **Osservaprezzi API** (`carburanti.mise.gov.it/ospzApi`). `POST /search/area {"region": id}` for each of the 20 regions, one at a time with a 1.5 s pause, because parallel requests get `429 Too Many Requests`. A full fetch takes about 40 s. Prices are live, and this host is reachable from GitHub's servers.
   - The API gives one update date per station, not per price. Each price's date is estimated from its id, since ids grow over time; `plugins/italy/osservaprezzi.py` explains how. This removes prices that are months or years old, but about 2–3.5% of stations may still show a price that is 1–8 weeks old, usually lower than the current one.
   - Addresses come as one string (`street zip - CITY PR`) and are split. The operator name isn't available.
2. **Open-data CSVs** ([MIMIT open data](https://www.mimit.gov.it/it/open-data/elenco-dataset/carburanti-prezzi-praticati-e-anagrafica-degli-impianti)): two `|`-separated files published every morning with the prices as of 08:00 and an exact date for every price. These are used only when the API fails. `www.mimit.gov.it` refuses connections from GitHub's servers, so on GitHub this fallback works only through a proxy. Set `FUELPRICE_IT_CSV_BASE_URL` to a mirror or URL-rewriting proxy, for example in the workflow's `env`.
   - Some station names contain a stray `|`, and a few rows have no coordinates or placeholder prices such as `0.100`. The parser handles all of these.

About 50 branded product names, the same in both sources, are mapped to categories in `plugins/italy/fuels.py`. Names not listed there fall back to keyword rules.

## Slovenia data notes

- Source: `https://goriva.si/api/v1/search/?page=N` (25 stations per page, fetched concurrently) and `/api/v1/franchise/` for the brand names.
- Fuel codes map directly to categories (`95`, `dizel`, `98`, `100`, `dizel-premium`, `avtoplin-lpg`, `hvo`, `cng`, `lng`). `KOEL` is heating oil and is skipped.
- `0.001` is used as a placeholder for "not sold" and is filtered out.

## Croatia data notes

- Source: `https://webservis.mzoe-gor.hr/data.gz`, the file the official site loads. `mzoe-gor.hr/data.json` is an outdated copy. `Last-Modified` gives the data date.
- The category comes from `vrsta_goriva_id`. Petrol is categorized by octane only: 95 is `petrol` and 100 is `premium_petrol`, as in Slovenia. Premium-branded 95 (e.g. "Class Plus Premium", about 1.75 €) stays `petrol`, because it costs much less than 100-octane (about 2.14 €). Diesel has no grade in the source, so diesel brand names containing "premium", "V-Power", "G-Power" and similar move it to `premium_diesel`. Heating oil, agricultural "blue" diesel, bottled LPG, bio components and EV charging are dropped.
- Most rows have the `long` and `lat` fields swapped, so they are assigned by value range. A few coordinates use degree-minute notation (`45° 39.4112' N`), and some are empty or are a Google Maps link, which are skipped.
- A few stations still list prices in kuna from before the euro (2023). Any station with a road-fuel price above €4.50 is treated as stale and dropped.

## France data notes

- Source: `https://donnees.roulez-eco.fr/opendata/instantane`, the official "flux instantané" ([data.gouv.fr](https://www.data.gouv.fr/datasets/prix-des-carburants-en-france-flux-instantane-v2-amelioree), Licence Ouverte). It is a ZIP with one ISO-8859-1 XML file, refreshed about every 10 minutes. Stations are required by law to report every price change (arrêté of 12 December 2006).
- Each price has its own update time (`maj`, Paris local time). Prices that haven't changed are not re-reported, so the 7-day `max_price_age` hides about 10% of prices, mostly at stations that seem to have stopped reporting (about 770 of 9,400 stations have no price newer than 7 days). LPG and E85 change less often and are hit more.
- Coordinates are degrees × 100000. The feed covers mainland France and Corsica only. Stations without any price (about 470) are skipped.
- The feed has no station names or brands. The station is named after its town, with "(autoroute)" added for motorway stations (`pop="A"`).
- Fuels: `Gazole` → diesel, `SP95` and `E10` → petrol, `SP98` → premium petrol, `GPLc` → LPG, `E85` (superethanol) → other.

## Spain data notes

- Source: `https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/EstacionesTerrestres/` ([datos.gob.es](https://datos.gob.es/en/catalogo/e05068001-precio-de-carburantes-en-las-gasolineras-espanolas)). One request returns every station (about 12 MB, about 10 s). The ministry refreshes it every half hour. The server sometimes drops connections, so a failed download is retried once.
- `Fecha` gives the data date. There are no per-price dates, so the build records `seen_since` as for Slovenia and Croatia.
- Numbers use a decimal comma. A few stations have `0,000000` coordinates (skipped) or latitude and longitude swapped (fixed by value range). The Canary Islands, Ceuta and Melilla are included. Their lower taxes give lower prices, which outlier detection handles because it compares only nearby stations.
- Petrol goes by octane: 95 (E5, E10 and "95 E5 Premium") is `petrol`, 98 is `premium_petrol`. `Gasoleo Premium` is premium diesel, `Diésel Renovable` is HVO, and biogas is CNG or LNG. E25, E85, renewable petrol, bioethanol and biodiesel go to "other". Agricultural diesel (`Gasoleo B`), AdBlue, hydrogen, methanol and ammonia are dropped.
- `Rótulo` (the sign over the station) is used as the station name. There is no separate brand or operator field.
- Spain has many discount chains (Ballenoil, Alcampo, bonÀrea, Plenergy...) pricing 12–25% below their neighbours. With the default 12% outlier margin, about 220 of their real prices were hidden, so Spain uses `outlier_low = 0.25`. About 6 prices are still flagged.
