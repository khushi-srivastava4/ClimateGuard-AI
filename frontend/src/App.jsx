import { useEffect, useMemo, useRef, useState } from 'react';
import Map from './components/Map';
import RiskCard from './components/RiskCard';
import Schedule from './components/Schedule';
import MandiChart from './components/MandiChart';
import LanguageToggle from './components/LanguageToggle';
import { apiRequest } from './api';
import { CROP_IDS } from './components/ui';
import en from './i18n/en.json';
import hi from './i18n/hi.json';

// Server-managed fields must not be sent back on update (stale farming_preferences would erase saved alert settings).
const editableFarmFields = ({ id, created_at, updated_at, farming_preferences, ...rest }) => rest;

const defaultCoords = { lat: 27.1767, lng: 78.0081 };
const emptyFarmDraft = () => ({
  name: '', location: '', state: '', district: '', crop: 'wheat',
  variety: '', growth_stage: '', sowing_date: '', soil_type: '',
  irrigation_method: '', area_hectares: '',
});

export default function App({ language: languageProp, onLanguageChange }) {
  // Language is owned by <Root/> when present (shared with the other tabs); standalone use still works.
  const [languageState, setLanguageState] = useState('en');
  const language = languageProp ?? languageState;
  const setLanguage = onLanguageChange ?? setLanguageState;
  const [selectedLocation, setSelectedLocation] = useState(defaultCoords);
  const [advice, setAdvice] = useState('');
  const [risk, setRisk] = useState({});
  const [weather, setWeather] = useState({});
  const [soil, setSoil] = useState({});
  const [market, setMarket] = useState({});
  const [adviceStatus, setAdviceStatus] = useState('unavailable');
  const [adviceProvider, setAdviceProvider] = useState('');
  const [sources, setSources] = useState([]);
  const [fieldPlan, setFieldPlan] = useState([]);
  const [chartData, setChartData] = useState([]);
  const [farms, setFarms] = useState([]);
  const [selectedFarm, setSelectedFarm] = useState(null);
  const [farmDraft, setFarmDraft] = useState(emptyFarmDraft);
  const [alerts, setAlerts] = useState([]);
  const [history, setHistory] = useState([]);
  const [historyError, setHistoryError] = useState('');
  const [historyLoading, setHistoryLoading] = useState(false);
  const [capabilities, setCapabilities] = useState({});
  const [alertPreferences, setAlertPreferences] = useState({ enabled: true, threshold: 70 });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [latitudeInput, setLatitudeInput] = useState(String(defaultCoords.lat));
  const [longitudeInput, setLongitudeInput] = useState(String(defaultCoords.lng));
  const [crop, setCrop] = useState('wheat');
  const adviceRequestRef = useRef(0);
  const historyRequestRef = useRef(null);

  const t = useMemo(() => (language === 'hi' ? hi : en), [language]);

  useEffect(() => {
    const controller = new AbortController();
    void fetchAdvice(selectedLocation, controller.signal);
    return () => controller.abort();
  }, [selectedLocation, language, crop, selectedFarm?.id]);

  useEffect(() => {
    const controller = new AbortController();
    apiRequest('/farms', { signal: controller.signal })
      .then(setFarms)
      .catch((requestError) => {
        if (!controller.signal.aborted) setError(requestError.message);
      });
    Promise.allSettled([
      apiRequest('/analytics/model-status', { signal: controller.signal }),
      apiRequest('/satellite/status', { signal: controller.signal }),
    ]).then(([modelResult, satelliteResult]) => {
      if (controller.signal.aborted) return;
      const unavailable = (result) => ({
        status: 'unavailable',
        reason: result.reason?.message || 'Status could not be loaded.',
      });
      setCapabilities({
        model: modelResult.status === 'fulfilled' ? modelResult.value : unavailable(modelResult),
        satellite: satelliteResult.status === 'fulfilled' ? satelliteResult.value : unavailable(satelliteResult),
      });
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    if (!selectedFarm) {
      setAlerts([]);
      setAlertPreferences({ enabled: true, threshold: 70 });
      return () => controller.abort();
    }
    apiRequest(`/alerts?farm_id=${encodeURIComponent(selectedFarm.id)}`, { signal: controller.signal })
      .then((result) => {
        if (!controller.signal.aborted) setAlerts(result);
      })
      .catch((requestError) => {
        if (!controller.signal.aborted) setError(requestError.message);
      });
    apiRequest(`/farms/${encodeURIComponent(selectedFarm.id)}/alert-preferences`, { signal: controller.signal })
      .then((preferences) => {
        if (!controller.signal.aborted) {
          setAlertPreferences({
            enabled: preferences.enabled !== false,
            threshold: preferences.threshold ?? 70,
          });
        }
      })
      .catch((requestError) => {
        if (!controller.signal.aborted) setError(requestError.message);
        });
    return () => controller.abort();
  }, [selectedFarm?.id]);

  useEffect(() => {
    historyRequestRef.current?.abort();
    historyRequestRef.current = null;
    setHistory([]);
    setHistoryError('');
    setHistoryLoading(false);
  }, [selectedLocation.lat, selectedLocation.lng]);

  const selectLocation = (coords) => {
    setSelectedFarm(null);
    setLatitudeInput(String(coords.lat));
    setLongitudeInput(String(coords.lng));
    setSelectedLocation(coords);
  };

  // Web Speech API hook can be added here for optional voice input/output.
  const fetchAdvice = async (coords, signal) => {
    const requestId = ++adviceRequestRef.current;
    setLoading(true);
    setError('');
    setAdvice('');
    setAdviceStatus('unavailable');
    setAdviceProvider('');
    setRisk({});
    setWeather({});
    setSoil({});
    setMarket({});
    setSources([]);
    setFieldPlan([]);
    setChartData([]);
    try {
      const data = await apiRequest('/advise', {
        method: 'POST',
        timeoutMs: 90000,
        signal,
        body: JSON.stringify({
          latitude: coords.lat,
          longitude: coords.lng,
          language,
          crop,
          mandicriteria: 'price',
          ...(selectedFarm ? { farm_id: selectedFarm.id } : {}),
        }),
      });
      if (signal?.aborted || requestId !== adviceRequestRef.current) return;
      if (
        !data.location
        || Math.abs(data.location.latitude - coords.lat) > 0.0001
        || Math.abs(data.location.longitude - coords.lng) > 0.0001
      ) {
        throw new Error('The advisory response does not match the selected field location. Please retry.');
      }
      setAdvice(data.advice || '');
      setAdviceStatus(data.advice_status || 'unavailable');
      setAdviceProvider(data.advice_provider || '');
      setRisk(data.risk || {});
      setWeather(data.weather || {});
      setSoil(data.soil || {});
      setMarket(data.market || {});
      setSources(Array.isArray(data.sources) ? data.sources : []);
      setFieldPlan(Array.isArray(data.field_plan) ? data.field_plan : []);
      const mandiData = Array.isArray(data.mandi) ? data.mandi : [];
      setChartData(mandiData);
    } catch (requestError) {
      if (signal?.aborted || requestId !== adviceRequestRef.current) return;
      if (requestError.name === 'AbortError') return;
      setError(requestError.message);
      setAdvice('');
      setAdviceStatus('unavailable');
      setRisk({});
      setWeather({ error: requestError.message });
      setSoil({ error: requestError.message });
      setMarket({ error: requestError.message });
      setFieldPlan([]);
      setChartData([]);
    } finally {
      if (requestId === adviceRequestRef.current) setLoading(false);
    }
  };

  const applyCoordinates = (event) => {
    event.preventDefault();
    const lat = Number(latitudeInput);
    const lng = Number(longitudeInput);
    if (!Number.isFinite(lat) || lat < -90 || lat > 90 || !Number.isFinite(lng) || lng < -180 || lng > 180) {
      setError(t.invalidCoordinates);
      return;
    }
    setSelectedLocation({ lat, lng });
    setSelectedFarm(null);
  };

  const createFarmProfile = async (event) => {
    event.preventDefault();
    try {
      const farm = await apiRequest('/farms', {
        method: 'POST',
        body: JSON.stringify({
          ...farmDraft,
          area_hectares: farmDraft.area_hectares ? Number(farmDraft.area_hectares) : null,
          sowing_date: farmDraft.sowing_date || null,
          latitude: selectedLocation.lat,
          longitude: selectedLocation.lng,
        }),
      });
      setFarms((current) => [...current, farm]);
      setSelectedFarm(farm);
      setCrop(farm.crop || crop);
      setFarmDraft({ ...emptyFarmDraft(), crop });
    } catch (requestError) {
      setError(requestError.message);
    }
  };

  const chooseFarm = (event) => {
    const farm = farms.find((item) => item.id === event.target.value) || null;
    setSelectedFarm(farm);
    if (!farm) {
      setFarmDraft(emptyFarmDraft());
      return;
    }
    setFarmDraft({
      ...emptyFarmDraft(),
      ...farm,
      area_hectares: farm.area_hectares == null ? '' : String(farm.area_hectares),
      sowing_date: farm.sowing_date || '',
    });
    if (farm.latitude != null && farm.longitude != null) {
      const coords = { lat: farm.latitude, lng: farm.longitude };
      setSelectedLocation(coords);
      setLatitudeInput(String(coords.lat));
      setLongitudeInput(String(coords.lng));
    }
    if (farm.crop) setCrop(farm.crop);
  };

  const updateFarmProfile = async () => {
    if (!selectedFarm) return;
    try {
      const updated = await apiRequest(`/farms/${encodeURIComponent(selectedFarm.id)}`, {
        method: 'PATCH',
        body: JSON.stringify({
          ...editableFarmFields(farmDraft),
          area_hectares: farmDraft.area_hectares ? Number(farmDraft.area_hectares) : null,
          sowing_date: farmDraft.sowing_date || null,
        }),
      });
      setFarms((current) => current.map((farm) => farm.id === updated.id ? updated : farm));
      setSelectedFarm(updated);
      if (updated.crop) setCrop(updated.crop);
    } catch (requestError) {
      setError(requestError.message);
    }
  };

  const deleteFarmProfile = async () => {
    if (!selectedFarm || !window.confirm(t.deleteFarmConfirm)) return;
    try {
      await apiRequest(`/farms/${encodeURIComponent(selectedFarm.id)}`, { method: 'DELETE' });
      setFarms((current) => current.filter((farm) => farm.id !== selectedFarm.id));
      setSelectedFarm(null);
      setFarmDraft(emptyFarmDraft());
    } catch (requestError) {
      setError(requestError.message);
    }
  };

  const updateActionStatus = async (actionId, status) => {
    try {
      await apiRequest(`/actions/${encodeURIComponent(actionId)}`, {
        method: 'PATCH',
        body: JSON.stringify({ status }),
      });
      const updatedActions = await apiRequest(`/farms/${encodeURIComponent(selectedFarm.id)}/actions`);
      setFieldPlan(updatedActions);
    } catch (requestError) {
      setError(requestError.message);
    }
  };

  const updateAlert = async (alertId, isRead) => {
    try {
      const updated = await apiRequest(`/alerts/${encodeURIComponent(alertId)}`, {
        method: 'PATCH',
        body: JSON.stringify({ is_read: isRead }),
      });
      setAlerts((current) => current.map((alert) => alert.id === updated.id ? updated : alert));
    } catch (requestError) {
      setError(requestError.message);
    }
  };

  const saveAlertPreferences = async () => {
    if (!selectedFarm) return;
    try {
      const saved = await apiRequest(`/farms/${encodeURIComponent(selectedFarm.id)}/alert-preferences`, {
        method: 'PUT',
        body: JSON.stringify(alertPreferences),
      });
      setAlertPreferences(saved);
    } catch (requestError) {
      setError(requestError.message);
    }
  };

  const loadHistory = async () => {
    historyRequestRef.current?.abort();
    const controller = new AbortController();
    historyRequestRef.current = controller;
    const requestId = historyRequestRef.current;
    setHistoryLoading(true);
    setHistoryError('');
    try {
      const query = new URLSearchParams({
        latitude: String(selectedLocation.lat),
        longitude: String(selectedLocation.lng),
        days: '30',
      });
      const result = await apiRequest(`/history/weather?${query}`, {
        signal: controller.signal,
        timeoutMs: 25000,
      });
      if (controller.signal.aborted || historyRequestRef.current !== requestId) return;
      setHistory(Array.isArray(result.daily) ? result.daily : []);
    } catch (requestError) {
      if (controller.signal.aborted || historyRequestRef.current !== requestId) return;
      setHistoryError(requestError.message);
      setHistory([]);
    } finally {
      if (historyRequestRef.current === requestId) setHistoryLoading(false);
    }
  };
  const scoreTone = (value) => value == null ? 'unavailable' : value >= 75 ? 'high' : value >= 40 ? 'moderate' : 'low';
  const scoreLabel = (value) => value == null ? t.unavailable : `${value}/100`;
  const forecast = Array.isArray(weather.daily) ? weather.daily : [];
  const soilProperties = soil.properties && typeof soil.properties === 'object' ? Object.entries(soil.properties) : [];

  return (
    <div className="dashboard-shell min-h-screen p-4 text-slate-200 sm:p-6 lg:p-8">
      <div className="mx-auto max-w-7xl">
        <header className="brand-header mb-6 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="brand-mark" aria-hidden="true">
              <svg viewBox="0 0 48 48" fill="none">
                <path d="M37 9C24 10 13 14 10 24c-2 7 3 13 10 12 11-2 14-15 17-27Z" fill="currentColor" opacity=".22" />
                <path d="M11 37c5-10 12-17 23-25M17 29c1 4 4 6 8 6M22 23c-1-4-1-7 1-10" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
              </svg>
            </div>
            <div>
              <p className="brand-eyebrow">{t.brandKicker}</p>
              <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{t.title}</h1>
              <p className="brand-subtitle">{t.brandSubtitle}</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className={`sync-pill ${weather.retrieved_at ? 'is-ready' : ''}`}>
              <span className="sync-dot" />
              {loading ? t.statusUpdating : weather.retrieved_at ? t.statusLoaded : t.statusWaiting}
            </div>
            <LanguageToggle language={language} onChange={setLanguage} />
          </div>
        </header>

        <section className="field-banner mb-6">
          <div className="field-banner-copy">
            <span className="field-banner-kicker">{t.fieldGlance}</span>
            <h2>{selectedFarm?.name || 'Plan with the season, not guesswork.'}</h2>
            <p>{selectedFarm ? `${selectedFarm.location}${selectedFarm.state ? ` · ${selectedFarm.state}` : ''}` : 'Local forecast signals, transparent risk indicators and practical field checks.'}</p>
          </div>
          <div className="field-banner-meta">
            <span className="field-meta-label">{t.activeCrop}</span>
            <strong>{t[`crop_${crop}`] || crop}</strong>
            <span className="field-meta-divider" />
            <span className="field-meta-label">{t.fieldLocationLabel}</span>
            <strong>{selectedLocation.lat.toFixed(3)}°, {selectedLocation.lng.toFixed(3)}°</strong>
          </div>
          <div className="field-banner-art" aria-hidden="true">
            <span className="sun-disc" />
            <span className="hill hill-back" />
            <span className="hill hill-front" />
            <span className="crop-lines" />
          </div>
        </section>

        <div className="mb-6 grid gap-6 lg:grid-cols-2">
          <section className="rounded-3xl border border-slate-800 bg-slate-900 p-4">
            <h2 className="mb-3 text-lg font-semibold">{t.farmProfiles}</h2>
            <label className="mb-3 block text-sm">{t.selectedFarm}
              <select aria-label={t.selectedFarm} className="mt-1 block w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2" value={selectedFarm?.id || ''} onChange={chooseFarm}>
                <option value="">{t.unregisteredLocation}</option>
                {farms.map((farm) => <option value={farm.id} key={farm.id}>{farm.name} — {farm.location}</option>)}
              </select>
            </label>
            <form onSubmit={createFarmProfile} className="grid gap-3 sm:grid-cols-2">
              <input aria-label={t.farmName} required maxLength={120} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2" placeholder={t.farmName} value={farmDraft.name} onChange={(event) => setFarmDraft({ ...farmDraft, name: event.target.value })} />
              <input aria-label={t.farmLocation} required maxLength={240} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2" placeholder={t.farmLocation} value={farmDraft.location} onChange={(event) => setFarmDraft({ ...farmDraft, location: event.target.value })} />
              <input aria-label={t.farmState} maxLength={100} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2" placeholder={t.farmState} value={farmDraft.state} onChange={(event) => setFarmDraft({ ...farmDraft, state: event.target.value })} />
              <input aria-label={t.farmDistrict} maxLength={100} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2" placeholder={t.farmDistrict} value={farmDraft.district} onChange={(event) => setFarmDraft({ ...farmDraft, district: event.target.value })} />
              <select aria-label={t.farmCropAria} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2" value={farmDraft.crop} onChange={(event) => setFarmDraft({ ...farmDraft, crop: event.target.value })}>
                {CROP_IDS.map((id) => <option key={id} value={id}>{t[`crop_${id}`]}</option>)}
              </select>
              <input aria-label={t.cropVariety} maxLength={120} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2" placeholder={t.cropVariety} value={farmDraft.variety} onChange={(event) => setFarmDraft({ ...farmDraft, variety: event.target.value })} />
              <input aria-label={t.growthStage} maxLength={120} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2" placeholder={t.growthStage} value={farmDraft.growth_stage} onChange={(event) => setFarmDraft({ ...farmDraft, growth_stage: event.target.value })} />
              <input aria-label={t.sowingDate} type="date" className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2" value={farmDraft.sowing_date} onChange={(event) => setFarmDraft({ ...farmDraft, sowing_date: event.target.value })} />
              <input aria-label={t.areaHectares} type="number" step="any" min="0.001" className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2" placeholder={t.areaHectares} value={farmDraft.area_hectares} onChange={(event) => setFarmDraft({ ...farmDraft, area_hectares: event.target.value })} />
              <input aria-label={t.soilType} maxLength={120} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2" placeholder={t.soilType} value={farmDraft.soil_type} onChange={(event) => setFarmDraft({ ...farmDraft, soil_type: event.target.value })} />
              <input aria-label={t.irrigationMethod} maxLength={120} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2" placeholder={t.irrigationMethod} value={farmDraft.irrigation_method} onChange={(event) => setFarmDraft({ ...farmDraft, irrigation_method: event.target.value })} />
              <button type="submit" className="rounded-lg bg-emerald-400 px-4 py-2 font-semibold text-slate-950 sm:col-span-2">{t.saveFarm}</button>
            </form>
            {selectedFarm && <div className="mt-3 flex gap-2">
              <button type="button" className="rounded-lg border border-emerald-500/50 px-3 py-2 text-sm text-emerald-200" onClick={updateFarmProfile}>{t.updateFarm}</button>
              <button type="button" className="rounded-lg border border-red-500/50 px-3 py-2 text-sm text-red-200" onClick={deleteFarmProfile}>{t.deleteFarm}</button>
            </div>}
          </section>

          <section className="rounded-3xl border border-slate-800 bg-slate-900 p-4">
            <h2 className="mb-3 text-lg font-semibold">{t.farmAlerts}</h2>
            {selectedFarm ? <>
              <div className="mb-3 flex flex-wrap items-center gap-3 text-sm">
                <label className="flex items-center gap-2"><input type="checkbox" checked={alertPreferences.enabled} onChange={(event) => setAlertPreferences({ ...alertPreferences, enabled: event.target.checked })} /> {t.enableRiskAlerts}</label>
                <label className="flex items-center gap-2">{t.alertThreshold}
                  <input aria-label={t.alertThreshold} type="number" min="1" max="100" className="w-20 rounded border border-slate-700 bg-slate-950 px-2 py-1" value={alertPreferences.threshold} onChange={(event) => setAlertPreferences({ ...alertPreferences, threshold: Number(event.target.value) })} />
                </label>
                <button type="button" className="rounded border border-emerald-500/50 px-3 py-1 text-emerald-200" onClick={saveAlertPreferences}>{t.save}</button>
              </div>
              <div className="max-h-40 space-y-2 overflow-auto text-sm">
                {alerts.length ? alerts.map((alert) => <div className="flex items-start justify-between gap-2 rounded-lg bg-slate-800 p-2" key={alert.id}>
                  <div><strong>{alert.title}</strong><p className="text-slate-400">{alert.message}</p><time className="text-xs text-slate-500">{new Date(alert.created_at).toLocaleString()}</time></div>
                  <button type="button" className="shrink-0 rounded border border-slate-600 px-2 py-1 text-xs" onClick={() => updateAlert(alert.id, !alert.is_read)}>{alert.is_read ? t.markUnread : t.markRead}</button>
                </div>) : <p className="text-slate-400">{t.noStoredAlerts}</p>}
              </div>
            </> : <p className="text-sm text-slate-400">{t.selectFarmForAlerts}</p>}
          </section>
        </div>

        {error && <div role="alert" className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-red-500/40 bg-red-950/40 p-4 text-red-200">
          <span>{error}</span>
          <button type="button" className="rounded-lg border border-red-400/50 px-3 py-1" onClick={() => fetchAdvice(selectedLocation)}>{t.retry}</button>
        </div>}

        <div className="grid gap-6 lg:grid-cols-[1.4fr_0.8fr]">
          <section className="rounded-3xl border border-slate-800 bg-slate-900 p-4 shadow-xl">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-lg font-semibold">{t.selectLocation}</h2>
              <span className="text-sm text-slate-400">{selectedLocation.lat.toFixed(4)}, {selectedLocation.lng.toFixed(4)}</span>
            </div>
            <Map onSelect={selectLocation} selected={[selectedLocation.lat, selectedLocation.lng]} />
            <p className="mt-3 text-sm text-slate-400">{t.mapHint}</p>
            <form onSubmit={applyCoordinates} className="mt-4 flex flex-wrap items-end gap-3">
              <label className="text-sm">{t.latitude}
                <input aria-label={t.latitude} className="mt-1 block w-36 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2" type="number" step="any" min="-90" max="90" value={latitudeInput} onChange={(event) => setLatitudeInput(event.target.value)} />
              </label>
              <label className="text-sm">{t.longitude}
                <input aria-label={t.longitude} className="mt-1 block w-36 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2" type="number" step="any" min="-180" max="180" value={longitudeInput} onChange={(event) => setLongitudeInput(event.target.value)} />
              </label>
              <button className="rounded-lg bg-emerald-400 px-4 py-2 font-semibold text-slate-950" type="submit">{t.applyLocation}</button>
              <label className="text-sm">{t.crop}
                <select className="mt-1 block rounded-lg border border-slate-700 bg-slate-950 px-3 py-2" value={crop} onChange={(event) => setCrop(event.target.value)}>
                  {CROP_IDS.map((id) => <option key={id} value={id}>{t[`crop_${id}`]}</option>)}
                </select>
              </label>
            </form>
          </section>

          <aside className="space-y-6">
            <div className="rounded-3xl border border-slate-800 bg-slate-900 p-4">
              <h2 className="mb-4 text-lg font-semibold">{t.riskOverview}</h2>
              <p className="mb-3 text-sm text-slate-400">{loading ? t.loading : (risk.assessment_period || t.assessmentUnavailable)}. {t.heuristicNotice}</p>
              <div className="grid grid-cols-2 gap-3">
                <RiskCard label={t.heat} value={scoreLabel(risk.heat_wave)} tone={scoreTone(risk.heat_wave)} />
                <RiskCard label={t.heavyRain} value={scoreLabel(risk.flood)} tone={scoreTone(risk.flood)} />
                <RiskCard label={t.waterlogging} value={scoreLabel(risk.water_logging)} tone={scoreTone(risk.water_logging)} />
                <RiskCard label={t.drought} value={scoreLabel(risk.drought)} tone={scoreTone(risk.drought)} />
                <RiskCard label={t.overall} value={scoreLabel(risk.overall)} tone={scoreTone(risk.overall)} />
              </div>
              {risk.reasons?.length > 0 && <ul className="mt-4 space-y-2 text-sm text-slate-300">{risk.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>}
              {risk.data_quality?.length > 0 && <div className="mt-4 border-t border-slate-700 pt-3 text-sm text-amber-200">{risk.data_quality.map((item) => <p key={item}>{item}</p>)}</div>}
            </div>
            <Schedule actions={fieldPlan} loading={loading} language={language} onStatusChange={selectedFarm ? updateActionStatus : undefined} />
          </aside>
        </div>

        <div className="mt-6 grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
          <section className="rounded-3xl border border-slate-800 bg-slate-900 p-4">
            <h2 className="mb-4 text-lg font-semibold">{t.advisory}</h2>
            {loading ? (
              <div className="flex items-center gap-2 text-slate-300">
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-emerald-300 border-t-transparent" />
                {t.loading}
              </div>
            ) : (
              <div className="space-y-3 text-slate-200">
                <p className={adviceStatus === 'generated' ? 'text-emerald-300' : 'text-amber-300'}>
                  {adviceStatus === 'generated'
                    ? `${t.generatedByAi}${adviceProvider ? ` (${adviceProvider})` : ''}`
                    : adviceStatus === 'fallback'
                      ? (language === 'hi' ? 'AI उपलब्ध नहीं था — नियम-आधारित सारांश' : 'AI model unavailable — rule-based summary, not AI-generated')
                      : t.advisoryUnavailable}
                </p>
                <p>{advice || t.advisoryUnavailable}</p>
              </div>
            )}
          </section>

          <section className="space-y-6 rounded-3xl border border-slate-800 bg-slate-900 p-4">
            <div>
              <h2 className="mb-2 text-lg font-semibold">{t.forecast}</h2>
              {loading ? <p className="text-slate-400">{t.loading}</p> : weather.error ? <p className="text-amber-300">{weather.error}</p> : forecast.length ? <div className="max-h-56 space-y-2 overflow-auto text-sm">
                {forecast.map((day) => <div key={day.date} className="flex flex-wrap justify-between gap-2 rounded-lg bg-slate-800 px-3 py-2">
                  <span>{day.date}</span><span>{day.temperature_2m_min ?? '—'}–{day.temperature_2m_max ?? '—'}°C</span><span>{day.precipitation_sum ?? '—'} mm rain</span>
                </div>)}
              </div> : <p className="text-slate-400">{t.unavailable}</p>}
              {weather.retrieved_at && <p className="mt-2 text-xs text-slate-400">{t.retrieved}: {new Date(weather.retrieved_at).toLocaleString(language === 'hi' ? 'hi-IN' : 'en-IN')}</p>}
              <div className="mt-3">
                <button type="button" className="rounded border border-slate-600 px-3 py-1 text-sm" disabled={historyLoading} onClick={loadHistory}>{historyLoading ? t.historyLoading : t.loadHistory}</button>
                {historyError && <p role="alert" className="mt-2 text-sm text-amber-300">{historyError}</p>}
                {history.length > 0 && <div className="mt-2 max-h-40 space-y-1 overflow-auto text-xs text-slate-300">
                  <p className="text-slate-400">{t.historicalReanalysis}</p>
                  {history.map((day) => <div className="flex justify-between gap-2 rounded bg-slate-800 px-2 py-1" key={day.date}><span>{day.date}</span><span>{day.temperature_2m_min ?? '—'}–{day.temperature_2m_max ?? '—'}°C · {day.precipitation_sum ?? '—'} mm</span></div>)}
                </div>}
              </div>
            </div>
            <div>
              <h2 className="mb-2 text-lg font-semibold">{t.soilEstimates}</h2>
              {loading ? <p className="text-slate-400">{t.loading}</p> : soil.error ? <p className="text-amber-300">{soil.error}</p> : soilProperties.length ? <>
                <p className="mb-2 text-xs text-slate-400">{soil.interpretation}</p>
                <ul className="grid grid-cols-2 gap-2 text-sm">{soilProperties.map(([name, value]) => <li className="rounded-lg bg-slate-800 p-2" key={name}>{name}: {value}</li>)}</ul>
              </> : <p className="text-slate-400">{t.unavailable}</p>}
            </div>
            <div>
              <h2 className="mb-2 text-lg font-semibold">{t.mandiPrices}</h2>
              {loading ? <p className="mb-2 text-sm text-slate-400">{t.loading}</p> : market.error && <p className="mb-2 text-sm text-amber-300">{market.error}</p>}
              {!loading && <MandiChart data={chartData} />}
            </div>
            <div className="text-xs text-slate-400">
              {sources.length ? sources.map((item) => <div key={item}>{item}</div>) : t.sourcesUnavailable}
            </div>
            <div className="border-t border-slate-700 pt-3 text-xs text-slate-400">
              <p>{t.mlValidation}: {capabilities.model?.status || t.unavailable} — {capabilities.model?.reason || ''}</p>
              <p>{t.satelliteMonitoring}: {capabilities.satellite?.status || t.unavailable}; {t.ndvi}: {capabilities.satellite?.ndvi || t.unavailable} — {capabilities.satellite?.reason || ''}</p>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
