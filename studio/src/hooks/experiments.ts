import type { ExperimentStatus, ExperimentSummary } from "../api/studio";

export const EXPERIMENT_STATUS_LABELS: Record<ExperimentStatus | "unloaded", string> = {
  starting: "启动中", running: "运行中", completed: "已完成", stopped: "已停止", failed: "执行失败", ended: "已结束", unloaded: "未加载",
};

/** A row of the experiment list: every known trace id, with its summary when the server has loaded it. */
export interface ExperimentRow {
  id: string;
  scenario: string;
  market?: string;
  status: ExperimentStatus | "unloaded";
  rounds: number | null;
  accepted: number | null;
  updated: string | null;
  hypothesis: string | null;
}

const RANK: Record<ExperimentRow["status"], number> = { running: 0, starting: 0, completed: 1, stopped: 1, failed: 1, ended: 1, unloaded: 2 };

/**
 * Merge the server's trace ids with the summaries of the loaded ones. Live runs come first, then the
 * rest by last update (newest first), and traces the server never loaded at the end, by name.
 */
export function mergeExperiments(ids: string[], summaries: ExperimentSummary[]): ExperimentRow[] {
  const byId = new Map(summaries.map((s) => [s.id, s]));
  const rows = ids.map<ExperimentRow>((id) => {
    const s = byId.get(id);
    return s
      ? { id, scenario: s.scenario, market: s.market, status: s.status, rounds: s.rounds, accepted: s.accepted, updated: s.updated, hypothesis: s.hypothesis }
      : { id, scenario: id.split("/")[0], status: "unloaded", rounds: null, accepted: null, updated: null, hypothesis: null };
  });
  return rows.sort((a, b) => RANK[a.status] - RANK[b.status] || (b.updated || "").localeCompare(a.updated || "") || a.id.localeCompare(b.id));
}

/** ISO timestamp → "09-02 12:00" in the viewer's local time; anything unparsable is shown as is. */
export function shortTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const two = (n: number) => String(n).padStart(2, "0");
  return `${two(d.getMonth() + 1)}-${two(d.getDate())} ${two(d.getHours())}:${two(d.getMinutes())}`;
}
