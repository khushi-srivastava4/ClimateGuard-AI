export default function Schedule({ actions = [], loading = false, language = 'en', onStatusChange }) {
  const isHindi = language === 'hi';
  return (
    <div className="rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-lg">
      <h3 className="mb-4 flex items-center gap-2 text-lg font-semibold text-white">
        <span className="schedule-icon" aria-hidden="true">✦</span>
        {isHindi ? 'खेत कार्य योजना' : 'Field action plan'}
      </h3>
      {loading ? <p className="text-sm text-slate-400">{isHindi ? 'योजना लोड हो रही है…' : 'Loading plan…'}</p> :
        actions.length ? <div className="space-y-3">
          {actions.map((item) => (
            <div key={item.id || `${item.action}-${item.date}`} className="schedule-item rounded-xl bg-slate-800 px-3 py-3 text-sm text-slate-200">
              <div className="flex flex-wrap justify-between gap-2"><strong>{item.action || item.title}</strong><time>{item.date || item.due_date || '—'}</time></div>
              <p className="mt-1 text-slate-400">{item.reason || item.description}</p>
              {item.status && <div className="mt-2 flex items-center justify-between gap-2">
                <span className="text-xs capitalize text-slate-400">{item.status}</span>
                {onStatusChange && item.status !== 'completed' && item.status !== 'skipped' && <button type="button" className="rounded border border-emerald-500/50 px-2 py-1 text-xs text-emerald-200" onClick={() => onStatusChange(item.id, 'completed')}>{isHindi ? 'पूरा हुआ' : 'Mark complete'}</button>}
              </div>}
            </div>
          ))}
        </div> : <p className="text-sm text-slate-400">{isHindi ? 'उपलब्ध मौसम और फसल डेटा से कोई कार्य योजना तैयार नहीं है।' : 'No field actions are currently available from the selected crop and forecast data.'}</p>}
    </div>
  );
}
