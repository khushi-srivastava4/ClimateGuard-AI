import { useState } from 'react';
import App from './App';
import ClimatePanel from './components/ClimatePanel';
import AssistantPanel from './components/AssistantPanel';
import GridPanel from './components/GridPanel';
import ReliefPanel from './components/ReliefPanel';
import { CROP_IDS, LANG_OPTIONS } from './components/ui';
import { opsLabels } from './i18n/ops';
import en from './i18n/en.json';
import hi from './i18n/hi.json';
import './insights.css';

const TABS = ['farm', 'climate', 'assistant', 'grid', 'relief'];

export default function Root() {
  const [tab, setTab] = useState('farm');
  const [language, setLanguage] = useState('en');
  const t = opsLabels(language);
  const dict = language === 'hi' ? hi : en;
  const tc = Object.fromEntries(CROP_IDS.map((id) => [id, dict['crop_' + id] || en['crop_' + id]]));

  return (
    <div className="climateguard-shell min-h-screen bg-slate-950">
      <nav className="climateguard-nav sticky top-0 z-[1000] flex flex-wrap items-center gap-2 border-b border-slate-800 bg-slate-950/95 px-4 py-2 backdrop-blur">
        {TABS.map((id) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`climateguard-tab rounded-full px-4 py-1.5 text-sm font-medium ${tab === id ? 'is-active bg-emerald-500 text-slate-950' : 'border border-slate-700 text-slate-300 hover:bg-slate-800'}`}
          >
            {t['tab' + id[0].toUpperCase() + id.slice(1)]}
          </button>
        ))}
        <select
          aria-label="Language"
          className="climateguard-language ml-auto rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-200"
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
        >
          {LANG_OPTIONS.map(([code, name]) => <option key={code} value={code}>{name}</option>)}
        </select>
      </nav>
      {tab === 'farm' && <App language={language} onLanguageChange={setLanguage} />}
      {tab !== 'farm' && (
        <main className="dashboard-shell mx-auto max-w-7xl p-4 text-slate-200 sm:p-6">
          {tab === 'climate' && <ClimatePanel language={language} t={t} tc={tc} />}
          {tab === 'assistant' && <AssistantPanel language={language} t={t} tc={tc} />}
          {tab === 'grid' && <GridPanel t={t} />}
          {tab === 'relief' && <ReliefPanel t={t} />}
        </main>
      )}
    </div>
  );
}
