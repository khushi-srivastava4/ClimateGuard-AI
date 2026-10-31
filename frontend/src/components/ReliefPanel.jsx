import { useEffect, useMemo, useState } from "react";
import RouteMap from "./RouteMap";
import { Btn, Card, Err, Field, Ghost, inputCls, Note, Num, Txt } from "./ui";
import { relief } from "../api/insights";

const LEVEL_CLS = { none: "text-emerald-300", watch: "text-yellow-300", high: "text-orange-300", severe: "text-red-400", unknown: "text-slate-400" };

export default function ReliefPanel({ t }) {
  const [pick, setPick] = useState(null);
  const [zones, setZones] = useState([]); const [sups, setSups] = useState([]); const [fleet, setFleet] = useState([]);
  const [orders, setOrders] = useState([]); const [haz, setHaz] = useState([]); const [run, setRun] = useState(null);
  const [zf, setZf] = useState({ name: "", item: "water", qty: 100 });
  const [sf, setSf] = useState({ name: "", inventory_url: "", webhook_url: "", item: "water", qty: 500 });
  const [vf, setVf] = useState({ vehicle_id: "", status: "available" });
  const [opt, setOpt] = useState({ min_level: "high", dry_run: true });
  const [busy, setBusy] = useState(false); const [err, setErr] = useState("");

  const load = () => Promise.all([relief.list("zones"), relief.list("suppliers"), relief.list("fleet"), relief.orders()])
    .then(([z, s, f, o]) => { setZones(z); setSups(s); setFleet(f); setOrders(o); }).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);

  const guard = async (fn) => { setErr(""); try { await fn(); await load(); } catch (e) { setErr(e.message); } };
  const needPick = () => { if (!pick) throw new Error(t.pickFirst); };

  const addZone = () => guard(async () => { needPick(); await relief.save("zones", { name: zf.name, ...pick, needs: [{ item: zf.item, qty: zf.qty }] }); });
  const addSup = () => guard(async () => {
    needPick();
    const b = { name: sf.name, ...pick, stock: sf.inventory_url ? [] : [{ item: sf.item, qty: sf.qty }] };
    if (sf.inventory_url) b.inventory_url = sf.inventory_url;
    if (sf.webhook_url) b.webhook_url = sf.webhook_url;
    await relief.save("suppliers", b);
  });
  const addVeh = () => guard(async () => { needPick(); await relief.save("fleet", { vehicle_id: vf.vehicle_id, ...pick, status: vf.status }); });

  async function checkHaz() { setBusy(true); setErr(""); try { setHaz(await relief.hazards()); } catch (e) { setErr(e.message); } finally { setBusy(false); } }
  async function runAgent() {
    setBusy(true); setErr(""); setRun(null);
    try { setRun(await relief.run(opt)); await load(); } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }

  const points = useMemo(() => [
    ...zones.map((z) => ({ kind: "zone", lat: z.lat, lon: z.lon, label: z.name })),
    ...sups.map((s) => ({ kind: "supplier", lat: s.lat, lon: s.lon, label: s.name })),
    ...fleet.map((v) => ({ kind: "vehicle", lat: v.lat, lon: v.lon, label: v.id })),
  ], [zones, sups, fleet]);
  const routes = (run?.order_details || orders.slice(0, 5)).map((o) => ({ ...o.route }));

  return (
    <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
      <div className="space-y-4">
        <Card title={t.reliefTitle} hint={t.reliefHint}>
          <RouteMap points={points} routes={routes} pick={pick} onSelect={(lat, lon) => setPick({ lat, lon })} />
          <Note>{pick ? `${t.picked}: ${pick.lat.toFixed(4)}, ${pick.lon.toFixed(4)}` : t.pickFirst} · <span className="text-red-400">● {t.zone}</span> <span className="text-green-400">● {t.supplier}</span> <span className="text-blue-400">● {t.vehicle}</span></Note>
        </Card>
        <Card title={t.setup}>
          <div className="grid gap-4 md:grid-cols-3">
            <div className="space-y-2"><h3 className="font-semibold text-red-300">{t.zone}</h3>
              <Field label={t.name}><Txt value={zf.name} onChange={(v) => setZf({ ...zf, name: v })} /></Field>
              <Field label={t.needItem}><Txt value={zf.item} onChange={(v) => setZf({ ...zf, item: v })} /></Field>
              <Field label={t.qty}><Num value={zf.qty} onChange={(v) => setZf({ ...zf, qty: v })} /></Field>
              <Btn onClick={addZone} disabled={!zf.name}>{t.add}</Btn></div>
            <div className="space-y-2"><h3 className="font-semibold text-green-300">{t.supplier}</h3>
              <Field label={t.name}><Txt value={sf.name} onChange={(v) => setSf({ ...sf, name: v })} /></Field>
              <Field label={t.inventoryUrl}><Txt value={sf.inventory_url} onChange={(v) => setSf({ ...sf, inventory_url: v })} placeholder="https://…/stock.json" /></Field>
              {!sf.inventory_url && <><Field label={t.needItem}><Txt value={sf.item} onChange={(v) => setSf({ ...sf, item: v })} /></Field><Field label={t.stockQty}><Num value={sf.qty} onChange={(v) => setSf({ ...sf, qty: v })} /></Field></>}
              <Field label={t.webhookUrl}><Txt value={sf.webhook_url} onChange={(v) => setSf({ ...sf, webhook_url: v })} placeholder="https://…/orders" /></Field>
              <Btn onClick={addSup} disabled={!sf.name}>{t.add}</Btn></div>
            <div className="space-y-2"><h3 className="font-semibold text-blue-300">{t.vehicle}</h3>
              <Field label={t.vehicleId}><Txt value={vf.vehicle_id} onChange={(v) => setVf({ ...vf, vehicle_id: v })} /></Field>
              <Field label={t.status}><select className={inputCls} value={vf.status} onChange={(e) => setVf({ ...vf, status: e.target.value })}>{["available", "assigned", "offline"].map((s) => <option key={s}>{s}</option>)}</select></Field>
              <Btn onClick={addVeh} disabled={!vf.vehicle_id}>{t.updatePosition}</Btn></div>
          </div>
          <Note>{t.setupNote}</Note>
          <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-300">
            {[["zones", zones], ["suppliers", sups], ["fleet", fleet]].flatMap(([k, arr]) => arr.map((x) => (
              <span key={k + x.id} className="rounded-full border border-slate-700 px-2 py-1">{k === "fleet" ? x.id : x.name} <button className="ml-1 text-slate-400" onClick={() => guard(() => relief.remove(k, x.id))}>✕</button></span>)))}
          </div>
        </Card>
      </div>

      <div className="space-y-4">
        <Card title={t.agentTitle} hint={t.agentHint}>
          <div className="flex flex-wrap items-end gap-3">
            <Field label={t.minLevel}><select className={inputCls} value={opt.min_level} onChange={(e) => setOpt({ ...opt, min_level: e.target.value })}>{["watch", "high", "severe"].map((l) => <option key={l}>{l}</option>)}</select></Field>
            <label className="flex items-center gap-1 pb-2 text-sm text-slate-300"><input type="checkbox" checked={opt.dry_run} onChange={(e) => setOpt({ ...opt, dry_run: e.target.checked })} />{t.dryRun}</label>
            <Ghost onClick={checkHaz} disabled={busy}>{t.checkHazards}</Ghost>
            <Btn busy={busy} onClick={runAgent}>{busy ? t.running : t.runAgent}</Btn>
          </div>
          <Err>{err}</Err>
          {haz.length > 0 && <ul className="mt-3 space-y-1 text-sm">{haz.map((h) => <li key={h.zone}><b>{h.name || h.zone}</b>: <span className={LEVEL_CLS[h.level]}>{h.level}</span> <span className="text-slate-400">{(h.reasons || []).join("; ")}</span></li>)}</ul>}
        </Card>
        {run && (
          <Card title={t.agentLog}>
            <ol className="space-y-1 text-sm">
              {run.steps.map((s, i) => <li key={i} className={s.ok ? "text-slate-200" : "text-amber-300"}><span className="mr-2 rounded bg-slate-800 px-1.5 py-0.5 text-xs uppercase text-slate-400">{s.stage}</span>{s.msg}</li>)}
            </ol>
            {run.dry_run && <Note>{t.dryRunNote}</Note>}
          </Card>
        )}
        <Card title={t.orders}>
          {orders.length === 0 ? <Note>{t.noOrders}</Note> : (
            <ul className="space-y-2 text-sm">
              {orders.slice(0, 8).map((o) => (
                <li key={o.id} className="rounded-lg border border-slate-800 p-2">
                  <b>{o.items.map((i) => `${i.item} ×${i.qty}`).join(", ")}</b> → {o.zone_name}
                  <div className="text-slate-400">{o.supplier_name} · {o.route.distance_km} km · {o.route.duration_h} h · {o.vehicle || t.noVehicle}</div>
                  <div className="text-slate-300">{o.status}</div>
                  {!["delivered", "cancelled"].includes(o.status) && <Ghost className="mt-1" onClick={() => guard(() => relief.patchOrder(o.id, "delivered"))}>{t.markDelivered}</Ghost>}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
