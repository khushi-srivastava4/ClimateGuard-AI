const BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export async function call(path, opts = {}, timeoutMs = 90000) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const r = await fetch(BASE + path, { ...opts, signal: ctl.signal });
    const text = await r.text();
    let j = {};
    try { j = text ? JSON.parse(text) : {}; } catch { /* non-JSON error body */ }
    if (!r.ok) {
      const d = j.detail;
      throw new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map((x) => `${(x.loc || []).slice(1).join(".")}: ${x.msg}`).join("; ") : `Request failed (${r.status})`);
    }
    return j;
  } catch (e) {
    throw new Error(e.name === "AbortError" ? "The request timed out. The server may be waiting on a slow data provider; try again." : e.message);
  } finally {
    clearTimeout(timer);
  }
}
const qs = (o) => new URLSearchParams(Object.entries(o).filter(([, v]) => v != null && v !== "")).toString();
const send = (method, path, body) => call(path, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });

export const getRisk = (p) => call(`/insights/risk?${qs(p)}`);
export const getGrid = (p) => call(`/insights/grid?${qs(p)}`);
export const getNdvi = (p) => call(`/satellite/ndvi?${qs(p)}`, {}, 120000);
export const adviseV2 = (body) => send("POST", "/advise/v2", body);
export const chat = (body) => send("POST", "/assistant/chat", body);
export async function translateAdvisory(text, targetLanguage) {
  const result = await send("POST", "/assistant/translate", {
    text,
    target_language: targetLanguage,
  });
  if (typeof result.translated_text !== "string" || !result.translated_text.trim()) {
    throw new Error("Translation service returned an empty response.");
  }
  return result.translated_text;
}
export const reportOutcome = (body) => send("POST", "/analytics/outcomes", body);
export const getValidation = () => call("/analytics/validation");

async function voiceRequest(path, options = {}, signal, timeoutMs = 90000) {
  const controller = new AbortController();
  let timedOut = false;
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const forwardAbort = () => controller.abort();
  signal?.addEventListener("abort", forwardAbort, { once: true });
  if (signal?.aborted) controller.abort();

  try {
    const response = await fetch(BASE + path, { ...options, signal: controller.signal });
    if (!response.ok) {
      let payload = {};
      try { payload = await response.json(); } catch { /* non-JSON error body */ }
      const detail = payload.detail;
      const message = typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((item) => item.msg).join("; ")
          : `Voice request failed (${response.status})`;
      throw new Error(message);
    }
    return response;
  } catch (error) {
    if (timedOut) throw new Error("The voice request timed out. Please try again.");
    throw error;
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", forwardAbort);
  }
}

export async function getVoiceCapabilities(signal) {
  const response = await voiceRequest("/voice/capabilities", {}, signal, 15000);
  return response.json();
}

export async function transcribeAudio(audio, languageCode, signal) {
  const form = new FormData();
  form.append("audio", audio, "recording.wav");
  form.append("language_code", languageCode);
  const response = await voiceRequest("/voice/stt", { method: "POST", body: form }, signal);
  return response.json();
}

function validatePcmWav(buffer) {
  const view = new DataView(buffer);
  const chunkId = (offset) => String.fromCharCode(
    view.getUint8(offset),
    view.getUint8(offset + 1),
    view.getUint8(offset + 2),
    view.getUint8(offset + 3),
  );
  if (
    buffer.byteLength < 44
    || chunkId(0) !== "RIFF"
    || view.getUint32(4, true) !== buffer.byteLength - 8
    || chunkId(8) !== "WAVE"
  ) {
    throw new Error("Speech service returned invalid WAV audio.");
  }

  let format = null;
  let dataSize = null;
  let offset = 12;
  while (offset + 8 <= buffer.byteLength) {
    const id = chunkId(offset);
    const size = view.getUint32(offset + 4, true);
    const dataOffset = offset + 8;
    const end = dataOffset + size;
    if (size === 0xffffffff || end > buffer.byteLength) {
      throw new Error("Speech service returned incomplete WAV audio.");
    }

    if (id === "fmt ") {
      if (size < 16) throw new Error("Speech service returned invalid WAV audio.");
      const audioFormat = view.getUint16(dataOffset, true);
      const channels = view.getUint16(dataOffset + 2, true);
      const sampleRate = view.getUint32(dataOffset + 4, true);
      const blockAlign = view.getUint16(dataOffset + 12, true);
      const bitsPerSample = view.getUint16(dataOffset + 14, true);
      if (
        audioFormat !== 1
        || channels < 1
        || sampleRate < 1
        || ![8, 16, 24, 32].includes(bitsPerSample)
        || blockAlign !== channels * (bitsPerSample / 8)
      ) {
        throw new Error("Speech service returned unsupported WAV audio.");
      }
      format = { blockAlign };
    } else if (id === "data") {
      if (dataSize !== null) throw new Error("Speech service returned invalid WAV audio.");
      dataSize = size;
    }

    offset = end + (size % 2);
    if (offset > buffer.byteLength) throw new Error("Speech service returned incomplete WAV audio.");
  }

  if (
    offset !== buffer.byteLength
    || !format
    || !dataSize
    || dataSize % format.blockAlign !== 0
  ) {
    throw new Error("Speech service returned empty or invalid WAV audio.");
  }
}

export async function synthesizeSpeech(text, languageCode, signal) {
  const response = await voiceRequest("/voice/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, language_code: languageCode }),
  }, signal);
  if (!response.headers.get("content-type")?.includes("audio/wav")) {
    throw new Error("Speech service returned an unsupported audio format.");
  }
  const audio = await response.arrayBuffer();
  validatePcmWav(audio);
  return new Blob([audio], { type: "audio/wav" });
}

export const gridSites = () => call("/grid/sites");
export const saveSite = (b) => send("POST", "/grid/sites", b);
export const postTelemetry = (b) => send("POST", "/grid/telemetry", b);
export const gridPlan = (id, hours = 24) => call(`/grid/plan/${id}?hours=${hours}`, {}, 60000);

export const relief = {
  list: (kind) => call(`/relief/${kind}`),
  save: (kind, b) => send("POST", `/relief/${kind}`, b),
  remove: (kind, id) => send("DELETE", `/relief/${kind}/${id}`),
  hazards: () => call("/relief/hazards"),
  run: (b) => send("POST", "/relief/run", b),
  runs: () => call("/relief/runs"),
  orders: () => call("/relief/orders"),
  patchOrder: (id, status) => send("PATCH", `/relief/orders/${id}`, { status }),
};
