import "../insights.css";

export default function AdvisoryV2({ result }) {
  if (!result) return null;
  const g = result.generated_by, gr = result.grounding;
  return (
    <div className="cg-panel">
      <h3 style={{ margin: "0 0 6px" }}>Advisory</h3>
      <span className="cg-badge" style={{ color: g.fallback ? "#ef6c00" : "#2e7d32" }}>
        {g.fallback ? "Rule-based fallback (no AI model reachable)" : `Written by ${g.provider} · ${g.model}${g.cached ? " (cached)" : ""}`}
      </span>
      <div style={{ whiteSpace: "pre-wrap", marginTop: 10, lineHeight: 1.5 }}>{result.advisory}</div>
      {gr && gr.checked > 0 && (
        <div className="cg-muted" style={{ marginTop: 8 }}>
          Figure check: {gr.checked - gr.unverified.length} of {gr.checked} figures match the data{gr.self_corrected ? " (after self-correction)" : ""}
          {gr.unverified.length > 0 && <> · unverified: {gr.unverified.join(", ")}</>}
        </div>
      )}
      {result.attempts?.filter((a) => !a.ok).map((a, i) => (
        <div key={i} className="cg-muted">{a.provider} skipped: {a.error}</div>
      ))}
    </div>
  );
}
