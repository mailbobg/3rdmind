import type React from "react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
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

export interface Option<T extends string> {
  value: T; label: string; group?: string;
  /** Secondary text shown right-aligned and muted (a count, a benchmark, a date span). */
  hint?: string;
  disabled?: boolean;
}

/** Options that need a filter box: above this many, the list opens with a search field focused. */
const SEARCH_FROM = 8;

/**
 * Select with its own list: the OS popup of a native <select> renders outside the page's styling (and
 * unreliably inside the desktop app), so the trigger is a button and the options are a fixed-position
 * list portalled to <body>.
 *
 * Interaction: click or ArrowDown/Enter/Space opens; Arrow keys move the highlight (wrapping), Home/End jump,
 * Enter picks, Escape closes and returns focus; typing on a closed or unfiltered list jumps to the first label
 * starting with those letters. Long lists (≥ 8) open with a filter box that matches label, value and hint.
 * The list flips above the trigger when there is more room there, and closes on outside click, page scroll
 * or resize. Groups render as headings; a hint renders muted on the right; the selected option shows a check.
 */
export function SelectInput<T extends string>({ value, onChange, options, placeholder, className, ariaLabel, searchable }:
  { value: T | ""; onChange: (v: T) => void; options: Option<T>[]; placeholder?: string; className?: string; ariaLabel?: string; searchable?: boolean }) {
  const [open, setOpen] = useState(false);
  const [box, setBox] = useState<{ top: number; left: number; width: number; maxHeight: number; up: boolean } | null>(null);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(-1);
  const trigger = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const typed = useRef<{ text: string; at: number }>({ text: "", at: 0 });
  const id = useMemo(() => `sel${Math.random().toString(36).slice(2, 8)}`, []);
  const current = options.find((o) => o.value === value);
  const withSearch = searchable ?? options.length >= SEARCH_FROM;
  const q = query.trim().toLowerCase();
  const visible = useMemo(() => (q ? options.filter((o) => `${o.label} ${o.value} ${o.hint || ""}`.toLowerCase().includes(q)) : options), [options, q]);
  const enabled = visible.filter((o) => !o.disabled);

  const place = () => {
    const t = trigger.current;
    if (!t) return;
    const r = t.getBoundingClientRect();
    const below = window.innerHeight - r.bottom - 12;
    const above = r.top - 12;
    const wanted = Math.min(360, 8 + visible.length * 30 + (withSearch ? 38 : 0) + (new Set(visible.map((o) => o.group).filter(Boolean)).size * 24));
    const up = below < Math.min(wanted, 200) && above > below;
    const maxHeight = Math.max(120, Math.min(360, up ? above : below));
    setBox({ top: up ? r.top - 4 : r.bottom + 4, left: r.left, width: r.width, maxHeight, up });
  };
  const openList = () => {
    setQuery("");
    const i = visible.findIndex((o) => o.value === value && !o.disabled);
    setActive(i >= 0 ? i : enabled.length ? visible.indexOf(enabled[0]) : -1);
    setOpen(true);
  };
  const close = (refocus = true) => { setOpen(false); if (refocus) trigger.current?.focus(); };
  useLayoutEffect(() => { if (open) place(); }, [open, visible.length]); // eslint-disable-line react-hooks/exhaustive-deps
  useLayoutEffect(() => {
    if (!open || !box) return;
    if (withSearch) search.current?.focus();
    list.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: "nearest" });
  }, [open, box, active, withSearch]);
  useEffect(() => {
    if (!open) return;
    const inside = (t: EventTarget | null) => !!t && (trigger.current?.contains(t as Node) || list.current?.contains(t as Node));
    const onPointer = (e: PointerEvent) => { if (!inside(e.target)) close(false); };
    // The list's own scrolling (including scrollIntoView) must not close it; page scrolling does.
    const onScroll = (e: Event) => { if (!inside(e.target)) close(false); };
    const onResize = () => close(false);
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onResize);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onResize);
    };
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  // A filtered list keeps its highlight on a visible option.
  useEffect(() => { if (open && (active < 0 || active >= visible.length || visible[active]?.disabled)) setActive(enabled.length ? visible.indexOf(enabled[0]) : -1); }, [visible, enabled, open, active]);

  const pick = (o: Option<T>) => { if (o.disabled) return; close(); if (o.value !== value) onChange(o.value); };
  const move = (delta: number) => {
    if (!enabled.length) return;
    const pos = enabled.findIndex((o) => o === visible[active]);
    const next = enabled[((pos < 0 ? (delta > 0 ? -1 : 0) : pos) + delta + enabled.length) % enabled.length];
    setActive(visible.indexOf(next));
  };
  const jumpTo = (letters: string) => {
    const l = letters.toLowerCase();
    const hit = enabled.find((o) => o.label.toLowerCase().startsWith(l)) || enabled.find((o) => o.label.toLowerCase().includes(l));
    if (!hit) return;
    if (open) setActive(visible.indexOf(hit)); else onChange(hit.value);
  };
  const typeAhead = (key: string) => {
    const now = Date.now();
    typed.current = { text: now - typed.current.at < 700 ? typed.current.text + key : key, at: now };
    jumpTo(typed.current.text);
  };
  const onTriggerKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter" || e.key === " ") { e.preventDefault(); if (!open) openList(); else if (e.key === "Enter" || e.key === " ") { const o = visible[active]; if (o) pick(o); } else move(e.key === "ArrowDown" ? 1 : -1); }
    else if (e.key === "Escape" && open) { e.preventDefault(); close(); }
    else if (e.key === "Home" && open) { e.preventDefault(); if (enabled[0]) setActive(visible.indexOf(enabled[0])); }
    else if (e.key === "End" && open) { e.preventDefault(); if (enabled.length) setActive(visible.indexOf(enabled[enabled.length - 1])); }
    else if (e.key.length === 1 && !e.metaKey && !e.ctrlKey && !e.altKey && !(open && withSearch)) { typeAhead(e.key); }
  };
  const onSearchKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); move(e.key === "ArrowDown" ? 1 : -1); }
    else if (e.key === "Enter") { e.preventDefault(); const o = visible[active]; if (o) pick(o); }
    else if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "Home" || e.key === "End") { if (!e.currentTarget.value) { e.preventDefault(); const o = e.key === "Home" ? enabled[0] : enabled[enabled.length - 1]; if (o) setActive(visible.indexOf(o)); } }
    else if (e.key === "Tab") { close(false); }
  };

  // Options keep their order; a group heading is emitted where a new group starts.
  const items: ReactNode[] = [];
  let lastGroup: string | undefined;
  visible.forEach((o, i) => {
    if (o.group && o.group !== lastGroup) items.push(<div key={`g:${o.group}`} className="mm-select__group" role="presentation">{o.group}</div>);
    lastGroup = o.group;
    items.push(
      <div key={o.value} id={`${id}-${i}`} role="option" aria-selected={o.value === value} aria-disabled={o.disabled || undefined} data-active={i === active || undefined}
        className="mm-select__option" onPointerMove={() => { if (!o.disabled && active !== i) setActive(i); }} onClick={() => pick(o)}>
        <span className="mm-select__label">{o.label}</span>
        {o.hint && <span className="mm-select__hint">{o.hint}</span>}
        <span className="mm-select__check" aria-hidden>{o.value === value ? "✓" : ""}</span>
      </div>,
    );
  });
  return (
    <>
      <button ref={trigger} type="button" className={`mm-control mm-select${className ? ` ${className}` : ""}`} aria-label={ariaLabel} aria-haspopup="listbox" aria-expanded={open}
        aria-controls={open ? `${id}-list` : undefined} aria-activedescendant={open && active >= 0 ? `${id}-${active}` : undefined}
        onClick={() => (open ? close() : openList())} onKeyDown={onTriggerKey}>
        <span className={current ? undefined : "mm-dim"}>{current ? current.label : placeholder || ""}</span>
      </button>
      {open && box && createPortal(
        <div ref={list} id={`${id}-list`} role="listbox" aria-label={ariaLabel} className={`mm-select__list${box.up ? " mm-select__list--up" : ""}`}
          style={{ top: box.up ? undefined : box.top, bottom: box.up ? window.innerHeight - box.top : undefined, left: box.left, minWidth: box.width, maxHeight: box.maxHeight }}>
          {withSearch && (
            <div className="mm-select__search">
              <input ref={search} className="mm-control" value={query} placeholder="输入筛选…" aria-label="筛选选项" autoComplete="off" spellCheck={false}
                onChange={(e) => setQuery(e.target.value)} onKeyDown={onSearchKey} />
            </div>
          )}
          <div className="mm-select__options">
            {items.length ? items : <div className="mm-select__group">{q ? `没有匹配 “${query.trim()}” 的选项` : "没有可选项"}</div>}
          </div>
        </div>,
        document.body,
      )}
    </>
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
/** `group` rows are sub-headings spanning every column; `span` rows hold arbitrary content (e.g. a nested table) under a parent row. */
export interface Row { key: string; cells: ReactNode[]; selected?: boolean; onClick?: () => void; group?: boolean; span?: boolean; expanded?: boolean }

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
        {rows.map((r) => r.group || r.span ? (
          <tr key={r.key} className={r.group ? "mm-group" : "mm-span"}><td colSpan={shown.length}>{r.cells[0]}</td></tr>
        ) : (
          <tr key={r.key} data-clickable={r.onClick ? "" : undefined} aria-selected={r.onClick ? !!r.selected : undefined} aria-expanded={r.expanded} onClick={r.onClick}
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
