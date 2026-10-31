import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

export default function MandiChart({ data }) {
  if (!data || data.length === 0) {
    return <div className="rounded-2xl border border-slate-700 bg-slate-900 p-4 text-slate-300">Mandi data unavailable.</div>;
  }

  // One publication date => compare markets; several dates => show the price trend over time.
  const isTrend = new Set(data.map((point) => point.date)).size > 1;

  return (
    <div className="h-56 rounded-2xl border border-slate-700 bg-slate-900 p-4">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}>
          <XAxis dataKey={isTrend ? 'date' : 'market'} stroke="#94a3b8" tick={{ fontSize: 11 }} interval={0} />
          <YAxis stroke="#94a3b8" />
          <Tooltip />
          <Line type="monotone" dataKey="price" stroke="#34d399" strokeWidth={3} dot={{ r: 4 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
