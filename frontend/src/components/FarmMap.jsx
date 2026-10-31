// Plain-Leaflet map. Fixes the "blue grid, no tiles" problem: (1) leaflet CSS imported, (2) container has a fixed height,
// (3) invalidateSize on resize, (4) automatic switch to a second tile provider if the first one blocks/fails.
import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "../insights.css";

const BASEMAPS = [
  { url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png", attr: "© OpenStreetMap contributors" },
  { url: "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png", attr: "© OpenStreetMap, © CARTO" },
  { url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}", attr: "Esri" },
];
const COLORS = ["#2e7d32", "#f9a825", "#ef6c00", "#c62828"];
const bucket = (s) => COLORS[s < 25 ? 0 : s < 50 ? 1 : s < 75 ? 2 : 3];

export default function FarmMap({ lat, lon, onSelect, cells = [], cellKm = 8, metric = "overall", height = 380 }) {
  const el = useRef(null), map = useRef(null), base = useRef(null), marker = useRef(null), grid = useRef(null);
  const errs = useRef(0), idx = useRef(0), sat = useRef(null);

  useEffect(() => {
    const m = L.map(el.current, { center: [lat ?? 22.5, lon ?? 79], zoom: lat ? 10 : 5 });
    map.current = m;
    const useBase = (i) => {
      if (base.current) m.removeLayer(base.current);
      errs.current = 0; idx.current = i;
      base.current = L.tileLayer(BASEMAPS[i].url, { attribution: BASEMAPS[i].attr, maxZoom: 18, subdomains: "abc" })
        .on("tileerror", () => { if (++errs.current >= 6 && idx.current < BASEMAPS.length - 1) useBase(idx.current + 1); })
        .addTo(m);
    };
    useBase(0);
    const d = new Date(Date.now() - 2 * 864e5).toISOString().slice(0, 10);
    sat.current = L.tileLayer(
      `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Terra_CorrectedReflectance_TrueColor/default/${d}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg`,
      { maxNativeZoom: 9, maxZoom: 18, attribution: "NASA GIBS / MODIS" });
    L.control.layers({ Map: base.current }, { "Satellite (MODIS true colour)": sat.current }, { collapsed: true }).addTo(m);
    grid.current = L.layerGroup().addTo(m);
    m.on("click", (e) => onSelect && onSelect(+e.latlng.lat.toFixed(5), +e.latlng.lng.toFixed(5)));
    const ro = new ResizeObserver(() => m.invalidateSize());
    ro.observe(el.current);
    setTimeout(() => m.invalidateSize(), 200);
    return () => { ro.disconnect(); m.remove(); };
  }, []);

  useEffect(() => {
    if (!map.current || lat == null || lon == null) return;
    if (marker.current) marker.current.remove();
    marker.current = L.circleMarker([lat, lon], { radius: 8, color: "#12332b", fillColor: "#2a6f97", fillOpacity: 0.9 }).addTo(map.current);
    map.current.setView([lat, lon], Math.max(map.current.getZoom(), 9));
  }, [lat, lon]);

  useEffect(() => {
    if (!grid.current) return;
    grid.current.clearLayers();
    cells.forEach((c) => {
      const s = c[metric] ?? 0;
      L.circle([c.lat, c.lon], { radius: (cellKm * 1000) / 2, color: bucket(s), weight: 0, fillColor: bucket(s), fillOpacity: 0.35 })
        .bindTooltip(`heat ${c.heat} · rain ${c.rain} · dry ${c.dry}<br/>max ${c.max_temp}°C, rain ${c.rain_7d} mm (7 d)`)
        .addTo(grid.current);
    });
  }, [cells, metric, cellKm]);

  return <div ref={el} className="cg-map" style={{ height }} />;
}
