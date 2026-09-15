import { useLayoutEffect, useRef, useState } from "react";
import type { ChangeEvent, MouseEvent, ReactNode } from "react";

/**
 * The work column's vocabulary: text tabs, outlined buttons, keyed fields in a hairline grid, titled
 * blocks and hairline tables. Plain elements styled by the `.mm-*` rules in index.css, so the column
 * reads as ink on paper rather than as a stack of widgets.
 */

export function TextTabs({ value, onChange, items, label }: { value: string; onChange: (v: string) => void; items: { key: string; label: ReactNode }[]; label: string }) {
  return (
    <div role="tablist" aria-label={label} className="mm-tabs">
      {items.map((t) => <button key={t.key} role="tab" type="button" aria-selected={t.key === value} className="mm-tab" onClick={() => onChange(t.key)}>{t.label}</button>)}
    </div>
  );
}

export function Btn({ children, onClick, kind, disabled, title }: { children: ReactNode; onClick?: () => void; kind?: "primary" | "danger" | "text"; disabled?: boolean; title?: string }) {
  return <button type="button" className={`mm-btn${kind ? ` mm-btn--${kind}` : ""}`} onClick={onClick} disabled={disabled} title={title}>{children}</button>;
}

/** Inline link-styled action; `href` makes it a real link. */
export function Link({ children, onClick, href }: { children: ReactNode; onClick?: (e: MouseEvent) => void; href?: string }) {
  return href ? <a className="mm-link" href={href} onClick={onClick}>{children}</a> : <button type="button" className="mm-link" onClick={onClick}>{children}</button>;
}

/** An 11px key above a control. `wide` spans the whole grid row. */
export function Field({ label, hint, children, wide }: { label: ReactNode; hint?: string; children: ReactNode; wide?: boolean }) {
  return (
    <label className={`mm-field${wide ? " mm-field--wide" : ""}`} title={hint}>
      <span className="mm-key">{label}</span>
      {children}
    </label>
  );
}

/** Fields in a 1px-gap grid: the same look as a scorecard, but every cell is editable. */
export function FieldGrid({ children, min = 150 }: { children: ReactNode; min?: number }) {
  return <div className="mm-grid" style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${min}px, 1fr))` }}>{children}</div>;
}

export function TextInput({ value, onChange, placeholder, type = "text", className, ariaLabel }:
  { value: string; onChange: (v: string) => void; placeholder?: string; type?: "text" | "date" | "search"; className?: string; ariaLabel?: string }) {
  return <input type={type} className={`mm-control${className ? ` ${className}` : ""}`} value={value} placeholder={placeholder} aria-label={ariaLabel} onChange={(e) => onChange(e.target.value)} />;
}

/** Number input that only reports finite values; the field keeps whatever the user is mid-typing. */
export function NumberInput({ value, onChange, min, max, step, disabled, className, ariaLabel }:
  { value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number; disabled?: boolean; className?: string; ariaLabel?: string }) {
  const handle = (e: ChangeEvent<HTMLInputElement>) => { const v = e.target.valueAsNumber; if (Number.isFinite(v)) onChange(v); };
  return <input type="number" className={`mm-control${className ? ` ${className}` : ""}`} value={value} min={min} max={max} step={step} disabled={disabled} aria-label={ariaLabel} onChange={handle} />;
}

export interface Option<T extends string> { value: T; label: string; group?: string }

/** Native select; options that carry a `group` are shown under an optgroup of that name. */
export function SelectInput<T extends string>({ value, onChange, options, placeholder, className, ariaLabel }:
  { value: T | ""; onChange: (v: T) => void; options: Option<T>[]; placeholder?: string; className?: string; ariaLabel?: string }) {
  const groups = new Map<string, Option<T>[]>();
  const plain: Option<T>[] = [];
  for (const o of options) { if (o.group) { if (!groups.has(o.group)) groups.set(o.group, []); groups.get(o.group)!.push(o); } else plain.push(o); }
  return (
    <select className={`mm-control${className ? ` ${className}` : ""}`} value={value} aria-label={ariaLabel} onChange={(e) => e.target.value && onChange(e.target.value as T)}>
      {placeholder && <option value="">{placeholder}</option>}
      {plain.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      {[...groups.entries()].map(([g, items]) => <optgroup key={g} label={g}>{items.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</optgroup>)}
    </select>
  );
}

/** A titled block: 13px heading, mono count, muted note on the right, then content. */
export function Block({ title, count, note, noteTone, children }: { title: ReactNode; count?: number | string; note?: ReactNode; noteTone?: "ok" | "bad"; children: ReactNode }) {
  return (
    <section className="mm-block">
      <h2><span className="mm-title">{title}{count !== undefined && <span className="mm-count" style={{ marginLeft: 8 }}>{count}</span>}</span>{note && <span className={`mm-note${noteTone ? ` ${noteTone}` : ""}`}>{note}</span>}</h2>
      {children}
    </section>
  );
}

export interface Column { label: ReactNode; num?: boolean; width?: number | string; optional?: boolean }
export interface Row { key: string; cells: ReactNode[]; selected?: boolean; onClick?: () => void; group?: boolean }

/**
 * Hairline table. A `group` row spans all columns as a sub-heading; clickable rows highlight on hover and
 * when selected. Optional columns are dropped (not just hidden: fixed table layout keeps hidden cells' widths)
 * when the wrapper is narrower than `NARROW`, i.e. while the results panel takes most of the width.
 */
const NARROW = 640;
export function Table({ columns, rows, label }: { columns: Column[]; rows: Row[]; label: string }) {
  const wrap = useRef<HTMLDivElement>(null);
  const [narrow, setNarrow] = useState(false);
  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const check = () => setNarrow(el.clientWidth < NARROW);
    check();
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const keep = columns.map((c) => !(narrow && c.optional));
  const shown = columns.filter((_, i) => keep[i]);
  const cls = (c?: Column) => (c?.num ? "num" : undefined);
  return (
    <div className="mm-table-wrap" ref={wrap}>
    <table className="mm-table" aria-label={label}>
      <thead><tr>{shown.map((c, i) => <th key={i} className={cls(c)} style={{ width: c.width }}>{c.label}</th>)}</tr></thead>
      <tbody>
        {rows.map((r) => r.group ? (
          <tr key={r.key} className="mm-group"><td colSpan={shown.length}>{r.cells[0]}</td></tr>
        ) : (
          <tr key={r.key} data-clickable={r.onClick ? "" : undefined} aria-selected={r.onClick ? !!r.selected : undefined} onClick={r.onClick}
            tabIndex={r.onClick ? 0 : undefined} onKeyDown={(e) => { if (r.onClick && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); r.onClick(); } }}>
            {r.cells.filter((_, i) => keep[i]).map((cell, i) => <td key={i} className={cls(shown[i])}>{cell}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  );
}

export function Tag({ tone, children }: { tone?: "ok" | "warn" | "bad" | "dim"; children: ReactNode }) {
  return <span className={`mm-tag${tone ? ` ${tone}` : ""}`}>{children}</span>;
}

/** Status word coloured by meaning: green when done or accepted, amber while moving, red on failure. */
export function StatusTag({ status }: { status: string }) {
  const tone = ["已完成", "接受", "completed"].includes(status) ? "ok"
    : ["执行失败", "拒绝", "失败", "failed"].includes(status) ? "bad"
    : ["运行中", "启动中", "running", "queued", "排队中", "加载中"].includes(status) ? "warn" : "dim";
  return <Tag tone={tone}>{status}</Tag>;
}

/** Signed number in mono: green above zero, red below, em dash when missing. */
export function Num({ value, digits = 4, format }: { value?: number | null; digits?: number; format?: (v: number) => string }) {
  if (typeof value !== "number" || !Number.isFinite(value)) return <span className="mm-dim">—</span>;
  const text = format ? format(value) : value.toFixed(digits);
  return <span className={value > 0 ? "mm-pos" : value < 0 ? "mm-neg" : undefined}>{value > 0 && !format ? "+" : ""}{text}</span>;
}

/** Left-rule note for warnings, errors and information; actions sit to the right of the text. */
export function Note({ tone = "warn", children, actions }: { tone?: "warn" | "bad" | "info"; children: ReactNode; actions?: ReactNode }) {
  return <div className={`mm-note-box ${tone}`} role={tone === "bad" ? "alert" : undefined}><span style={{ flex: 1, minWidth: 0 }}>{children}</span>{actions}</div>;
}

export function Empty({ children }: { children: ReactNode }) { return <div className="mm-empty">{children}</div>; }
export function P({ children }: { children: ReactNode }) { return <p className="mm-p">{children}</p>; }
