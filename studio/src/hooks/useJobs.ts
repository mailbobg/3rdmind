import { useCallback, useEffect, useRef, useState } from "react";
import * as studio from "../api/studio";
import type { Job } from "../api/studio";
import type { Toast } from "./useToasts";

export const JOB_KIND_LABELS: Record<string, string> = {
  research: "研究", backtest: "回测", search: "组合搜索", diagnose: "拆开回测", refresh: "重算到最新",
  universe: "准备股票池数据", strategy_update: "更新策略", sync: "同步数据", build: "重建数据",
};

/**
 * The background-work list for the current workspace, polled every 5 s. `active` is everything queued or
 * running; a job seen finishing since the last poll is announced through `notify` (toast + optional desktop
 * notification) and, when it failed, kept in `failures` until dismissed.
 */
export function useJobs(enabled: boolean, notify: (t: Omit<Toast, "id" | "at">) => void, desktop: boolean, onOpen: (j: Job) => void) {
  const [active, setActive] = useState<Job[]>([]);
  const [failures, setFailures] = useState<Job[]>([]);
  const cursor = useRef<string | null>(null);
  const known = useRef<Set<string>>(new Set());
  const dismissFailure = useCallback((id: string) => setFailures((list) => list.filter((j) => j.id !== id)), []);
  useEffect(() => {
    if (!enabled) return;
    let stop = false;
    const poll = async () => {
      try {
        const r = await studio.jobs(cursor.current || undefined);
        if (stop) return;
        const live = r.items.filter((j) => j.status === "queued" || j.status === "running");
        setActive(live);
        if (cursor.current) {
          // Finished since the last look: research rounds/runs have their own announcements (/studio/recent).
          for (const j of r.items) {
            if (j.status !== "completed" && j.status !== "failed") continue;
            if (j.kind === "research" || known.current.has(`${j.id}@${j.finished}`)) continue;
            known.current.add(`${j.id}@${j.finished}`);
            const ok = j.status === "completed";
            const body = ok ? summarize(j) : j.error || undefined;
            notify({ tone: ok ? "ok" : "bad", title: `${j.label} ${ok ? "完成" : "失败"}`, body, trace: undefined, job: j });
            if (!ok) setFailures((list) => [...list.filter((f) => f.id !== j.id), j]);
            if (desktop && typeof Notification !== "undefined" && Notification.permission === "granted") {
              const n = new Notification(`${j.label} ${ok ? "完成" : "失败"}`, { body, tag: j.id });
              n.onclick = () => { window.focus(); onOpen(j); n.close(); };
            }
          }
        }
        cursor.current = r.now;
      } catch { /* backend away */ }
    };
    poll();
    const t = setInterval(poll, 5000);
    return () => { stop = true; clearInterval(t); };
  }, [enabled, notify, desktop, onOpen]);
  return { active, failures, dismissFailure };
}

function summarize(j: Job): string | undefined {
  const r = j.result || {};
  if (j.kind === "backtest" && r.total_return != null) return `总收益 ${r.total_return >= 0 ? "+" : ""}${(r.total_return * 100).toFixed(1)}%`;
  if (j.kind === "search" && Array.isArray(r.recommended)) return `推荐 ${r.recommended.length} 个信号`;
  if (j.kind === "refresh" && r.end) return `数据到 ${r.end}`;
  if (j.kind === "strategy_update") return r.failures?.length ? `${r.failures.length} 个因子重算失败，回测已启动` : "已启动跟踪回测";
  return undefined;
}
