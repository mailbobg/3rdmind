import { reactive, ref } from "vue";
import { persistStudioState, restoreStudioState } from "./studioStorage";

/** Drag-resizable rail and results widths for the three-column layout, plus the results column's open state. */
export const RAIL = { min: 180, max: 420, default: 230 };
export const RESULTS = { min: 360, max: 1400, default: 680 };

export function useColumnWidths() {
  const saved = restoreStudioState().layout || {};
  const widths = reactive({
    rail: clamp(saved.rail ?? RAIL.default, RAIL),
    results: clamp(saved.results ?? RESULTS.default, RESULTS),
  });
  // The results column starts hidden so the workspace gets the full width; it opens when the user
  // picks something that has a detail view (a round, a factor, a backtest) or toggles it by hand.
  const resultsOpen = ref<boolean>(saved.resultsOpen ?? false);
  function persistColumns() {
    persistStudioState({ layout: { rail: widths.rail, results: widths.results, resultsOpen: resultsOpen.value } });
  }
  function setResultsOpen(open: boolean) { resultsOpen.value = open; persistColumns(); }
  const toggleResults = () => setResultsOpen(!resultsOpen.value);
  const openResults = () => { if (!resultsOpen.value) setResultsOpen(true); };

  function startDrag(side: "rail" | "results", event: PointerEvent) {
    const startX = event.clientX;
    const startWidth = widths[side];
    const limits = side === "rail" ? RAIL : RESULTS;
    const target = event.currentTarget as HTMLElement;
    target.setPointerCapture(event.pointerId);
    document.body.style.cursor = "col-resize";
    const move = (e: PointerEvent) => {
      // The rail grows when dragged right; the results column grows when dragged left.
      const delta = side === "rail" ? e.clientX - startX : startX - e.clientX;
      widths[side] = clamp(startWidth + delta, limits);
    };
    const stop = () => {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", stop);
      target.removeEventListener("pointercancel", stop);
      document.body.style.cursor = "";
      persistColumns();
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", stop);
    target.addEventListener("pointercancel", stop);
  }

  return { widths, startDrag, resultsOpen, toggleResults, openResults };
}

export function clamp(value: number, limits: { min: number; max: number }) {
  return Math.min(limits.max, Math.max(limits.min, Number.isFinite(value) ? value : limits.min));
}
