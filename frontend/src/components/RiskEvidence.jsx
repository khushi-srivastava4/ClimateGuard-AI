import "../insights.css";
const COLORS = { low: "#2e7d32", moderate: "#f9a825", high: "#ef6c00", severe: "#c62828" };
const NAMES = { drought: "Drought / water stress", heat: "Heat stress", flood: "Heavy rain / waterlogging", unseasonal_rain: "Unseasonal rain" };

export default function RiskEvidence({ risks, sources }) {
  if (!risks) return null;
  return (
    <div className="cg-panel">
      <h3 style={{ margin: "0 0 4px" }}>Climate risk, with evidence</h3>
      <div className="cg-muted">Heuristic indicators from live forecasts, not calibrated probabilities of crop loss.</div>
      {Object.entries(risks).map(([k, r]) => (
        <div key={k}>
          <div className="cg-row">
            <b>{NAMES[k] || k}</b>
            <div className="cg-bar"><i style={{ width: `${r.score}%`, background: COLORS[r.level] }} /></div>
            <span className="cg-badge" style={{ color: COLORS[r.level] }}>{r.level} {r.score}</span>
          </div>
          {r.evidence.map((e, i) => (
            <div key={i} className="cg-muted cg-ev">{e.text} <small>[{e.src.join(", ")}]</small></div>
          ))}
        </div>
      ))}
      {sources && (
        <div className="cg-muted" style={{ marginTop: 10 }}>
          Sources: {Object.entries(sources).map(([id, s]) => `${id} ${s.state}${s.latency_ms ? ` (${s.latency_ms} ms)` : ""}`).join(" · ")}
        </div>
      )}
    </div>
  );
}
