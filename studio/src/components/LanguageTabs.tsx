import { useLayoutEffect, useRef, useState } from "react";
import { type Lang, lang, setLang, t } from "../i18n";

/**
 * Language switch in the rail, after beui.dev's pill tabs: a rounded track with one dark pill that glides
 * to the chosen tab (position and width animate on a settling curve, no overshoot), white text on the pill,
 * muted text elsewhere. The pill moves first and the page reloads into the other language right after
 * (see i18n.ts), so the glide is visible.
 */
const TABS: { value: Lang; label: string }[] = [
  { value: "zh", label: "中文" },
  { value: "en", label: "English" },
];

export function LanguageTabs() {
  const [active, setActive] = useState<Lang>(lang);
  const [pill, setPill] = useState<{ x: number; w: number } | null>(null);
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  useLayoutEffect(() => {
    const el = refs.current[active];
    if (el) setPill({ x: el.offsetLeft, w: el.offsetWidth });
  }, [active]);

  const choose = (value: Lang) => {
    if (value === active) return;
    setActive(value);
    window.setTimeout(() => setLang(value), 340);
  };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const i = TABS.findIndex((x) => x.value === active);
    const next = TABS[(i + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length];
    refs.current[next.value]?.focus();
    choose(next.value);
  };

  return (
    <div role="tablist" aria-label={t("界面语言")} className="lang-tabs" onKeyDown={onKey}>
      {pill && <span aria-hidden className="lang-tabs__pill" style={{ transform: `translateX(${pill.x}px)`, width: pill.w }} />}
      {TABS.map((tab) => (
        <button key={tab.value} ref={(el) => { refs.current[tab.value] = el; }} type="button" role="tab"
          aria-selected={tab.value === active} tabIndex={tab.value === active ? 0 : -1}
          className="lang-tabs__tab" data-active={tab.value === active || undefined} onClick={() => choose(tab.value)}>
          {tab.label}
        </button>
      ))}
    </div>
  );
}
