import { useCallback, useMemo, useState } from "react";
import type { FactorWeight } from "../api/studio";
import { persistStudioState, restoreStudioState } from "./studioStorage";

/** Signals picked for the portfolio backtest; shared by the factor library, research page and backtest page. */
export const basketKey = (f: { trace: string; loop_id: number; name: string; kind?: string }) =>
  `${f.kind || "factor"}#${f.trace}#${f.loop_id}#${f.name}`;
export const PREDICTION_NAME = "模型预测";

export function useFactorBasket() {
  const [items, setItems] = useState<FactorWeight[]>(() => {
    const saved = restoreStudioState().basket;
    return Array.isArray(saved) ? saved : [];
  });
  const commit = useCallback((next: FactorWeight[]) => { setItems(next); persistStudioState({ basket: next }); }, []);
  const keys = useMemo(() => new Set(items.map(basketKey)), [items]);
  const has = useCallback((f: { trace: string; loop_id: number; name: string; kind?: string }) => keys.has(basketKey(f)), [keys]);
  const toggle = useCallback((f: { trace: string; loop_id: number; name: string; kind?: string }) => {
    const index = items.findIndex((item) => basketKey(item) === basketKey(f));
    commit(index >= 0 ? items.filter((_, i) => i !== index) : [...items, { name: f.name, trace: f.trace, loop_id: f.loop_id, weight: 1, kind: (f.kind as FactorWeight["kind"]) || "factor" }]);
  }, [items, commit]);
  const addRound = useCallback((trace: string, loop_id: number, names: string[]) => {
    const additions = names.filter((name) => !keys.has(basketKey({ trace, loop_id, name }))).map((name) => ({ name, trace, loop_id, weight: 1, kind: "factor" as const }));
    if (additions.length) commit([...items, ...additions]);
  }, [items, keys, commit]);
  const addPrediction = useCallback((trace: string, loop_id: number) => {
    const item = { name: PREDICTION_NAME, trace, loop_id, kind: "prediction" as const };
    if (!keys.has(basketKey(item))) commit([...items, { ...item, weight: 1 }]);
  }, [items, keys, commit]);
  const setWeight = useCallback((f: FactorWeight, weight: number) => commit(items.map((item) => (basketKey(item) === basketKey(f) ? { ...item, weight } : item))), [items, commit]);
  const clear = useCallback(() => commit([]), [commit]);
  /** Replace the whole basket, e.g. with a search's recommendation. */
  const replace = useCallback((next: FactorWeight[]) => commit(next), [commit]);
  return { items, has, toggle, addRound, addPrediction, setWeight, clear, replace };
}
export type BasketStore = ReturnType<typeof useFactorBasket>;
