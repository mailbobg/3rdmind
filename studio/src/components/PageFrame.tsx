import type { ReactNode } from "react";
import { Chip } from "@heroui/react";
import { capitalize, useStudio } from "../hooks/studioContext";
import { useResizablePanel } from "../hooks/useResizablePanel";

export interface PageFrameProps {
  title: string;
  description?: string;
  tag?: string;
  titleEnd?: ReactNode;
  tabs?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  resultsTitle: ReactNode;
  resultsActions?: ReactNode;
  results: ReactNode;
}

/**
 * The three-layer frame every page shares: an object bar across both columns, then a work column
 * (text tabs + actions, content in the minimal `.mm` style) beside a results panel the user can hide
 * and drag wider.
 */
export function PageFrame(p: PageFrameProps) {
  const { layout } = useStudio();
  const panel = useResizablePanel();
  return (
    <div className="grid min-h-0 min-w-0 grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)] gap-2">
      <header className="flex min-h-[52px] min-w-0 items-center gap-3.5 rounded-2xl border border-border bg-surface px-4.5 py-2.5">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-sm font-semibold text-foreground" title={p.title}>{capitalize(p.title)}</h1>
          {p.description && <div className="truncate text-[11px] text-muted" title={p.description}>{p.description}</div>}
        </div>
        {p.titleEnd}
        {p.tag && <Chip size="sm" variant="tertiary">{p.tag}</Chip>}
      </header>
      <div className="grid min-h-0 min-w-0 gap-0.5" style={{ gridTemplateColumns: layout.resultsOpen ? `minmax(360px,1fr) 6px ${panel.width}px` : "minmax(360px,1fr)" }}>
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
            <div role="separator" aria-orientation="vertical" aria-label="调整结果栏宽度" onPointerDown={panel.onPointerDown}
              className="group relative cursor-col-resize touch-none rounded hover:bg-border active:bg-border">
              <span className="absolute left-0.5 top-1/2 h-9 w-0.5 -translate-y-1/2 rounded bg-border" />
            </div>
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
    </div>
  );
}
