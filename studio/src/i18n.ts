import { EN } from "./i18n.en";

/**
 * Two-language UI. Source strings are the Chinese the components are written in; `t()` returns their English
 * from the dictionary when the language is "en", with `{0}`, `{1}`… placeholders filled from `vars`.
 * The language is read once at start-up (shared across workspaces) and switching reloads the page, so no
 * memoised text can go stale.
 */
export type Lang = "zh" | "en";
const KEY = "rd-studio-lang";

function initial(): Lang {
  try {
    if (typeof localStorage === "undefined") return "zh";
    const saved = localStorage.getItem(KEY);
    if (saved === "en" || saved === "zh") return saved;
  } catch { /* storage unavailable */ }
  return "zh";
}
export let lang: Lang = initial();
if (typeof document !== "undefined") document.documentElement.lang = lang === "en" ? "en" : "zh-CN";

export function setLang(next: Lang) {
  if (next === lang) return;
  try { localStorage.setItem(KEY, next); } catch { /* storage unavailable */ }
  if (typeof location !== "undefined") location.reload();
}

const missing = new Set<string>();

export function t(key: string, vars?: (string | number | null | undefined)[]): string {
  let text = key;
  if (lang === "en") {
    const hit = EN[key];
    if (hit !== undefined) text = hit;
    else if (import.meta.env.DEV && /[一-龥]/.test(key) && !missing.has(key)) { missing.add(key); console.warn("[i18n] missing:", key); }
  }
  if (vars) text = text.replace(/\{(\d+)\}/g, (m, i) => { const v = vars[Number(i)]; return v == null ? "" : String(v); });
  return text;
}

/** Locale for dates and numbers. */
export const locale = () => (lang === "en" ? "en-US" : "zh-CN");
