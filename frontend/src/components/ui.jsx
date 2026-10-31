// Small shared UI pieces that match the existing dark dashboard styling.
export const card = "rounded-3xl border border-slate-800 bg-slate-900 p-4 sm:p-5";
export const inputCls = "rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100";

export function Card({ title, hint, children, className = "" }) {
  return (
    <section className={`${card} ${className}`}>
      {title && <h2 className="text-lg font-semibold text-slate-100">{title}</h2>}
      {hint && <p className="mt-1 text-sm text-slate-400">{hint}</p>}
      <div className={title ? "mt-3" : ""}>{children}</div>
    </section>
  );
}

export function Field({ label, children }) {
  return (
    <label className="flex flex-col gap-1 text-sm text-slate-300">
      <span>{label}</span>
      {children}
    </label>
  );
}

export const Num = ({ value, onChange, ...rest }) => (
  <input type="number" step="any" className={`${inputCls} w-full`} value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))} {...rest} />
);

export const Txt = ({ value, onChange, ...rest }) => (
  <input className={`${inputCls} w-full`} value={value ?? ""} onChange={(e) => onChange(e.target.value)} {...rest} />
);

export function Btn({ children, busy, className = "", ...rest }) {
  return (
    <button className={`rounded-lg bg-emerald-500 px-4 py-2 font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-50 ${className}`} disabled={busy || rest.disabled} {...rest}>
      {children}
    </button>
  );
}

export const Ghost = ({ children, className = "", ...rest }) => (
  <button className={`rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800 ${className}`} {...rest}>{children}</button>
);

export const Err = ({ children }) => (children ? <p className="mt-2 rounded-lg border border-amber-700 bg-amber-950/40 px-3 py-2 text-sm text-amber-200">{children}</p> : null);
export const Note = ({ children }) => <p className="mt-2 text-sm text-slate-400">{children}</p>;

export const CROP_IDS = ["wheat", "rice", "maize", "cotton", "soybean", "groundnut", "mustard", "potato", "tomato", "sugarcane", "chickpea"];
export const LANG_OPTIONS = [["en", "English"], ["hi", "हिन्दी"], ["bn", "বাংলা"], ["mr", "मराठी"], ["ta", "தமிழ்"], ["te", "తెలుగు"], ["gu", "ગુજરાતી"], ["kn", "ಕನ್ನಡ"], ["pa", "ਪੰਜਾਬੀ"]];
export const VOICE_LANGUAGES = [
  { code: "en-IN", chatCode: "en", label: "English (India)" },
  { code: "hi-IN", chatCode: "hi", label: "हिन्दी" },
  { code: "bn-IN", chatCode: "bn", label: "বাংলা" },
  { code: "gu-IN", chatCode: "gu", label: "ગુજરાતી" },
  { code: "ta-IN", chatCode: "ta", label: "தமிழ்" },
  { code: "kn-IN", chatCode: "kn", label: "ಕನ್ನಡ" },
  { code: "te-IN", chatCode: "te", label: "తెలుగు" },
  { code: "mr-IN", chatCode: "mr", label: "मराठी" },
  { code: "ml-IN", chatCode: "ml", label: "മലയാളം" },
  { code: "pa-IN", chatCode: "pa", label: "ਪੰਜਾਬੀ" },
  { code: "or-IN", chatCode: "or", label: "ଓଡ଼ିଆ", translationOnly: true },
  { code: "as-IN", chatCode: "as", label: "অসমীয়া", translationOnly: true },
  { code: "ur-IN", chatCode: "ur", label: "اردو", translationOnly: true },
];
