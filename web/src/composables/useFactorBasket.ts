import { computed, reactive } from "vue";
import type { FactorWeight } from "../api/studio";
import { persistStudioState, restoreStudioState } from "./studioStorage";

/** Factors picked for the portfolio backtest. Shared by the factor library and the backtest page. */
export const basketKey = (f: { trace: string; loop_id: number; name: string; kind?: string }) =>
  `${f.kind || "factor"}#${f.trace}#${f.loop_id}#${f.name}`;
export const PREDICTION_NAME = "模型预测";

const saved = restoreStudioState();
const items = reactive<FactorWeight[]>(Array.isArray(saved.basket) ? saved.basket : []);
const persist = () => persistStudioState({ basket: [...items] });

export function useFactorBasket() {
  const keys = computed(() => new Set(items.map(basketKey)));
  function has(f: { trace: string; loop_id: number; name: string }) { return keys.value.has(basketKey(f)); }
  function toggle(f: { trace: string; loop_id: number; name: string }) {
    const index = items.findIndex((item) => basketKey(item) === basketKey(f));
    if (index >= 0) items.splice(index, 1);
    else items.push({ name: f.name, trace: f.trace, loop_id: f.loop_id, weight: 1 });
    persist();
  }
  function addRound(trace: string, loop_id: number, names: string[]) {
    for (const name of names) if (!has({ trace, loop_id, name })) items.push({ name, trace, loop_id, weight: 1, kind: "factor" });
    persist();
  }
  function addPrediction(trace: string, loop_id: number) {
    const item = { name: PREDICTION_NAME, trace, loop_id, kind: "prediction" as const };
    if (!has(item)) items.push({ ...item, weight: 1 });
    persist();
  }
  function setWeight(f: FactorWeight, weight: number) { f.weight = weight; persist(); }
  function clear() { items.splice(0); persist(); }
  return { items, has, toggle, addRound, addPrediction, setWeight, clear };
}
