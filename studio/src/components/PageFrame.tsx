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

/** Diagonal arrows: pointing out to expand, pointing in to restore. */
function ExpandIcon({ expanded }: { expanded: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {expanded ? (
        <><path d="M6 8H2.5M6 8v3.5M6 8l-4 4" /><path d="M8 6h3.5M8 6V2.5M8 6l4-4" /></>
      ) : (
        <><path d="M8.5 1.5H12.5V5.5M12.5 1.5l-5 5" /><path d="M5.5 12.5H1.5V8.5M1.5 12.5l5-5" /></>
      )}
    </svg>
  );
}

export function PageFrame(p: PageFrameProps) {
  const { layout } = useStudio();
  const panel = useResizablePanel();
  // The remembered results width is clamped to what the window leaves next to the work column; when even
  // that is too little the two stack vertically.
  // Every page mounts its own frame, so a page change always comes back to the two-column layout.
  useLayoutEffect(() => { layout.resetExpanded(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
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
  const expanded = layout.resultsOpen && layout.resultsExpanded;
  const stacked = layout.resultsOpen && !expanded && available < WORK_MIN + RESULTS_MIN;
  const resultsWidth = Math.max(RESULTS_MIN, Math.min(panel.width, available - WORK_MIN));
  const columns = !layout.resultsOpen || stacked || expanded ? "minmax(0,1fr)" : `minmax(${WORK_MIN}px,1fr) ${resultsWidth}px`;
  const rows = stacked ? "minmax(0,1fr) minmax(0,1fr)" : undefined;
  // The work column fills the card; the results column is a raised panel floating over the card's right side
  // (own border, shadow and inset), like a desktop app's preview pane. The work column still yields the space,
  // so nothing hides behind the panel; the drag handle rides the panel's left edge. Stacked, the panel becomes
  // a plain lower half again.
  const floating = layout.resultsOpen && !stacked;
  return (
    <div ref={frame} className="grid min-h-0 min-w-0 overflow-hidden rounded-2xl border border-border bg-surface" style={{ gridTemplateColumns: columns, gridTemplateRows: rows }}>
      {!expanded && <main className="mm flex min-h-0 min-w-0 flex-col">
        <div className="mm-head">
          <div>{p.tabs}</div>
          <div className="mm-head-actions">
            {p.actions}
            <button type="button" className="mm-btn mm-btn--text" onClick={layout.toggleResults}>{layout.resultsOpen ? "隐藏结果 ▸" : "◂ 显示结果"}</button>
          </div>
        </div>
        <div className="mm-body">{p.children}</div>
      </main>}
      {layout.resultsOpen && (
        <aside className={`relative flex min-h-0 min-w-0 flex-col bg-surface ${floating ? "float-panel" : "border-t border-border"}`}>
          {!stacked && !expanded && (
            <div role="separator" aria-orientation="vertical" aria-label="调整结果栏宽度" onPointerDown={panel.onPointerDown}
              className="absolute -left-1.5 top-0 bottom-0 z-10 w-3 cursor-col-resize touch-none hover:bg-accent/15 active:bg-accent/25" />
          )}
          <div className="flex flex-wrap items-center justify-between gap-2.5 border-b border-border px-3.5 py-2.5">
            <div className="text-[13px] font-semibold text-foreground">{typeof p.resultsTitle === "string" ? capitalize(p.resultsTitle) : p.resultsTitle}</div>
            <div className="flex flex-wrap items-center gap-1.5">
              {p.resultsActions}
              <button type="button" className="mm-btn mm-btn--text mm-btn--icon" onClick={layout.toggleExpanded}
                aria-pressed={expanded} title={expanded ? "恢复两栏" : "展开到整块区域"} aria-label={expanded ? "恢复两栏" : "展开到整块区域"}>
                <ExpandIcon expanded={expanded} />
              </button>
            </div>
          </div>
          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-3.5">{p.results}</div>
        </aside>
      )}
    </div>
  );
}
