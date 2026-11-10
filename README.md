# Fuel price map

A web map of fuel stations showing the price of the selected fuel. Each country's data
source is a **plugin**. Three countries ship today:

| Country | Source | Stations | Notes |
|---|---|---|---|
| Italia (`it`) | MIMIT open data, two CSVs published daily | ~21,600 | self/attended prices, per-price timestamps |
| Slovenija (`si`) | goriva.si JSON API | ~540 | one price per fuel, no timestamps |
| Hrvatska (`hr`) | mzoe-gor.hr (Ministry of Economy), gzipped JSON | ~870 | one price per fuel, no timestamps |

There is no server. The app is a static site that reads pre-built data files:

```
 sources (MIMIT, goriva.si, mzoe-gor)          GitHub Actions, every 2 h
        │                                     ┌──────────────────────────────┐
        └──────────────► fuelprice-build ────►│ data/meta.json, it.json, ... │
                         (Python plugins)     └──────────────┬───────────────┘
                                                             │ static hosting (GitHub Pages)
                                                             ▼
                                        browser: IndexedDB cache, refreshed when older than 4 h
```

- **`backend/`** (Python 3.12) holds the country plugins and the `fuelprice-build` command. It fetches every source, normalizes the data and writes compact JSON files (`export.py` describes the format). It is not a server: it only runs at build time.
- **`frontend/`** (Vite, TypeScript, Leaflet, markercluster) is the web app. Markers show the price, colored from green (cheap) to red, and clusters show the lowest price inside them. Several countries can be shown at once.

A build job is needed because the Italian and Slovenian sources don't send CORS headers. That means a browser can't read them directly, while it can read files published next to the app.

## How the app keeps data fresh

- Everything downloaded is saved in the browser's **IndexedDB**. A reopened app starts from the saved copy without waiting for the network.
- When the saved data is **older than 4 hours**, the app re-checks `meta.json`, which is small. It then downloads a country again only if that country's file has changed (`hash` in `meta.json`). Italy publishes once a day, so most checks download nothing. Only the countries you select are downloaded.
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

- Source: [MIMIT, carburanti open data](https://www.mimit.gov.it/it/open-data/elenco-dataset/carburanti-prezzi-praticati-e-anagrafica-degli-impianti). It is two `|`-separated CSVs (stations and prices), published every morning with the prices as of 08:00.
- Some station names contain a stray `|`, and a few rows have no coordinates or placeholder prices such as `0.100`. The parser handles all of these.
- About 50 branded product names are mapped to categories in `plugins/italy/fuels.py`. Names not listed there fall back to keyword rules, and any that still don't match are logged.

## Slovenia data notes

- Source: `https://goriva.si/api/v1/search/?page=N` (25 stations per page, fetched concurrently) and `/api/v1/franchise/` for the brand names.
- Fuel codes map directly to categories (`95`, `dizel`, `98`, `100`, `dizel-premium`, `avtoplin-lpg`, `hvo`, `cng`, `lng`). `KOEL` is heating oil and is skipped.
- `0.001` is used as a placeholder for "not sold" and is filtered out.

## Croatia data notes

- Source: `https://webservis.mzoe-gor.hr/data.gz`, the file the official site loads. `mzoe-gor.hr/data.json` is an outdated copy. `Last-Modified` gives the data date.
- The category comes from `vrsta_goriva_id`. Brand names containing "premium", "V-Power", "G-Power" and similar move a fuel to the premium category. Heating oil, agricultural "blue" diesel, bottled LPG, bio components and EV charging are dropped.
- Most rows have the `long` and `lat` fields swapped, so they are assigned by value range. A few coordinates use degree-minute notation (`45° 39.4112' N`), and some are empty or are a Google Maps link, which are skipped.
- A few stations still list prices in kuna from before the euro (2023). Any station with a road-fuel price above €4.50 is treated as stale and dropped.
