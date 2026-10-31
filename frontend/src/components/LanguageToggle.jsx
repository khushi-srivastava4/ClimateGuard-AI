export default function LanguageToggle({ language, onChange }) {
  return (
    <div className="language-toggle flex items-center gap-2 rounded-full border border-slate-700 bg-slate-900 px-2 py-1.5">
      <button
        className={`rounded-full px-3 py-1 text-sm ${language === 'en' ? 'bg-emerald-500 text-slate-950' : 'text-slate-300'}`}
        onClick={() => onChange('en')}
      >
        EN
      </button>
      <button
        className={`rounded-full px-3 py-1 text-sm ${language === 'hi' ? 'bg-emerald-500 text-slate-950' : 'text-slate-300'}`}
        onClick={() => onChange('hi')}
      >
        HI
      </button>
    </div>
  );
}
