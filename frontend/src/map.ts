import L from "./leaflet-global";
import "leaflet.markercluster";
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";

import type { FuelCategory, MapData, MapRow, Station } from "./types";
import { escapeHtml, formatPrice, priceColor, relativeAge, scale, shortPrice, unit } from "./format";

/** Station ids are only unique within a country. */
export const rowKey = (r: Pick<MapRow, "country" | "id">) => `${r.country}:${r.id}`;

interface PriceMarkerOptions extends L.MarkerOptions {
  row: MapRow;
}

type PriceMarker = L.Marker & { options: PriceMarkerOptions };

export class PriceMap {
  readonly map: L.Map;
  private cluster: L.MarkerClusterGroup;
  private markers = new Map<string, PriceMarker>();
  private data: MapData | null = null;
  private userMarker: L.CircleMarker | null = null;

  /**
   * @param getStation resolves full station details from the loaded data.
   * @param overlay element floating over the map (side panel) that popups must avoid.
   */
  constructor(
    el: HTMLElement,
    private getStation: (country: string, id: string) => Station | null,
    private overlay?: HTMLElement,
  ) {
    this.map = L.map(el, { zoomControl: true, preferCanvas: true });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(this.map);

    this.cluster = L.markerClusterGroup({
      chunkedLoading: true,
      showCoverageOnHover: false,
      maxClusterRadius: (zoom) => (zoom >= 13 ? 30 : 60),
      disableClusteringAtZoom: 15,
      iconCreateFunction: (c) => this.clusterIcon(c),
    });
    this.cluster.on("click", (e) => this.openStation((e as L.LeafletEvent & { layer: PriceMarker }).layer));
    this.map.addLayer(this.cluster);
  }

  setView(center: [number, number], zoom: number): void {
    this.map.setView(center, zoom);
  }

  setData(data: MapData): void {
    this.data = data;
    this.map.closePopup();
    this.cluster.clearLayers();
    this.markers.clear();
    const layers: PriceMarker[] = data.rows.map((row) => {
      const m = L.marker([row.lat, row.lon], {
        icon: this.markerIcon(row.price),
        row,
        title: `${row.name} – ${shortPrice(row.price)}`,
      } as PriceMarkerOptions) as PriceMarker;
      this.markers.set(rowKey(row), m);
      return m;
    });
    this.cluster.addLayers(layers);
  }

  /** Zoom to show all stations currently on the map. */
  fitToData(): void {
    if (!this.data?.rows.length) return;
    const bounds = L.latLngBounds(this.data.rows.map((r) => [r.lat, r.lon] as [number, number]));
    this.map.fitBounds(bounds, { padding: [20, 20], maxZoom: 12 });
  }

  /** Cheapest stations currently inside the map viewport. */
  cheapestInView(limit: number): MapRow[] {
    if (!this.data) return [];
    const bounds = this.map.getBounds();
    return this.data.rows
      .filter((r) => bounds.contains([r.lat, r.lon]))
      .sort((a, b) => a.price - b.price)
      .slice(0, limit);
  }

  /** @param key a row key as returned by {@link rowKey}. */
  focus(key: string): void {
    const marker = this.markers.get(key);
    if (!marker) return;
    this.cluster.zoomToShowLayer(marker, () => this.openStation(marker));
  }

  locate(): void {
    this.map.locate({ setView: true, maxZoom: 13 });
    this.map.once("locationfound", (e: L.LocationEvent) => {
      this.userMarker?.remove();
      this.userMarker = L.circleMarker(e.latlng, {
        radius: 8, color: "#fff", weight: 3, fillColor: "#2563eb", fillOpacity: 1,
      }).addTo(this.map);
    });
    this.map.once("locationerror", (e: L.ErrorEvent) => alert(`Could not get your location: ${e.message}`));
  }

  // -- rendering -------------------------------------------------------------

  private color(price: number): string {
    return priceColor(scale(price, this.data?.stats ?? null));
  }

  private markerIcon(price: number): L.DivIcon {
    return L.divIcon({
      className: "price-marker",
      html: `<span style="--c:${this.color(price)}">${shortPrice(price)}</span>`,
      iconSize: [52, 26],
      iconAnchor: [26, 26],
      popupAnchor: [0, -24],
    });
  }

  private clusterIcon(cluster: L.MarkerCluster): L.DivIcon {
    let min = Infinity;
    for (const m of cluster.getAllChildMarkers() as PriceMarker[]) {
      if (m.options.row.price < min) min = m.options.row.price;
    }
    const count = cluster.getChildCount();
    return L.divIcon({
      className: "price-cluster",
      html: `<div style="border-color:${this.color(min)}"><small>from</small><b style="color:${this.color(min)}">${shortPrice(min)}</b><small>${count} stations</small></div>`,
      iconSize: [72, 50],
    });
  }

  private openStation(marker: PriceMarker): void {
    const row = marker.options.row;
    const station = this.getStation(row.country, row.id);
    const html = station
      ? this.popupHtml(station, row)
      : `<div class="popup"><h3>${escapeHtml(row.name)}</h3><p>Details not available.</p></div>`;
    L.popup({ maxWidth: 340, minWidth: 260, ...this.popupPadding() })
      .setLatLng(marker.getLatLng())
      .setContent(html)
      .openOn(this.map);
  }

  /** Keep auto-panned popups clear of the overlay panel (right side on desktop, bottom on mobile). */
  private popupPadding(): Pick<L.PopupOptions, "autoPanPaddingTopLeft" | "autoPanPaddingBottomRight"> {
    const pad = 16;
    const map = this.map.getContainer().getBoundingClientRect();
    const box = this.overlay?.getBoundingClientRect();
    let right = pad;
    let bottom = pad;
    if (box && box.width > 0) {
      if (box.left > map.left + map.width / 2) right = map.right - box.left + pad;
      else bottom = map.bottom - box.top + pad;
    }
    return { autoPanPaddingTopLeft: [pad, pad], autoPanPaddingBottomRight: [right, bottom] };
  }

  private popupHtml(s: Station, row: MapRow): string {
    const currency = row.currency;
    const selected: FuelCategory | undefined = this.data?.fuel;
    const hasModes = s.prices.some((p) => p.self_service !== null);
    // Sources with timestamps get "Updated"; others get "Unchanged since" (observed by the data build).
    const dateKind: "updated" | "since" | null = s.prices.some((p) => p.updated_at)
      ? "updated"
      : s.prices.some((p) => p.seen_since)
        ? "since"
        : null;

    // One row per product, with self and attended columns.
    type Entry = { category: FuelCategory; self?: number; attended?: number; any?: number; date: Date | null };
    const products = new Map<string, Entry>();
    for (const p of s.prices) {
      const entry: Entry = products.get(p.product) ?? { category: p.category, date: null };
      if (p.self_service === true) entry.self = p.price;
      else if (p.self_service === false) entry.attended = p.price;
      else entry.any = p.price;
      const d = dateKind === "updated" ? p.updated_at : p.seen_since;
      // Newest update; for "since", the most recent change of any mode.
      if (d && (!entry.date || d > entry.date)) entry.date = d;
      products.set(p.product, entry);
    }
    const cell = (v?: number) => (v === undefined ? "–" : formatPrice(v, currency));
    const rows = [...products.entries()]
      .sort(([, a], [, b]) => Number(b.category === selected) - Number(a.category === selected))
      .map(([name, e]) => {
        const age = dateKind === "updated" ? relativeAge(e.date) : { text: "", old: false };
        const cls = [e.category === selected ? "selected" : "", age.old ? "old" : ""].join(" ");
        const prices = hasModes ? `<td>${cell(e.self)}</td><td>${cell(e.attended)}</td>` : `<td>${cell(e.any)}</td>`;
        const title = e.date ? e.date.toLocaleString() : "";
        const updated =
          dateKind === "updated"
            ? `<td class="age" title="${title}">${age.old ? "⚠ " : ""}${age.text}</td>`
            : dateKind === "since"
              ? `<td class="age" title="${title}">${e.date ? e.date.toLocaleDateString() : "–"}</td>`
              : "";
        return `<tr class="${cls}"><th>${escapeHtml(name)}<small>${unit(e.category)}</small></th>${prices}${updated}</tr>`;
      })
      .join("");
    const head = hasModes ? "<th>Self</th><th>Attended</th>" : "<th>Price</th>";
    const place = [s.address, [s.city, s.province && `(${s.province})`].filter(Boolean).join(" ")]
      .filter(Boolean).map(escapeHtml).join("<br>");
    const directions = `https://www.google.com/maps/dir/?api=1&destination=${s.lat},${s.lon}`;
    return `<div class="popup">
      <h3>${escapeHtml(s.name)}</h3>
      <p class="brand">${escapeHtml(s.brand)}${s.operator && s.operator !== s.brand ? ` · ${escapeHtml(s.operator)}` : ""}</p>
      <p class="addr">${place}</p>
      <table><thead><tr><th></th>${head}${dateKind === "updated" ? "<th>Updated</th>" : dateKind === "since" ? '<th title="First seen at this price by the data build">Unchanged since</th>' : ""}</tr></thead><tbody>${rows}</tbody></table>
      <a href="${directions}" target="_blank" rel="noopener">Directions ↗</a>
    </div>`;
  }
}
