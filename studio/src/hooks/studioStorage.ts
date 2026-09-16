const SHARED_KEY = "rd-studio-v3";
let workspaceKey = SHARED_KEY;

/** Scope page state (basket, selections, form values) to a market workspace; layout stays shared. */
export function setStorageWorkspace(region: string) {
  workspaceKey = region === "cn" ? SHARED_KEY : `${SHARED_KEY}:${region}`;
}

function read(key: string): Record<string, any> {
  try { return JSON.parse(localStorage.getItem(key) || "{}"); } catch { return {}; }
}

export function restoreStudioState(): Record<string, any> {
  const own = read(workspaceKey);
  return workspaceKey === SHARED_KEY ? own : { ...own, layout: read(SHARED_KEY).layout };
}

export function persistStudioState(patch: Record<string, unknown>) {
  try {
    const { layout, ...rest } = patch;
    if (layout !== undefined) localStorage.setItem(SHARED_KEY, JSON.stringify({ ...read(SHARED_KEY), layout }));
    if (Object.keys(rest).length) localStorage.setItem(workspaceKey, JSON.stringify({ ...read(workspaceKey), ...rest }));
  } catch { /* storage unavailable */ }
}
