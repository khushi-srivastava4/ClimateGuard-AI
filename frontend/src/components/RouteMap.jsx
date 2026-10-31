// Leaflet map for the relief agent: zones, depots, vehicles and the chosen routes. Click to pick a location.
import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

const COLORS = { zone: "#ef4444", supplier: "#22c55e", vehicle: "#3b82f6", pick: "#f59e0b" };

export default function RouteMap({ points = [], routes = [], pick, onSelect, height = 340 }) {
  const el = useRef(null), map = useRef(null), layer = useRef(null);

  useEffect(() => {
    const m = L.map(el.current, { center: [22.5, 79], zoom: 5 });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap contributors" })
      .on("tileerror", function () { this._errs = (this._errs || 0) + 1; if (this._errs === 6) { this.setUrl("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png"); } })
      .addTo(m);
    layer.current = L.layerGroup().addTo(m);
    m.on("click", (e) => onSelect && onSelect(+e.latlng.lat.toFixed(5), +e.latlng.lng.toFixed(5)));
    const ro = new ResizeObserver(() => m.invalidateSize());
    ro.observe(el.current);
    map.current = m;
    return () => { ro.disconnect(); m.remove(); };
  }, []);

  useEffect(() => {
    const g = layer.current;
    if (!g) return;
    g.clearLayers();
    const all = [];
    points.forEach((p) => {
      all.push([p.lat, p.lon]);
      L.circleMarker([p.lat, p.lon], { radius: 8, color: "#0f172a", weight: 1, fillColor: COLORS[p.kind] || "#999", fillOpacity: 0.95 }).bindTooltip(`${p.kind}: ${p.label}`).addTo(g);
    });
    routes.forEach((r) => { if (r.path?.length) { L.polyline(r.path, { color: r.safe === false ? "#ef4444" : "#38bdf8", weight: 4, opacity: 0.8 }).addTo(g); r.path.forEach((c) => all.push(c)); } });
    if (pick) L.circleMarker([pick.lat, pick.lon], { radius: 6, color: COLORS.pick, fillColor: COLORS.pick, fillOpacity: 0.4 }).addTo(g);
    if (all.length && map.current) map.current.fitBounds(all, { padding: [30, 30], maxZoom: 10 });
  }, [points, routes, pick]);

  return <div ref={el} style={{ height, width: "100%", borderRadius: 16, overflow: "hidden" }} />;
}
