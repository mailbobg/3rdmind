import { useCallback, useEffect, useRef, useState } from "react";
import * as studio from "../api/studio";
import type { AttentionItem } from "../api/studio";
import { persistStudioState, restoreStudioState } from "./studioStorage";
import { t as tr } from "../i18n";

export const ATTENTION_LABELS: Record<AttentionItem["kind"], string> = {
  instruction: tr("开始前的研究指示"), features: tr("基础特征集"), hypothesis: tr("这一轮的假设"), feedback: tr("这一轮的评估结论"), other: tr("一个确认"),
};

export interface NotifyPrefs { desktop: boolean; sound: boolean }

/** A short two-tone chime through WebAudio; silent when the browser refuses (autoplay policy). */
function chime() {
  try {
    const ctx = new AudioContext();
    const gain = ctx.createGain();
    gain.gain.value = 0.06;
    gain.connect(ctx.destination);
    [[660, 0], [880, 0.14]].forEach(([freq, at]) => {
      const osc = ctx.createOscillator();
      osc.type = "sine"; osc.frequency.value = freq;
      osc.connect(gain);
      osc.start(ctx.currentTime + at); osc.stop(ctx.currentTime + at + 0.16);
    });
    setTimeout(() => ctx.close(), 600);
  } catch { /* no audio */ }
}

/**
 * Runs waiting on the user, polled every 8 s for the current workspace. New items (trace + since not seen
 * before in this session) trigger a desktop notification and/or a chime when those are switched on; the
 * preferences live in the shared layout storage.
 */
export function useAttention(enabled: boolean, onOpen: (item: AttentionItem) => void) {
  const [items, setItems] = useState<AttentionItem[]>([]);
  const [prefs, setPrefsState] = useState<NotifyPrefs>(() => ({ desktop: false, sound: false, ...(restoreStudioState().layout?.notify || {}) }));
  const seen = useRef<Set<string>>(new Set());
  const first = useRef(true);
  const setPrefs = useCallback(async (patch: Partial<NotifyPrefs>) => {
    let next = { ...prefs, ...patch };
    if (patch.desktop && typeof Notification !== "undefined" && Notification.permission !== "granted") {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") next = { ...next, desktop: false };
    }
    setPrefsState(next);
    persistStudioState({ layout: { ...(restoreStudioState().layout || {}), notify: next } });
    if (patch.sound) chime();
  }, [prefs]);
  useEffect(() => {
    if (!enabled) return;
    let stop = false;
    const poll = async () => {
      try {
        const list = await studio.attention();
        if (stop) return;
        setItems(list);
        const fresh = list.filter((i) => !seen.current.has(`${i.trace}@${i.since}`));
        fresh.forEach((i) => seen.current.add(`${i.trace}@${i.since}`));
        // The first poll only learns what is already pending; later polls announce new arrivals.
        if (!first.current && fresh.length) {
          if (prefs.sound) chime();
          if (prefs.desktop && typeof Notification !== "undefined" && Notification.permission === "granted") {
            for (const i of fresh) {
              const n = new Notification(tr("RD-Agent 等你确认"), { body: tr("{0} · {1}{2}", [i.trace.split("/").pop(), ATTENTION_LABELS[i.kind], i.round ? tr("（第 {0} 轮）", [i.round]) : ""]), tag: `${i.trace}@${i.since}` });
              n.onclick = () => { window.focus(); onOpen(i); n.close(); };
            }
          }
        }
        first.current = false;
      } catch { /* backend away; keep the last list */ }
    };
    poll();
    const t = setInterval(poll, 8000);
    return () => { stop = true; clearInterval(t); };
  }, [enabled, prefs.sound, prefs.desktop, onOpen]);
  return { items, prefs, setPrefs };
}
