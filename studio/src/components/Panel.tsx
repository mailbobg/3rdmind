import type { ReactNode } from "react";

/** A bordered block with a title row, optional status text on the right, and an optional footer: the one big thing in a column. */
export function Panel(p: { title: ReactNode; status?: ReactNode; statusTone?: "ok" | "bad"; footer?: ReactNode; children: ReactNode; flush?: boolean; grow?: boolean }) {
  return (
    <section className={`flex min-h-0 flex-col rounded-xl border border-border bg-surface ${p.grow ? "flex-1" : ""}`}>
      <div className="flex items-center justify-between gap-2.5 border-b border-border px-3 py-2 text-xs">
        <h3 className="m-0 text-xs font-semibold text-foreground">{p.title}</h3>
        {p.status && <span className={`text-[11px] ${p.statusTone === "bad" ? "text-danger" : "text-success"}`}>{p.status}</span>}
      </div>
      <div className={`min-h-0 flex-1 overflow-auto ${p.flush ? "" : "p-3"}`}>{p.children}</div>
      {p.footer && <div className="flex flex-wrap items-center gap-3.5 border-t border-border px-3 py-2 text-[11px] text-muted">{p.footer}</div>}
    </section>
  );
}
