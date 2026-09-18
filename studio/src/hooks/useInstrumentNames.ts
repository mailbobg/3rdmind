import { useEffect, useState } from "react";
import * as studio from "../api/studio";

type Names = Record<string, { name: string; industry?: string }>;
const cache: Record<string, Names> = {};
const pending: Record<string, Promise<Names>> = {};
const listeners = new Set<(n: Names) => void>();

/** Instrument code → listing name for the current workspace, fetched once per region per page load. */
export function useInstrumentNames(): Names {
  const region = studio.getApiRegion();
  const [names, setNames] = useState<Names>(cache[region] || {});
  useEffect(() => {
    if (cache[region]) { setNames(cache[region]); return; }
    listeners.add(setNames);
    pending[region] ??= studio.instrumentNames().then((r) => { cache[region] = r.names; listeners.forEach((l) => l(r.names)); return r.names; }).catch(() => (cache[region] = {}));
    return () => { listeners.delete(setNames); };
  }, [region]);
  return names;
}
