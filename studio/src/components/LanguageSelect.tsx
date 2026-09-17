import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { type Lang, lang, setLang, t } from "../i18n";

/**
 * Language switch in the rail, styled after beui.dev's motion combobox: a bordered field with the current
 * language and an up/down chevron, opening a panel that springs out of the field (height, fade and a small
 * travel on one weighted curve), rich rows with an icon tile, label and detail, a highlight that glides
 * between rows, and a check on the selected one. The panel is fixed-positioned and opens upward, since the
 * trigger sits at the bottom of a scrolling rail. Choosing another language reloads the page (see i18n.ts).
 */
const OPTIONS: { value: Lang; glyph: string; label: string; detail: string }[] = [
  { value: "zh", glyph: "中", label: "中文", detail: "简体中文" },
  { value: "en", glyph: "A", label: "English", detail: "English (US)" },
];

export function LanguageSelect() {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState<Lang>(lang);
  const [height, setHeight] = useState(0);
  const [anchor, setAnchor] = useState<{ left: number; bottom: number; width: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const current = OPTIONS.find((o) => o.value === lang) ?? OPTIONS[0];

  // Measure once the panel exists; the content is static, so one measurement per open is enough.
  useLayoutEffect(() => {
    if (!open) return;
    const rect = triggerRef.current?.getBoundingClientRect();
    if (rect) setAnchor({ left: rect.left, bottom: window.innerHeight - rect.top + 6, width: rect.width });
    setHeight(contentRef.current?.offsetHeight ?? 0);
    setActive(lang);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      const target = e.target as Node;
      if (panelRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); triggerRef.current?.focus(); } };
    const onScroll = () => setOpen(false);
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", onScroll);
    return () => { document.removeEventListener("pointerdown", onDown); document.removeEventListener("keydown", onKey); window.removeEventListener("resize", onScroll); };
  }, [open]);

  const choose = (value: Lang) => { setOpen(false); if (value !== lang) setLang(value); };
  const onTriggerKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) { setOpen(true); return; }
      const i = OPTIONS.findIndex((o) => o.value === active);
      const next = OPTIONS[(i + (e.key === "ArrowDown" ? 1 : OPTIONS.length - 1)) % OPTIONS.length];
      setActive(next.value);
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (open) choose(active); else setOpen(true);
    }
  };
  const activeIndex = Math.max(0, OPTIONS.findIndex((o) => o.value === active));

  return (
    <>
      <button ref={triggerRef} type="button" className="lang-select__trigger" data-state={open ? "open" : "closed"}
        aria-label={t("界面语言")} aria-haspopup="listbox" aria-expanded={open}
        onClick={() => setOpen((v) => !v)} onKeyDown={onTriggerKey}>
        <span className="lang-select__glyph" aria-hidden>{current.glyph}</span>
        <span className="lang-select__value">{current.label}</span>
        <svg className="lang-select__chevrons" viewBox="0 0 16 16" width="14" height="14" aria-hidden>
          <path d="M5 6.2 8 3.2l3 3M5 9.8l3 3 3-3" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      <div ref={panelRef} className="lang-select__panel" data-side="top" aria-hidden={!open}
        style={{ left: anchor?.left, bottom: anchor?.bottom, width: anchor?.width, height: open ? height : 0, opacity: open ? 1 : 0, transform: open ? "translateY(0)" : "translateY(6px)", pointerEvents: open ? "auto" : "none", visibility: anchor ? "visible" : "hidden" }}>
        <div ref={contentRef} role="listbox" aria-label={t("界面语言")} className="lang-select__list">
          <span aria-hidden className="lang-select__glide" style={{ transform: `translateY(${activeIndex * 100}%)` }} />
          {OPTIONS.map((o) => (
            <button key={o.value} type="button" role="option" aria-selected={o.value === lang} tabIndex={-1}
              className="lang-select__option" data-active={o.value === active || undefined}
              onPointerMove={() => setActive(o.value)} onPointerDown={(e) => e.preventDefault()} onClick={() => choose(o.value)}>
              <span className={`lang-select__tile lang-select__tile--${o.value}`} aria-hidden>{o.glyph}</span>
              <span className="lang-select__text">
                <span className="lang-select__label">{o.label}</span>
                <span className="lang-select__detail">{o.detail}</span>
              </span>
              <svg className="lang-select__check" data-on={o.value === lang || undefined} viewBox="0 0 16 16" width="15" height="15" aria-hidden>
                <path d="M3.5 8.5 6.5 11.5 12.5 4.5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          ))}
        </div>
      </div>
    </>
  );
}
