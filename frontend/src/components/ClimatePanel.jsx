import { useEffect, useState } from "react";
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import FarmMap from "./FarmMap";
import RiskEvidence from "./RiskEvidence";
import AdvisoryV2 from "./AdvisoryV2";
import NdviPanel from "./NdviPanel";
import { Btn, Card, CROP_IDS, Err, Field, inputCls, Note, Txt } from "./ui";
import { adviseV2, getGrid, getValidation, reportOutcome } from "../api/insights";

export default function ClimatePanel({ language, t, tc }) {
  const [loc, setLoc] = useState({ lat: 27.1767, lon: 78.0081 });
  const [form, setForm] = useState({ crop: "wheat", stage: "", soil_type: "", state: "" });
  const [res, setRes] = useState(null);
  const [grid, setGrid] = useState(null);
  const [metric, setMetric] = useState("overall");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [val, setVal] = useState(null);
  const [out, setOut] = useState({ event: "none", observed_date: new Date().toISOString().slice(0, 10) });
  const [outMsg, setOutMsg] = useState("");

  const loadVal = () => getValidation().then(setVal).catch(() => setVal(null));
  useEffect(() => { loadVal(); }, []);

  async function analyze() {
    setBusy(true); setErr(""); setRes(null);
    getGrid({ lat: loc.lat, lon: loc.lon }).then(setGrid).catch(() => setGrid(null));
    try {
      setRes(await adviseV2({ lat: loc.lat, lon: loc.lon, crop: form.crop, stage: form.stage || null, soil_type: form.soil_type || null, state: form.state || null, language }));
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }

  async function submitOutcome() {
    setOutMsg("");
    try {
      await reportOutcome({ lat: loc.lat, lon: loc.lon, crop: form.crop, event: out.event, observed_date: out.observed_date });
      setOutMsg(t.outcomeThanks); loadVal();
    } catch (e) { setOutMsg(e.message); }
  }

  const a = res?.assessment;
  const s = a?.series;
  const chartData = s ? s.dates.map((d, i) => ({ date: d.slice(5), rain: s.precip[i], tmax: s.tmax[i], et0: s.et0[i], future: i >= s.past_len })) : [];

  return (
    <div className="grid gap-4 lg:grid-cols-[1.1fr_1fr]">
      <div className="space-y-4">
        <Card title={t.climateTitle} hint={t.climateHint}>
          <FarmMap lat={loc.lat} lon={loc.lon} onSelect={(lat, lon) => setLoc({ lat, lon })} cells={grid?.cells} cellKm={grid?.cell_km} metric={metric} />
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <Field label={t.crop}>
              <select className={inputCls} value={form.crop} onChange={(e) => setForm({ ...form, crop: e.target.value })}>
                {CROP_IDS.map((id) => <option key={id} value={id}>{tc[id]}</option>)}
              </select>
            </Field>
            <Field label={t.heatmapLayer}>
              <select className={inputCls} value={metric} onChange={(e) => setMetric(e.target.value)}>
                {["overall", "heat", "rain", "dry"].map((m) => <option key={m} value={m}>{t["metric_" + m]}</option>)}
              </select>
            </Field>
            <Field label={t.growthStage}><Txt value={form.stage} onChange={(v) => setForm({ ...form, stage: v })} placeholder="vegetative / flowering / harvest" /></Field>
            <Field label={t.soilType}><Txt value={form.soil_type} onChange={(v) => setForm({ ...form, soil_type: v })} placeholder="loam, clay, sandy…" /></Field>
            <Field label={t.stateForMandi}><Txt value={form.state} onChange={(v) => setForm({ ...form, state: v })} placeholder="Uttar Pradesh" /></Field>
            <div className="flex items-end"><Btn busy={busy} onClick={analyze} className="w-full">{busy ? t.analyzing : t.analyze}</Btn></div>
          </div>
          <Note>{loc.lat.toFixed(4)}, {loc.lon.toFixed(4)} · {t.clickMap}</Note>
          <Err>{err}</Err>
        </Card>

        {a && (
          <Card title={t.forecastChart} hint={t.forecastChartHint}>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={chartData}>
                  <CartesianGrid stroke="#1e293b" />
                  <XAxis dataKey="date" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                  <YAxis yAxisId="mm" stroke="#94a3b8" unit="mm" />
                  <YAxis yAxisId="c" orientation="right" stroke="#f59e0b" unit="°" />
                  <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} />
                  <Legend />
                  <Bar yAxisId="mm" dataKey="rain" name={t.rain} fill="#38bdf8" />
                  <Line yAxisId="mm" dataKey="et0" name="ET0" stroke="#a3e635" dot={false} />
                  <Line yAxisId="c" dataKey="tmax" name={t.maxTemp} stroke="#f59e0b" dot={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </Card>
        )}
        <NdviPanel lat={loc.lat} lon={loc.lon} />
      </div>

      <div className="space-y-4">
        {res && <AdvisoryV2 result={res} />}
        {a && <RiskEvidence risks={a.risks} sources={a.sources} />}
        {a && (
          <Card title={t.actionPlan}>
            <ul className="space-y-2 text-sm">
              {a.actions_v2.map((x) => (
                <li key={x.key} className="rounded-lg border border-slate-800 p-2">
                  <span className="font-semibold text-emerald-300">{x.date}</span> · {x.title}
                  <div className="text-slate-400">{x.detail}</div>
                </li>
              ))}
            </ul>
            <div className="mt-3 grid gap-2 text-sm text-slate-300 sm:grid-cols-2">
              <div><b>{t.irrigation}</b><br />{t.week1}: {a.water.weekly_irrigation_mm[0]} mm · {t.week2}: {a.water.weekly_irrigation_mm[1]} mm<br /><span className="text-slate-500">{a.water.assumption}</span></div>
              <div><b>{t.sowingWindows}</b><br />{a.sowing_windows.length ? a.sowing_windows.slice(0, 2).map((w) => `${w.start} → ${w.end}`).join(" · ") : t.none}<br /><b>{t.dryWindows}</b><br />{a.dry_windows.length ? a.dry_windows.slice(0, 2).map((w) => `${w.start} → ${w.end}`).join(" · ") : t.none}</div>
            </div>
          </Card>
        )}
        {a && (
          <Card title={t.contextTitle}>
            <ul className="space-y-1 text-sm text-slate-300">
              <li>{t.enso}: {a.enso ? `${a.enso.phase} (ONI ${a.enso.oni}, ${a.enso.season})` : t.unavailable}</li>
              <li>{t.soil}: {a.soil ? `${a.soil.source}${a.soil.clay_pct != null ? ` · clay ${Number(a.soil.clay_pct).toFixed(0)}%` : ""}${a.soil.ph != null ? ` · pH ${Number(a.soil.ph).toFixed(1)}` : ""}` : t.unavailable}</li>
              <li>{t.market}: {a.market ? `₹${a.market.median_modal ?? ""}/quintal (${a.market.scope})${a.market.stale ? " — " + t.stale : ""}` : t.unavailable}</li>
            </ul>
            {a.warnings.map((w, i) => <p key={i} className="mt-1 text-xs text-amber-300">{w}</p>)}
          </Card>
        )}
        <Card title={t.outcomeTitle} hint={t.outcomeHint}>
          <div className="grid gap-2 sm:grid-cols-3">
            <select className={inputCls} value={out.event} onChange={(e) => setOut({ ...out, event: e.target.value })}>
              {["none", "drought", "heat", "flood", "unseasonal_rain"].map((x) => <option key={x} value={x}>{t["event_" + x]}</option>)}
            </select>
            <input type="date" className={inputCls} value={out.observed_date} onChange={(e) => setOut({ ...out, observed_date: e.target.value })} />
            <Btn onClick={submitOutcome}>{t.submit}</Btn>
          </div>
          {outMsg && <Note>{outMsg}</Note>}
          {val && <Note>{val.status}: {val.reason}</Note>}
        </Card>
      </div>
    </div>
  );
}
