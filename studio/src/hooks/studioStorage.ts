const STORAGE_KEY = "rd-studio-v3";

export function restoreStudioState(): Record<string, any> {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"); } catch { return {}; }
}

export function persistStudioState(patch: Record<string, unknown>) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...restoreStudioState(), ...patch })); } catch { /* storage unavailable */ }
}
