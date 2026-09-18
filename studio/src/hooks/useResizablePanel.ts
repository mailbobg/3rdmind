import { useCallback, useRef, useState } from "react";
import { persistStudioState, restoreStudioState } from "./studioStorage";

const LIMITS = { min: 360, max: 1400, default: 680 };
const clamp = (v: number) => Math.min(LIMITS.max, Math.max(LIMITS.min, Number.isFinite(v) ? v : LIMITS.default));

/** Width of the results panel, dragged from its left edge and remembered in local storage. */
export function useResizablePanel() {
  const [width, setWidth] = useState<number>(() => clamp(restoreStudioState().layout?.results ?? LIMITS.default));
  const widthRef = useRef(width);
  widthRef.current = width;
  const onPointerDown = useCallback((event: React.PointerEvent<HTMLElement>) => {
    const startX = event.clientX;
    const startWidth = widthRef.current;
    const target = event.currentTarget;
    target.setPointerCapture(event.pointerId);
    document.body.style.cursor = "col-resize";
    const move = (e: PointerEvent) => setWidth(clamp(startWidth + (startX - e.clientX))); // the panel grows when dragged left
    const stop = () => {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", stop);
      target.removeEventListener("pointercancel", stop);
      document.body.style.cursor = "";
      persistStudioState({ layout: { ...(restoreStudioState().layout || {}), results: widthRef.current } });
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", stop);
    target.addEventListener("pointercancel", stop);
  }, []);
  return { width, onPointerDown };
}
