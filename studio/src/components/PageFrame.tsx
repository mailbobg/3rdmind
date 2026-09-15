import { useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { capitalize, useStudio } from "../hooks/studioContext";
import { useResizablePanel } from "../hooks/useResizablePanel";

export interface PageFrameProps {
  tabs?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  resultsTitle: ReactNode;
  resultsActions?: ReactNode;
  results: ReactNode;
}

/**
 * The frame every page shares: a work column (text tabs + actions, content in the minimal `.mm` style)
 * beside a results panel the user can hide and drag wider.
 */
const WORK_MIN = 360;   // the work column never goes below this beside the results column
const RESULTS_MIN = 280;
const HANDLE = 6;

export function PageFrame(p: PageFrameProps) {
  const { layout } = useStudio();
  const panel = useResizablePanel();
  // The remembered results width is clamped to what the window leaves next to the work column; when even
  // that is too little the two stack vertically.
  const frame = useRef<HTMLDivElement>(null);
  const [available, setAvailable] = useState(Infinity);
  useLayoutEffect(() => {
    const el = frame.current;
    if (!el) return;
    const measure = () => setAvailable(el.clientWidth);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const stacked = layout.resultsOpen && available < WORK_MIN + HANDLE + RESULTS_MIN;
  const resultsWidth = Math.max(RESULTS_MIN, Math.min(panel.width, available - WORK_MIN - HANDLE));
  const columns = !layout.resultsOpen || stacked ? "minmax(0,1fr)" : `minmax(${WORK_MIN}px,1fr) ${HANDLE}px ${resultsWidth}px`;
  const rows = stacked ? "minmax(0,1fr) minmax(0,1fr)" : undefined;
  return (
    <div ref={frame} className="grid min-h-0 min-w-0 gap-0.5" style={{ gridTemplateColumns: columns, gridTemplateRows: rows }}>
        <main className="mm flex min-h-0 min-w-0 flex-col rounded-2xl border border-border">
          <div className="mm-head">
            <div>{p.tabs}</div>
            <div className="mm-head-actions">
              {p.actions}
              <button type="button" className="mm-btn mm-btn--text" onClick={layout.toggleResults}>{layout.resultsOpen ? "隐藏结果 ▸" : "◂ 显示结果"}</button>
            </div>
          </div>
          <div className="mm-body">{p.children}</div>
        </main>
        {layout.resultsOpen && (
          <>
            {!stacked && (
              <div role="separator" aria-orientation="vertical" aria-label="调整结果栏宽度" onPointerDown={panel.onPointerDown}
                className="group relative cursor-col-resize touch-none rounded hover:bg-border active:bg-border">
                <span className="absolute left-0.5 top-1/2 h-9 w-0.5 -translate-y-1/2 rounded bg-border" />
              </div>
            )}
            <aside className="flex min-h-0 min-w-0 flex-col rounded-2xl border border-border bg-surface">
              <div className="flex flex-wrap items-center justify-between gap-2.5 border-b border-border px-3.5 py-2.5">
                <div className="text-[13px] font-semibold text-foreground">{typeof p.resultsTitle === "string" ? capitalize(p.resultsTitle) : p.resultsTitle}</div>
                <div className="flex flex-wrap items-center gap-1.5">{p.resultsActions}</div>
              </div>
              <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-3.5">{p.results}</div>
            </aside>
          </>
        )}
    </div>
  );
}
