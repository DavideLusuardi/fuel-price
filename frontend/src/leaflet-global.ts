// leaflet.markercluster is a UMD plugin that augments the global `L`.
// Expose the ESM Leaflet instance globally before the plugin is imported.
import L from "leaflet";

(window as unknown as { L: typeof L }).L = L;

export default L;
