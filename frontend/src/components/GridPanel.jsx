import { useEffect, useState } from "react";
import { Area, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import FarmMap from "./FarmMap";
import { Btn, Card, Err, Field, Ghost, inputCls, Note, Num, Txt } from "./ui";
import { gridPlan, gridSites, postTelemetry, saveSite } from "../api/insights";

const blankLoad = () => ({ name: "", kw: 1, priority: 3, cooling: false, deferrable: false, run_hours: 2 });
const blankSite = { name: "", pv_kwp: 5, inverter_kw: "", battery_kwh: 10, battery_min_soc_pct: 20, grid_import_limit_kw: 0, tank_l: "", water_demand_lph: "", pump_kw: "", pump_lph: "" };

export default function GridPanel({ t }) {
  const [loc, setLoc] = useState({ lat: 27.1767, lon: 78.0081 });
  const [sites, setSites] = useState([]);
  const [siteId, setSiteId] = useState("");
  const [form, setForm] = useState(blankSite);
  const [loads, setLoads] = useState([{ ...blankLoad(), name: "Vaccine fridge", kw: 0.4, priority: 1 }]);
  const [tel, setTel] = useState({ soc_pct: "", tank_pct: "", load_kw: "", grid_available: true });
  const [plan, setPlan] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  const refresh = () => gridSites().then((s) => { setSites(s); if (!siteId && s[0]) setSiteId(s[0].id); }).catch((e) => setErr(e.message));
  useEffect(() => { refresh(); }, []);

  const clean = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== "" && v !== null));

  async function save() {
    setErr(""); setMsg("");
    try {
      const s = await saveSite({ ...clean(form), lat: loc.lat, lon: loc.lon, loads: loads.filter((l) => l.name).map((l) => clean({ ...l, run_hours: l.deferrable ? l.run_hours : "" })) });
      setSiteId(s.id); setMsg(t.siteSaved); refresh();
    } catch (e) { setErr(e.message); }
  }
  async function sendTel() {
    setErr(""); setMsg("");
    try { await postTelemetry({ site_id: siteId, ...clean(tel) }); setMsg(t.telemetrySaved); } catch (e) { setErr(e.message); }
  }
  async function makePlan() {
    setBusy(true); setErr(""); setPlan(null);
    try { setPlan(await gridPlan(siteId, 24)); } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }

  const upLoad = (i, patch) => setLoads(loads.map((l, k) => (k === i ? { ...l, ...patch } : l)));
  const rows = plan?.rows.map((r) => ({ ...r, h: r.time.slice(11, 16) })) || [];
  const sm = plan?.summary;

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_1.3fr]">
      <div className="space-y-4">
        <Card title={t.gridSite} hint={t.gridHint}>
          <FarmMap lat={loc.lat} lon={loc.lon} onSelect={(lat, lon) => setLoc({ lat, lon })} height={220} />
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <Field label={t.siteName}><Txt value={form.name} onChange={(v) => setForm({ ...form, name: v })} placeholder="Village clinic" /></Field>
            <Field label={t.pvKwp}><Num value={form.pv_kwp} onChange={(v) => setForm({ ...form, pv_kwp: v })} /></Field>
            <Field label={t.inverterKw}><Num value={form.inverter_kw} onChange={(v) => setForm({ ...form, inverter_kw: v })} /></Field>
            <Field label={t.batteryKwh}><Num value={form.battery_kwh} onChange={(v) => setForm({ ...form, battery_kwh: v })} /></Field>
            <Field label={t.minSoc}><Num value={form.battery_min_soc_pct} onChange={(v) => setForm({ ...form, battery_min_soc_pct: v })} /></Field>
            <Field label={t.importLimit}><Num value={form.grid_import_limit_kw} onChange={(v) => setForm({ ...form, grid_import_limit_kw: v })} /></Field>
            <Field label={t.tankL}><Num value={form.tank_l} onChange={(v) => setForm({ ...form, tank_l: v })} /></Field>
            <Field label={t.waterDemand}><Num value={form.water_demand_lph} onChange={(v) => setForm({ ...form, water_demand_lph: v })} /></Field>
            <Field label={t.pumpKw}><Num value={form.pump_kw} onChange={(v) => setForm({ ...form, pump_kw: v })} /></Field>
            <Field label={t.pumpLph}><Num value={form.pump_lph} onChange={(v) => setForm({ ...form, pump_lph: v })} /></Field>
          </div>
          <h3 className="mt-4 font-semibold text-slate-200">{t.loads}</h3>
          <Note>{t.loadsHint}</Note>
          <div className="mt-2 space-y-2">
            {loads.map((l, i) => (
              <div key={i} className="grid grid-cols-[1.4fr_0.7fr_0.6fr] gap-2 rounded-lg border border-slate-800 p-2 text-sm">
                <Txt value={l.name} onChange={(v) => upLoad(i, { name: v })} placeholder={t.loadName} />
                <Num value={l.kw} onChange={(v) => upLoad(i, { kw: v })} title="kW" />
                <select className={inputCls} value={l.priority} onChange={(e) => upLoad(i, { priority: Number(e.target.value) })} title={t.priority}>
                  {[1, 2, 3, 4, 5].map((p) => <option key={p} value={p}>P{p}</option>)}
                </select>
                <label className="col-span-1 flex items-center gap-1 text-slate-300"><input type="checkbox" checked={l.cooling} onChange={(e) => upLoad(i, { cooling: e.target.checked })} />{t.cooling}</label>
                <label className="col-span-1 flex items-center gap-1 text-slate-300"><input type="checkbox" checked={l.deferrable} onChange={(e) => upLoad(i, { deferrable: e.target.checked })} />{t.deferrable}</label>
                <div className="flex items-center gap-1">{l.deferrable && <Num value={l.run_hours} onChange={(v) => upLoad(i, { run_hours: v })} title={t.runHours} />}<Ghost onClick={() => setLoads(loads.filter((_, k) => k !== i))}>✕</Ghost></div>
              </div>
            ))}
          </div>
          <div className="mt-3 flex gap-2"><Ghost onClick={() => setLoads([...loads, blankLoad()])}>+ {t.addLoad}</Ghost><Btn onClick={save} disabled={!form.name}>{t.saveSite}</Btn></div>
        </Card>
        <Card title={t.edgeTitle}><Note>{t.edgeNote}</Note></Card>
      </div>

      <div className="space-y-4">
        <Card title={t.liveState}>
          <div className="flex flex-wrap items-end gap-2">
            <Field label={t.gridSite}>
              <select className={inputCls} value={siteId} onChange={(e) => setSiteId(e.target.value)}>
                <option value="">—</option>{sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </Field>
            <Field label={t.socPct}><Num value={tel.soc_pct} onChange={(v) => setTel({ ...tel, soc_pct: v })} /></Field>
            <Field label={t.tankPct}><Num value={tel.tank_pct} onChange={(v) => setTel({ ...tel, tank_pct: v })} /></Field>
            <label className="flex items-center gap-1 pb-2 text-sm text-slate-300"><input type="checkbox" checked={tel.grid_available} onChange={(e) => setTel({ ...tel, grid_available: e.target.checked })} />{t.gridAvailable}</label>
            <Ghost onClick={sendTel} disabled={!siteId}>{t.postTelemetry}</Ghost>
            <Btn busy={busy} onClick={makePlan} disabled={!siteId}>{busy ? t.planning : t.planNext24}</Btn>
          </div>
          <Note>{t.telemetryNote}</Note>
          <Err>{err}</Err>
          {msg && <Note>{msg}</Note>}
        </Card>

        {plan && (
          <>
            <Card title={t.recommendations}>
              <ul className="list-disc space-y-1 pl-5 text-sm text-slate-200">{plan.recommendations.map((r, i) => <li key={i}>{r}</li>)}</ul>
              {plan.warnings.map((w, i) => <p key={i} className="mt-1 text-xs text-amber-300">{w}</p>)}
              <div className="mt-3 grid grid-cols-2 gap-2 text-sm text-slate-300 sm:grid-cols-4">
                <div><b>{sm.pv_kwh}</b> kWh PV</div><div><b>{sm.demand_kwh}</b> kWh {t.demand}</div>
                <div><b>{sm.unserved_kwh}</b> kWh {t.unserved}</div><div>{t.heatwave}: <b>{sm.heatwave}</b> ({sm.max_temp_c}°C)</div>
              </div>
            </Card>
            <Card title={t.energyChart}>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={rows}>
                    <CartesianGrid stroke="#1e293b" /><XAxis dataKey="h" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                    <YAxis yAxisId="kw" stroke="#94a3b8" unit="kW" /><YAxis yAxisId="soc" orientation="right" domain={[0, 100]} stroke="#a3e635" unit="%" />
                    <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} /><Legend />
                    <Area yAxisId="kw" dataKey="pv_kw" name="PV" stroke="#fbbf24" fill="#fbbf24" fillOpacity={0.3} />
                    <Line yAxisId="kw" dataKey="demand_kw" name={t.demand} stroke="#f87171" dot={false} />
                    <Line yAxisId="kw" dataKey="served_kw" name={t.served} stroke="#38bdf8" dot={false} />
                    <Line yAxisId="soc" dataKey="soc_pct" name="SoC" stroke="#a3e635" dot={false} connectNulls />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </Card>
            {plan.deferred_loads.length > 0 && (
              <Card title={t.schedule}>
                <ul className="space-y-1 text-sm text-slate-300">{plan.deferred_loads.map((d) => <li key={d.load}><b>{d.load}</b>: {d.run_at.map((x) => x.slice(11, 16)).join(", ")}</li>)}</ul>
              </Card>
            )}
            {plan.water && (
              <Card title={t.water}><p className="text-sm text-slate-300">{t.tank}: {plan.water.tank_pct_now}% · {t.demand24}: {plan.water.demand_24h_l} L · {t.pumpHours}: {plan.water.pump_hours_needed}</p></Card>
            )}
          </>
        )}
      </div>
    </div>
  );
}
