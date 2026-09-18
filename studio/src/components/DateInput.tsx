import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { lang, t } from "../i18n";

/**
 * Date field: type or pick. The box takes anything that reads as a date (2025-09-17, 2025/9/17, 20250917,
 * 2025.9.17) and normalises it on Enter or blur; the calendar button opens a popover with a month grid,
 * a month/year picker, bounds (days outside min…max are disabled) and shortcuts (today, the last data day,
 * one year back). Arrow keys move a day in the grid, PageUp/PageDown a month, Enter picks, Escape closes.
 * Values are ISO dates (YYYY-MM-DD) or "".
 */
export interface DatePreset { label: string; value: string }

const WEEKDAYS_ZH = ["一", "二", "三", "四", "五", "六", "日"];
const WEEKDAYS_EN = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];
const MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const pad = (n: number) => String(n).padStart(2, "0");
export const isoDate = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const fromIso = (s: string) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
const shift = (iso: string, days: number) => { const d = fromIso(iso); d.setDate(d.getDate() + days); return isoDate(d); };
const shiftMonth = (iso: string, months: number) => { const d = fromIso(iso); const day = d.getDate(); d.setDate(1); d.setMonth(d.getMonth() + months); d.setDate(Math.min(day, daysIn(d.getFullYear(), d.getMonth()))); return isoDate(d); };
const daysIn = (y: number, m: number) => new Date(y, m + 1, 0).getDate();

/** Loose parse of what a person types; null when it is not a date. */
export function parseDate(text: string): string | null {
  const s = text.trim().replace(/[年月./]/g, "-").replace(/日/g, "");
  let m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(s);
  if (!m) { const n = /^(\d{4})(\d{2})(\d{2})$/.exec(s); if (n) m = n; }
  if (!m) return null;
  const y = Number(m[1]), mo = Number(m[2]), d = Number(m[3]);
  if (mo < 1 || mo > 12 || d < 1 || d > daysIn(y, mo - 1)) return null;
  return `${y}-${pad(mo)}-${pad(d)}`;
}

export function DateInput({ value, onChange, min, max, presets, placeholder, ariaLabel, className }: {
  value: string; onChange: (v: string) => void; min?: string | null; max?: string | null; presets?: DatePreset[]; placeholder?: string; ariaLabel?: string; className?: string }) {
  const [text, setText] = useState(value);
  const [bad, setBad] = useState(false);
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"days" | "months">("days");
  // The month on show and the keyboard cursor, both ISO; the cursor doubles as the "active" day.
  const [cursor, setCursor] = useState(value || isoDate(new Date()));
  const [box, setBox] = useState<{ top: number; left: number; up: boolean } | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  useEffect(() => { setText(value); setBad(false); }, [value]);

  const within = (iso: string) => (!min || iso >= min) && (!max || iso <= max);
  const commitText = () => {
    if (!text.trim()) { setBad(false); if (value) onChange(""); return; }
    const parsed = parseDate(text);
    if (parsed && within(parsed)) { setBad(false); setText(parsed); if (parsed !== value) onChange(parsed); }
    else { setBad(true); }
  };
  const pick = (iso: string) => { if (!within(iso)) return; onChange(iso); setText(iso); setBad(false); setOpen(false); input.current?.focus(); };

  const place = () => {
    const r = wrap.current?.getBoundingClientRect();
    if (!r) return;
    const height = 312;
    const up = window.innerHeight - r.bottom - 12 < height && r.top > height;
    setBox({ top: up ? r.top - 4 : r.bottom + 4, left: Math.max(12, Math.min(r.left, window.innerWidth - 292)), up });
  };
  const openPop = () => { setCursor(value && parseDate(value) ? value : clamp(isoDate(new Date()))); setMode("days"); setOpen(true); };
  const clamp = (iso: string) => (min && iso < min ? min : max && iso > max ? max : iso);
  useLayoutEffect(() => { if (open) place(); }, [open]);
  useEffect(() => {
    if (!open) return;
    const inside = (e: EventTarget | null) => !!e && (wrap.current?.contains(e as Node) || pop.current?.contains(e as Node));
    const onDown = (e: PointerEvent) => { if (!inside(e.target)) setOpen(false); };
    const onScroll = (e: Event) => { if (!inside(e.target)) setOpen(false); };
    const onResize = () => setOpen(false);
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onResize);
    return () => { document.removeEventListener("pointerdown", onDown); document.removeEventListener("scroll", onScroll, true); window.removeEventListener("resize", onResize); };
  }, [open]);
  useEffect(() => { if (open) pop.current?.querySelector<HTMLElement>('[data-cursor="true"]')?.focus(); }, [open, cursor, mode]);

  const onInputKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") { e.preventDefault(); commitText(); }
    else if (e.key === "ArrowDown" && !open) { e.preventDefault(); openPop(); }
    else if (e.key === "Escape" && open) { setOpen(false); }
  };
  const onGridKey = (e: React.KeyboardEvent) => {
    const moves: Record<string, () => string> = {
      ArrowLeft: () => shift(cursor, -1), ArrowRight: () => shift(cursor, 1), ArrowUp: () => shift(cursor, -7), ArrowDown: () => shift(cursor, 7),
      PageUp: () => shiftMonth(cursor, e.shiftKey ? -12 : -1), PageDown: () => shiftMonth(cursor, e.shiftKey ? 12 : 1),
      Home: () => cursor.slice(0, 8) + "01", End: () => cursor.slice(0, 8) + pad(daysIn(Number(cursor.slice(0, 4)), Number(cursor.slice(5, 7)) - 1)),
    };
    if (moves[e.key]) { e.preventDefault(); setCursor(moves[e.key]()); }
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(cursor); }
    else if (e.key === "Escape") { e.preventDefault(); setOpen(false); input.current?.focus(); }
  };

  const year = Number(cursor.slice(0, 4)), month = Number(cursor.slice(5, 7)) - 1;
  const today = isoDate(new Date());
  const cells = useMemo(() => {
    const first = new Date(year, month, 1);
    const lead = (first.getDay() + 6) % 7; // Monday first
    const out: string[] = [];
    for (let i = -lead; out.length < 42; i++) out.push(isoDate(new Date(year, month, 1 + i)));
    return out;
  }, [year, month]);
  const monthLabel = lang === "en" ? `${MONTHS_EN[month]} ${year}` : `${year} 年 ${month + 1} 月`;
  const shortcuts: DatePreset[] = [{ label: t("今天"), value: today }, ...(presets || [])].filter((p, i, all) => p.value && within(p.value) && all.findIndex((q) => q.value === p.value) === i);

  return (
    <div ref={wrap} className={`mm-date${className ? ` ${className}` : ""}`}>
      <input ref={input} type="text" inputMode="numeric" className={`mm-control mm-date__input${bad ? " mm-date__input--bad" : ""}`} value={text} placeholder={placeholder || "YYYY-MM-DD"}
        aria-label={ariaLabel} aria-invalid={bad || undefined} title={bad ? t("看不懂这个日期，试试 2025-09-17 或 20250917") : undefined} spellCheck={false} autoComplete="off"
        onChange={(e) => { setText(e.target.value); setBad(false); }} onBlur={commitText} onKeyDown={onInputKey} />
      <button type="button" className="mm-date__toggle" aria-label={t("打开日历")} aria-expanded={open} tabIndex={-1} onClick={() => (open ? setOpen(false) : openPop())}>
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden>
          <rect x="2" y="3" width="12" height="11" rx="1.5" /><path d="M2 6.5h12M5.5 1.5v3M10.5 1.5v3" strokeLinecap="round" />
        </svg>
      </button>
      {open && box && createPortal(
        <div ref={pop} className={`mm-date__pop${box.up ? " mm-date__pop--up" : ""}`} role="dialog" aria-label={ariaLabel || t("选择日期")}
          style={{ top: box.up ? undefined : box.top, bottom: box.up ? window.innerHeight - box.top : undefined, left: box.left }} onKeyDown={onGridKey}>
          <div className="mm-date__head">
            <button type="button" className="mm-date__nav" aria-label={t("上个月")} onClick={() => setCursor(shiftMonth(cursor, mode === "days" ? -1 : -12))}>‹</button>
            <button type="button" className="mm-date__month" onClick={() => setMode(mode === "days" ? "months" : "days")} aria-label={t("选择月份和年份")}>
              {mode === "days" ? monthLabel : lang === "en" ? String(year) : `${year} 年`}
            </button>
            <button type="button" className="mm-date__nav" aria-label={t("下个月")} onClick={() => setCursor(shiftMonth(cursor, mode === "days" ? 1 : 12))}>›</button>
          </div>
          {mode === "days" ? (
            <div className="mm-date__grid" role="grid">
              {(lang === "en" ? WEEKDAYS_EN : WEEKDAYS_ZH).map((w) => <span key={w} className="mm-date__wd">{w}</span>)}
              {cells.map((iso) => {
                const inMonth = iso.slice(0, 7) === cursor.slice(0, 7);
                const disabled = !within(iso);
                return (
                  <button key={iso} type="button" role="gridcell" tabIndex={iso === cursor ? 0 : -1} data-cursor={iso === cursor || undefined} disabled={disabled}
                    className={`mm-date__day${inMonth ? "" : " mm-date__day--out"}${iso === value ? " mm-date__day--picked" : ""}${iso === today ? " mm-date__day--today" : ""}`}
                    aria-selected={iso === value} aria-label={iso} onClick={() => pick(iso)} onMouseEnter={() => !disabled && setCursor(iso)}>
                    {Number(iso.slice(8, 10))}
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="mm-date__months">
              {Array.from({ length: 12 }, (_, m) => {
                const first = `${year}-${pad(m + 1)}-01`, last = `${year}-${pad(m + 1)}-${pad(daysIn(year, m))}`;
                const disabled = (!!max && first > max) || (!!min && last < min);
                return (
                  <button key={m} type="button" disabled={disabled} className={`mm-date__mon${m === month ? " mm-date__mon--picked" : ""}`}
                    onClick={() => { setCursor(clamp(`${year}-${pad(m + 1)}-${pad(Math.min(Number(cursor.slice(8, 10)), daysIn(year, m)))}`)); setMode("days"); }}>
                    {lang === "en" ? MONTHS_EN[m] : `${m + 1} 月`}
                  </button>
                );
              })}
            </div>
          )}
          {shortcuts.length > 0 && (
            <div className="mm-date__foot">
              {shortcuts.map((p) => <button key={p.label} type="button" className="mm-date__preset" onClick={() => pick(p.value)}>{p.label}<span className="mm-date__preset-date">{p.value}</span></button>)}
            </div>
          )}
        </div>,
        document.body,
      )}
    </div>
  );
}
