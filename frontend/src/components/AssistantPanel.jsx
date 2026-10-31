import { useEffect, useRef, useState } from "react";
import FarmMap from "./FarmMap";
import { Btn, Card, CROP_IDS, Err, Field, Ghost, inputCls, Note, Txt, VOICE_LANGUAGES } from "./ui";
import { chat, getVoiceCapabilities, synthesizeSpeech, transcribeAudio, translateAdvisory } from "../api/insights";

const MAX_RECORDING_SECONDS = 30;
const WAV_SAMPLE_RATE = 16000;

async function recordingToWav(blob) {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) throw new Error("Audio conversion is not supported by this browser.");

  const context = new AudioContextClass();
  try {
    const audio = await context.decodeAudioData(await blob.arrayBuffer());
    if (!audio.length || audio.duration < 0.2 || audio.duration > MAX_RECORDING_SECONDS) {
      throw new Error("Recording must be between 0.2 and 30 seconds.");
    }

    const sampleCount = Math.ceil(audio.length * WAV_SAMPLE_RATE / audio.sampleRate);
    const pcm = new ArrayBuffer(44 + sampleCount * 2);
    const view = new DataView(pcm);
    const write = (offset, value) => {
      for (let i = 0; i < value.length; i += 1) view.setUint8(offset + i, value.charCodeAt(i));
    };
    write(0, "RIFF");
    view.setUint32(4, 36 + sampleCount * 2, true);
    write(8, "WAVE");
    write(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, WAV_SAMPLE_RATE, true);
    view.setUint32(28, WAV_SAMPLE_RATE * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    write(36, "data");
    view.setUint32(40, sampleCount * 2, true);

    const channels = Array.from({ length: audio.numberOfChannels }, (_, i) => audio.getChannelData(i));
    const ratio = audio.sampleRate / WAV_SAMPLE_RATE;
    for (let i = 0; i < sampleCount; i += 1) {
      const position = i * ratio;
      const left = Math.floor(position);
      const right = Math.min(left + 1, audio.length - 1);
      const fraction = position - left;
      let sample = 0;
      for (const channel of channels) {
        sample += channel[left] * (1 - fraction) + channel[right] * fraction;
      }
      sample /= channels.length;
      const value = Math.max(-1, Math.min(1, sample));
      view.setInt16(44 + i * 2, value < 0 ? value * 0x8000 : value * 0x7fff, true);
    }
    return new Blob([pcm], { type: "audio/wav" });
  } finally {
    await context.close();
  }
}

function stopTracks(stream) {
  stream?.getTracks().forEach((track) => track.stop());
}

export default function AssistantPanel({ language, t, tc }) {
  const initialVoiceLanguage = VOICE_LANGUAGES.find((item) => item.chatCode === language)?.code || "en-IN";
  const [loc, setLoc] = useState({ lat: 27.1767, lon: 78.0081 });
  const [form, setForm] = useState({ crop: "wheat", stage: "", soil_type: "", state: "" });
  const [msgs, setMsgs] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [permissionPending, setPermissionPending] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [translating, setTranslating] = useState(false);
  const [speakOn, setSpeakOn] = useState(true);
  const [voiceLanguage, setVoiceLanguage] = useState(initialVoiceLanguage);
  const [capabilities, setCapabilities] = useState(null);
  const [capabilityError, setCapabilityError] = useState("");
  const [playbackStatus, setPlaybackStatus] = useState("idle");
  const [err, setErr] = useState("");
  const rec = useRef(null);
  const streamRef = useRef(null);
  const chunksRef = useRef([]);
  const recordingErrorRef = useRef(false);
  const recordingTimerRef = useRef(null);
  const recordingLanguageRef = useRef(voiceLanguage);
  const sttControllerRef = useRef(null);
  const ttsControllerRef = useRef(null);
  const audioRef = useRef(null);
  const audioUrlRef = useRef(null);
  const ttsRequestIdRef = useRef(0);
  const chatRequestIdRef = useRef(0);
  const translationRequestIdRef = useRef(0);
  const busyRef = useRef(false);
  const speakOnRef = useRef(speakOn);
  const mountedRef = useRef(false);
  const endRef = useRef(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  useEffect(() => {
    mountedRef.current = true;
    const controller = new AbortController();
    getVoiceCapabilities(controller.signal)
      .then((result) => {
        if (!Array.isArray(result?.stt?.languages) || !Array.isArray(result?.tts?.languages)) {
          throw new Error("Voice capability response was invalid.");
        }
        if (!mountedRef.current) return;
        setCapabilities(result);
        setVoiceLanguage((current) => result.stt.languages.includes(current)
          ? current
          : VOICE_LANGUAGES.find((item) => result.stt.languages.includes(item.code))?.code || "");
      })
      .catch((error) => {
        if (mountedRef.current && !controller.signal.aborted) {
          setCapabilityError(`${t.voiceUnavailable} ${error.message}`);
        }
      });

    return () => {
      mountedRef.current = false;
      controller.abort();
      sttControllerRef.current?.abort();
      ttsControllerRef.current?.abort();
      window.clearTimeout(recordingTimerRef.current);
      if (rec.current) {
        rec.current.ondataavailable = null;
        rec.current.onerror = null;
        rec.current.onstop = null;
        if (rec.current.state !== "inactive") rec.current.stop();
      }
      stopTracks(streamRef.current);
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current.removeAttribute("src");
        audioRef.current.load();
      }
      if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
    };
  }, []);

  function releaseAudio(requestId) {
    if (requestId !== ttsRequestIdRef.current) return;
    if (audioRef.current) {
      audioRef.current.onended = null;
      audioRef.current.onerror = null;
      audioRef.current.pause();
      audioRef.current.removeAttribute("src");
      audioRef.current.load();
      audioRef.current = null;
    }
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }
    ttsControllerRef.current = null;
    if (mountedRef.current) setPlaybackStatus("idle");
  }

  function stopPlayback() {
    ttsRequestIdRef.current += 1;
    ttsControllerRef.current?.abort();
    releaseAudio(ttsRequestIdRef.current);
  }

  async function playSpeech(value, locale, explicit = false) {
    if (!explicit && !speakOnRef.current) return;
    if (!capabilities?.tts.languages.includes(locale)) {
      if (mountedRef.current) setErr(t.voiceTtsUnavailable);
      return;
    }

    stopPlayback();
    const requestId = ++ttsRequestIdRef.current;
    const controller = new AbortController();
    ttsControllerRef.current = controller;
    setPlaybackStatus("generating");
    try {
      const spokenText = value.replace(/\[S\d+\]/g, "").trim();
      const audioBlob = await synthesizeSpeech(spokenText, locale, controller.signal);
      if (!mountedRef.current || requestId !== ttsRequestIdRef.current) return;

      const audioUrl = URL.createObjectURL(audioBlob);
      audioUrlRef.current = audioUrl;
      const audio = new Audio(audioUrl);
      audioRef.current = audio;
      audio.onended = () => releaseAudio(requestId);
      audio.onerror = () => {
        releaseAudio(requestId);
        if (mountedRef.current) setErr(t.voicePlaybackFailed);
      };
      await audio.play();
      if (mountedRef.current && requestId === ttsRequestIdRef.current && audioRef.current === audio) {
        setPlaybackStatus("playing");
      }
    } catch (error) {
      if (error.name === "AbortError" || requestId !== ttsRequestIdRef.current) return;
      releaseAudio(requestId);
      if (mountedRef.current) setErr(`${t.voicePlaybackFailed} ${error.message}`);
    }
  }

  async function send(message, locale = voiceLanguage, detectedLanguage = null) {
    const question = (message ?? text).trim();
    if (!question || busyRef.current || !locale) return;
    busyRef.current = true;
    const requestId = ++chatRequestIdRef.current;
    setText("");
    setErr("");
    setBusy(true);
    const history = msgs.map(({ role, content, sourceContent }) => ({
      role,
      content: role === "assistant" ? sourceContent || content : content,
    }));
    setMsgs((current) => [...current, {
      role: "user",
      content: question,
      language: locale,
      detectedLanguage: detectedLanguage && detectedLanguage !== locale ? detectedLanguage : null,
    }]);
    try {
      const languageCode = VOICE_LANGUAGES.find((item) => item.code === locale)?.chatCode;
      if (!languageCode) throw new Error("The selected assistant language is not supported.");
      const result = await chat({
        lat: loc.lat,
        lon: loc.lon,
        crop: form.crop,
        stage: form.stage || null,
        soil_type: form.soil_type || null,
        state: form.state || null,
        language: languageCode,
        message: question,
        history,
      });
      if (!mountedRef.current || requestId !== chatRequestIdRef.current) return;
      const response = result.advisory;
      setMsgs((current) => [...current, {
        role: "assistant",
        content: response,
        sourceContent: result.source_advisory || response,
        translations: {
          en: result.source_advisory || response,
          [languageCode]: response,
        },
        by: result.generated_by,
        grounding: result.grounding,
        language: locale,
      }]);
      if (capabilities?.tts.languages.includes(locale)) void playSpeech(response, locale);
    } catch (error) {
      if (mountedRef.current && requestId === chatRequestIdRef.current) setErr(error.message);
    } finally {
      if (requestId === chatRequestIdRef.current) {
        busyRef.current = false;
        if (mountedRef.current) setBusy(false);
      }
    }
  }

  async function changeVoiceLanguage(locale) {
    const requestId = ++translationRequestIdRef.current;
    const targetLanguage = VOICE_LANGUAGES.find((item) => item.code === locale)?.chatCode;
    if (!targetLanguage) return;
    setErr("");
    const assistantMessages = msgs
      .map((message, index) => ({ message, index }))
      .filter(({ message }) => message.role === "assistant");

    if (targetLanguage === "en") {
      setMsgs((current) => current.map((message) => message.role === "assistant"
        ? {
          ...message,
          content: message.sourceContent || message.content,
          translations: {
            ...message.translations,
            en: message.sourceContent || message.content,
          },
          language: locale,
        }
        : message));
      setVoiceLanguage(locale);
      return;
    }

    const messagesToTranslate = assistantMessages.filter(
      ({ message }) => !message.translations?.[targetLanguage],
    );
    setTranslating(true);
    try {
      const results = await Promise.allSettled(messagesToTranslate.map(({ message }) => (
        translateAdvisory(message.sourceContent || message.content, targetLanguage)
      )));
      if (!mountedRef.current || requestId !== translationRequestIdRef.current) return;
      const translatedByIndex = new Map();
      let translationError;
      let translationFailed = false;
      results.forEach((result, translationIndex) => {
        if (result.status === "fulfilled") {
          translatedByIndex.set(messagesToTranslate[translationIndex].index, result.value);
        } else if (!translationFailed) {
          translationFailed = true;
          translationError = result.reason;
        }
      });
      if (translationFailed) {
        setMsgs((current) => current.map((message, index) => {
          const translatedText = translatedByIndex.get(index);
          return message.role === "assistant" && translatedText
            ? {
              ...message,
              translations: { ...message.translations, [targetLanguage]: translatedText },
            }
            : message;
        }));
        throw translationError || new Error("One or more advisory translations failed.");
      }
      setMsgs((current) => {
        const next = [...current];
        assistantMessages.forEach(({ index }) => {
          const message = next[index];
          if (message?.role === "assistant") {
            const translatedText = message.translations?.[targetLanguage]
              || translatedByIndex.get(index);
            next[index] = {
              ...message,
              content: translatedText || message.sourceContent || message.content,
              translations: translatedText
                ? { ...message.translations, [targetLanguage]: translatedText }
                : message.translations,
              language: locale,
            };
          }
        });
        return next;
      });
      setVoiceLanguage(locale);
    } catch (error) {
      if (mountedRef.current && requestId === translationRequestIdRef.current) {
        setErr(error.message);
      }
    } finally {
      if (mountedRef.current && requestId === translationRequestIdRef.current) {
        setTranslating(false);
      }
    }
  }

  async function processRecording(blob, locale) {
    const controller = new AbortController();
    sttControllerRef.current = controller;
    setTranscribing(true);
    setErr("");
    try {
      const wav = await recordingToWav(blob);
      if (!mountedRef.current || controller.signal.aborted) return;
      const result = await transcribeAudio(wav, locale, controller.signal);
      if (!mountedRef.current || controller.signal.aborted) return;
      const transcript = typeof result.transcript === "string" ? result.transcript.trim() : "";
      if (!transcript) {
        setErr(t.voiceNoSpeech);
        return;
      }
      setText(transcript);
      const detectedLanguage = typeof result.detected_language_code === "string"
        && sttLanguages.includes(result.detected_language_code)
        ? result.detected_language_code
        : null;
      await send(transcript, locale, detectedLanguage);
    } catch (error) {
      if (mountedRef.current && error.name !== "AbortError") setErr(error.message || t.voiceMicFailed);
    } finally {
      sttControllerRef.current = null;
      if (mountedRef.current) setTranscribing(false);
    }
  }

  function stopRecording() {
    window.clearTimeout(recordingTimerRef.current);
    recordingTimerRef.current = null;
    if (rec.current && rec.current.state !== "inactive") rec.current.stop();
  }

  async function toggleRecording() {
    if (recording) {
      stopRecording();
      return;
    }
    if (busyRef.current || transcribing || permissionPending) return;
    setErr("");
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setErr(t.micUnsupported);
      return;
    }

    setPermissionPending(true);
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!mountedRef.current || busyRef.current) {
        stopTracks(stream);
        return;
      }
      const mimeType = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"]
        .find((type) => window.MediaRecorder.isTypeSupported(type));
      const recorder = new window.MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      streamRef.current = stream;
      rec.current = recorder;
      chunksRef.current = [];
      recordingErrorRef.current = false;
      recordingLanguageRef.current = voiceLanguage;
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunksRef.current.push(event.data);
      };
      recorder.onerror = () => {
        recordingErrorRef.current = true;
        setErr(t.voiceMicFailed);
        stopRecording();
      };
      recorder.onstop = () => {
        window.clearTimeout(recordingTimerRef.current);
        recordingTimerRef.current = null;
        stopTracks(streamRef.current);
        streamRef.current = null;
        rec.current = null;
        setRecording(false);
        const recordingBlob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        chunksRef.current = [];
        if (recordingErrorRef.current) {
          recordingErrorRef.current = false;
          return;
        }
        if (!recordingBlob.size) {
          setErr(t.voiceNoAudio);
          return;
        }
        void processRecording(recordingBlob, recordingLanguageRef.current);
      };
      recorder.start(250);
      setRecording(true);
      recordingTimerRef.current = window.setTimeout(stopRecording, (MAX_RECORDING_SECONDS - 0.5) * 1000);
    } catch (error) {
      stopTracks(stream);
      streamRef.current = null;
      rec.current = null;
      if (mountedRef.current) {
        setErr(error.name === "NotAllowedError" || error.name === "PermissionDeniedError"
          ? t.voiceMicPermission
          : `${t.voiceMicFailed} ${error.message}`);
      }
    } finally {
      if (mountedRef.current) setPermissionPending(false);
    }
  }

  const examples = [t.ex1, t.ex2, t.ex3];
  const sttLanguages = capabilities?.stt.languages || [];
  const ttsLanguages = capabilities?.tts.languages || [];
  const availableLanguages = VOICE_LANGUAGES.filter((item) => sttLanguages.includes(item.code) || item.translationOnly);
  const voiceBusy = recording || permissionPending || transcribing || translating;
  const browserCanRecord = typeof window !== "undefined"
    && Boolean(window.MediaRecorder)
    && Boolean(navigator.mediaDevices?.getUserMedia);

  return (
    <div className="voice-assistant-layout grid gap-4 lg:grid-cols-[1fr_1.2fr]">
      <Card title={t.assistantContext} hint={t.assistantContextHint} className="assistant-context-card">
        <FarmMap lat={loc.lat} lon={loc.lon} onSelect={(lat, lon) => setLoc({ lat, lon })} height={260} />
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <Field label={t.crop}>
            <select className={inputCls} value={form.crop} onChange={(event) => setForm({ ...form, crop: event.target.value })}>
              {CROP_IDS.map((id) => <option key={id} value={id}>{tc[id]}</option>)}
            </select>
          </Field>
          <Field label={t.growthStage}><Txt value={form.stage} onChange={(value) => setForm({ ...form, stage: value })} /></Field>
          <Field label={t.soilType}><Txt value={form.soil_type} onChange={(value) => setForm({ ...form, soil_type: value })} /></Field>
          <Field label={t.stateForMandi}><Txt value={form.state} onChange={(value) => setForm({ ...form, state: value })} /></Field>
        </div>
        <Note>{loc.lat.toFixed(4)}, {loc.lon.toFixed(4)}</Note>
      </Card>

      <Card title={t.assistantTitle} hint={t.assistantHint} className="assistant-chat-card">
        <div className="assistant-language-row mb-3 flex flex-wrap items-center gap-2">
          <label className="text-sm font-medium" htmlFor="assistant-voice-language">{t.voiceLanguage}</label>
          <select
            id="assistant-voice-language"
            className={inputCls}
            value={voiceLanguage}
            disabled={!capabilities || voiceBusy || busy}
            onChange={(event) => void changeVoiceLanguage(event.target.value)}
          >
            {availableLanguages.map((item) => (
              <option key={item.code} value={item.code}>
                {item.label}{ttsLanguages.includes(item.code) ? "" : " — text only"}
              </option>
            ))}
          </select>
          {!capabilities && <span className="text-sm text-slate-400">{t.voiceCapabilitiesLoading}</span>}
          {translating && <span className="text-sm text-slate-400">{t.translatingAdvisory}</span>}
        </div>
        <div className="assistant-conversation h-[420px] space-y-3 overflow-y-auto rounded-xl border border-slate-800 p-3">
          {msgs.length === 0 && (
            <div className="assistant-empty-state text-sm text-slate-400">
              <p>{t.tryAsking}</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {examples.map((example) => <Ghost className="assistant-suggestion" key={example} disabled={busy || voiceBusy} onClick={() => send(example)}>{example}</Ghost>)}
              </div>
            </div>
          )}
          {msgs.map((message, index) => (
            <div key={index} className={`assistant-message ${message.role === "user" ? "assistant-message-user ml-10" : "assistant-message-bot mr-10"}`}>
              <div className="assistant-message-content whitespace-pre-wrap text-sm leading-relaxed">{message.content}</div>
              {message.detectedLanguage && (
                <div className="assistant-message-meta mt-1 text-xs text-slate-400">
                  {t.voiceDetectedLanguage}: {VOICE_LANGUAGES.find((item) => item.code === message.detectedLanguage)?.label || message.detectedLanguage}
                </div>
              )}
              {message.by && (
                <div className="assistant-message-meta mt-1 text-xs text-slate-400">
                  {message.by.fallback ? t.ruleBased : message.by.provider}
                  {message.grounding?.checked > 0 && ` · ${t.figuresChecked}: ${message.grounding.checked - message.grounding.unverified.length}/${message.grounding.checked}`}
                  {ttsLanguages.includes(message.language) && (
                    <Ghost className="assistant-listen-button ml-2 !px-2 !py-0.5 text-xs" onClick={() => void playSpeech(message.content, message.language, true)}>{t.listen}</Ghost>
                  )}
                </div>
              )}
            </div>
          ))}
          {busy && <div className="assistant-thinking text-sm text-slate-400">{t.thinking}</div>}
          <div ref={endRef} />
        </div>
        <div className="assistant-error"><Err>{err || capabilityError}</Err></div>
        <div className="assistant-composer mt-3 flex gap-2">
          <input
            className={`${inputCls} assistant-input flex-1`}
            value={text}
            placeholder={t.askPlaceholder}
            maxLength={600}
            disabled={busy || voiceBusy}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && void send()}
          />
          <Ghost
            className={`assistant-voice-button ${recording ? "is-listening" : ""}`}
            onClick={() => void toggleRecording()}
            disabled={!browserCanRecord || !capabilities || !sttLanguages.includes(voiceLanguage) || busy || transcribing || permissionPending}
            title={!browserCanRecord ? t.micUnsupported : !sttLanguages.includes(voiceLanguage) ? t.voiceInputUnavailable : ""}
          >
            {recording ? t.stopMic : permissionPending ? t.voiceMicrophonePrompt : transcribing ? t.voiceTranscribing : t.mic}
          </Ghost>
          <Btn className="assistant-send-button" busy={busy} disabled={voiceBusy} onClick={() => void send()}>{t.send}</Btn>
          {playbackStatus !== "idle" && (
            <Ghost className="assistant-voice-button" onClick={stopPlayback}>
              {playbackStatus === "generating" ? t.voicePreparing : t.voiceStopPlayback}
            </Ghost>
          )}
        </div>
        <label className="assistant-read-aloud mt-2 flex items-center gap-2 text-sm text-slate-400">
          <input
            type="checkbox"
            checked={speakOn}
            onChange={(event) => {
              const checked = event.target.checked;
              speakOnRef.current = checked;
              setSpeakOn(checked);
              if (!checked) stopPlayback();
            }}
          />
          <span>{t.readAloud}</span>
        </label>
        {!browserCanRecord && <Note>{t.micUnsupported}</Note>}
        {capabilities && !sttLanguages.includes(voiceLanguage) && <Note>{t.voiceInputUnavailable}</Note>}
        {capabilities && !ttsLanguages.includes(voiceLanguage) && <Note>{t.voiceTtsUnavailable}</Note>}
      </Card>
    </div>
  );
}
