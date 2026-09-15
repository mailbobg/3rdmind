import { reactive } from "vue";
import { persistStudioState, restoreStudioState } from "./studioStorage";

/** Drag-resizable rail and results widths for the three-column layout. */
export const RAIL = { min: 180, max: 420, default: 230 };
export const RESULTS = { min: 320, max: 900, default: 440 };

export function useColumnWidths() {
  const saved = restoreStudioState().columns || {};
  const widths = reactive({
    rail: clamp(saved.rail ?? RAIL.default, RAIL),
    results: clamp(saved.results ?? RESULTS.default, RESULTS),
  });

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
      persistStudioState({ columns: { rail: widths.rail, results: widths.results } });
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", stop);
    target.addEventListener("pointercancel", stop);
  }

  return { widths, startDrag };
}

export function clamp(value: number, limits: { min: number; max: number }) {
  return Math.min(limits.max, Math.max(limits.min, Number.isFinite(value) ? value : limits.min));
}
