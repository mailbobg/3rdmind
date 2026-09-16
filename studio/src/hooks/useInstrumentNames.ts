import { useEffect, useState } from "react";
import * as studio from "../api/studio";

type Names = Record<string, { name: string; industry?: string }>;
let cache: Names | null = null;
let pending: Promise<Names> | null = null;
const listeners = new Set<(n: Names) => void>();

/** Instrument code → listing name, fetched once per page load from /studio/instruments/names. */
export function useInstrumentNames(): Names {
  const [names, setNames] = useState<Names>(cache || {});
  useEffect(() => {
    if (cache) { setNames(cache); return; }
    listeners.add(setNames);
    pending ??= studio.instrumentNames().then((r) => { cache = r.names; listeners.forEach((l) => l(cache!)); return cache; }).catch(() => (cache = {}));
    return () => { listeners.delete(setNames); };
  }, []);
  return names;
}
