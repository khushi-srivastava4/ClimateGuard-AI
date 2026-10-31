export default function RiskCard({ label, value, tone, citation }) {
  const toneMap = {
    low: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/50',
    moderate: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/50',
    high: 'bg-red-500/20 text-red-300 border-red-500/50',
    unavailable: 'bg-slate-800 text-slate-400 border-slate-700',
  };

  return (
    <div className={`risk-card rounded-2xl border p-4 ${toneMap[tone] || toneMap.unavailable}`}>
      <div className="risk-card-label uppercase tracking-wide">{label}</div>
      <div className="risk-card-value mt-2 font-bold">{value}</div>
      {citation && <div className="mt-2 text-xs font-normal opacity-80">{citation}</div>}
    </div>
  );
}
