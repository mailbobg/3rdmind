import type { TraceEvent } from "../api/studio";

/** The four steps every RD-Agent research round goes through, in order. */
export const STEPS = ["hypothesis", "coding", "evaluation", "feedback"] as const;
export type StepKey = (typeof STEPS)[number];
export const STEP_LABELS: Record<StepKey, string> = { hypothesis: "提假设", coding: "写代码", evaluation: "Qlib 评估", feedback: "评估结论" };

export interface StepState {
  key: StepKey;
  label: string;
  /** done: finished; current: in progress (only on a running round); pending: not started. */
  state: "done" | "current" | "pending";
  startedAt: number | null;
  endedAt: number | null;
  /** Coding iterations seen so far (the coder may loop several times before its code passes). */
  iterations?: number;
}

export interface RoundProgress {
  id: string;
  steps: StepState[];
  startedAt: number | null;
  endedAt: number | null;
  /** Total ms for a finished round; for a running one, ms so far. */
  elapsed: number | null;
  finished: boolean;
}

const ts = (e: TraceEvent | undefined) => (e ? new Date(e.timestamp).getTime() : null);

/**
 * Per-round step timeline from the trace events. A step starts when the previous one ends (the hypothesis
 * step starts with the round's first event); it ends at the last event that belongs to it. On a running trace
 * the first unfinished step of the last round is "current".
 */
export function roundProgress(events: TraceEvent[], running: boolean, now = Date.now()): RoundProgress[] {
  const byRound = new Map<string, TraceEvent[]>();
  for (const e of events) {
    if (e.loop_id === undefined || e.loop_id === null) continue;
    const id = String(e.loop_id);
    if (!byRound.has(id)) byRound.set(id, []);
    byRound.get(id)!.push(e);
  }
  const rounds = [...byRound.entries()].sort((a, b) => Number(a[0]) - Number(b[0]));
  return rounds.map(([id, list], index) => {
    const sorted = [...list].sort((a, b) => a.timestamp.localeCompare(b.timestamp));
    const last = (pred: (e: TraceEvent) => boolean) => { const hits = sorted.filter(pred); return hits[hits.length - 1]; };
    const hypothesis = last((e) => e.tag === "research.hypothesis");
    const codes = sorted.filter((e) => e.tag === "evolving.codes" || e.tag === "evolving.feedbacks");
    const codingEnd = last((e) => e.tag === "evolving.codes");
    const evaluation = last((e) => e.tag === "feedback.metric" || e.tag === "feedback.return_chart");
    const feedback = last((e) => e.tag === "feedback.hypothesis_feedback");
    const roundStart = ts(sorted[0]);
    const ends: (number | null)[] = [ts(hypothesis), ts(codingEnd), ts(evaluation), ts(feedback)];
    const isLast = index === rounds.length - 1;
    const steps: StepState[] = [];
    let cursor = roundStart;
    let currentAssigned = false;
    STEPS.forEach((key, i) => {
      const endedAt = ends[i];
      let state: StepState["state"];
      if (endedAt != null) state = "done";
      else if (running && isLast && !currentAssigned) { state = "current"; currentAssigned = true; }
      else state = "pending";
      steps.push({
        key, label: STEP_LABELS[key], state,
        startedAt: state === "pending" ? null : cursor,
        endedAt,
        iterations: key === "coding" ? new Set(codes.map((e) => String(e.evo_id ?? 0))).size || undefined : undefined,
      });
      if (endedAt != null) cursor = endedAt;
    });
    const finished = ends[3] != null;
    const endedAt = finished ? ends[3] : null;
    const elapsed = roundStart == null ? null : (finished ? endedAt! : running && isLast ? now : (ts(sorted[sorted.length - 1]) ?? roundStart)) - roundStart;
    return { id, steps, startedAt: roundStart, endedAt, elapsed, finished };
  });
}

/** Median duration of the finished rounds, or null when there is none to learn from. */
export function medianRoundMs(rounds: RoundProgress[]): number | null {
  const done = rounds.filter((r) => r.finished && r.elapsed != null).map((r) => r.elapsed!).sort((a, b) => a - b);
  if (!done.length) return null;
  const mid = Math.floor(done.length / 2);
  return done.length % 2 ? done[mid] : (done[mid - 1] + done[mid]) / 2;
}

/** "3 分" / "1 小时 12 分" / "45 秒" for a duration in ms. */
export function fmtDuration(ms: number | null | undefined): string {
  if (ms == null || !isFinite(ms) || ms < 0) return "—";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s} 秒`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} 分`;
  return `${Math.floor(m / 60)} 小时 ${m % 60} 分`;
}

/** A one-line description of where a running round is: "第 2 轮 · 写代码 · 第 3 次迭代 · 已 6 分". */
export function progressLine(rounds: RoundProgress[], now = Date.now()): string {
  const current = rounds[rounds.length - 1];
  if (!current) return "";
  const step = current.steps.find((s) => s.state === "current");
  if (!step) return current.finished ? `第 ${Number(current.id) + 1} 轮完成` : "";
  const since = step.startedAt != null ? now - step.startedAt : null;
  const iter = step.key === "coding" && step.iterations ? ` · 第 ${step.iterations} 次迭代` : "";
  return `第 ${Number(current.id) + 1} 轮 · ${step.label}${iter}${since != null ? ` · 已 ${fmtDuration(since)}` : ""}`;
}
