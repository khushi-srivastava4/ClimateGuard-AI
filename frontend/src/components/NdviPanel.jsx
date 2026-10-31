import { useState } from "react";
import { getNdvi } from "../api/insights";
import "../insights.css";

export default function NdviPanel({ lat, lon }) {
  const [data, setData] = useState(null), [err, setErr] = useState(""), [busy, setBusy] = useState(false);
  const load = async () => {
    setBusy(true); setErr(""); setData(null);
    try { setData(await getNdvi({ lat, lon })); } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const pts = data?.series || [];
  const W = 320, H = 90, x = (i) => (pts.length < 2 ? W / 2 : 10 + (i * (W - 20)) / (pts.length - 1)), y = (v) => H - 10 - v * (H - 20);
  return (
    <div className="cg-panel">
      <h3 style={{ margin: "0 0 4px" }}>Vegetation (Sentinel-2 NDVI)</h3>
      <button onClick={load} disabled={busy || lat == null}>{busy ? "Reading satellite scenes…" : "Check vegetation"}</button>
      {err && <div className="cg-muted" style={{ color: "#c62828", marginTop: 8 }}>Unavailable: {err}</div>}
      {data && (
        <>
          <svg width={W} height={H} style={{ display: "block", marginTop: 10 }}>
            <polyline fill="none" stroke="#2a6f97" strokeWidth="2" points={pts.map((p, i) => `${x(i)},${y(p.ndvi_mean)}`).join(" ")} />
            {pts.map((p, i) => <circle key={p.date} cx={x(i)} cy={y(p.ndvi_mean)} r="3.5" fill="#12332b"><title>{p.date}: NDVI {p.ndvi_mean}</title></circle>)}
          </svg>
          <div className="cg-muted">{pts.length} cloud-free scenes, {pts[0].date} to {pts[pts.length - 1].date}. Latest NDVI {pts[pts.length - 1].ndvi_mean}
            {data.trend && <> · {data.trend.direction} ({data.trend.change > 0 ? "+" : ""}{data.trend.change})</>}</div>
          <div className="cg-muted">{data.caveat}</div>
        </>
      )}
    </div>
  );
}
