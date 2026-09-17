import { useCallback, useEffect, useRef, useState } from "react";
import * as studio from "../api/studio";
import type { RecentItem } from "../api/studio";

import type { Job } from "../api/studio";
import { t as tr } from "../i18n";
export interface Toast { id: string; title: string; body?: string; tone: "ok" | "bad" | "info"; trace?: string; job?: Job; at: number }

/**
 * Completion toasts: polls /studio/recent with a moving cursor (seeded on the first poll, so nothing that already
 * happened is announced) and turns new round / run completions into toasts that fade after ~8 s.
 */
export function useToasts(enabled: boolean, desktop = false, onOpen?: (trace: string) => void) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const cursor = useRef<string | null>(null);
  const dismiss = useCallback((id: string) => setToasts((list) => list.filter((t) => t.id !== id)), []);
  const push = useCallback((t: Omit<Toast, "id" | "at">) => {
    const id = Math.random().toString(36).slice(2);
    setToasts((list) => [...list.slice(-3), { ...t, id, at: Date.now() }]);
    setTimeout(() => dismiss(id), 9000);
  }, [dismiss]);
  useEffect(() => {
    if (!enabled) return;
    let stop = false;
    const poll = async () => {
      try {
        const r = await studio.recent(cursor.current || undefined);
        if (stop) return;
        if (cursor.current) {
          for (const i of r.items) {
            const t = describe(i);
            push(t);
            if (desktop && typeof Notification !== "undefined" && Notification.permission === "granted") {
              const n = new Notification(t.title, { body: t.body, tag: `${i.trace}@${i.timestamp}` });
              n.onclick = () => { window.focus(); onOpen?.(i.trace); n.close(); };
            }
          }
        }
        cursor.current = r.now;
      } catch { /* backend away */ }
    };
    poll();
    const t = setInterval(poll, 8000);
    return () => { stop = true; clearInterval(t); };
  }, [enabled, push, desktop, onOpen]);
  return { toasts, dismiss, push };
}

function describe(i: RecentItem): Omit<Toast, "id" | "at"> {
  const name = i.trace.split("/").pop() || i.trace;
  if (i.kind === "round_done") {
    const ic = i.ic != null ? ` · IC ${i.ic.toFixed(3)}` : "";
    const n = i.factors.length ? tr(" · {0} 个因子", [i.factors.length]) : "";
    return { tone: i.decision ? "ok" : "info", trace: i.trace, title: tr("{0} 第 {1} 轮完成 · {2}", [name, i.round ?? "?", i.decision ? tr("接受") : tr("拒绝")]), body: `${ic}${n}`.replace(/^ · /, "") || undefined };
  }
  return { tone: i.status === "completed" ? "ok" : i.status === "failed" ? "bad" : "info", trace: i.trace,
    title: `${name} ${i.status === "completed" ? tr("研究结束") : i.status === "failed" ? tr("研究失败") : tr("研究已停止")}`, body: i.status === "completed" ? tr("点开看总结") : undefined };
}
