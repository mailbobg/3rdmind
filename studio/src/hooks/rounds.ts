import type { Reflection, TraceEvent } from "../api/studio";
import { t } from "../i18n";

export interface CodeFile { name: string; code: string; task: string; loop: string }
export interface RoundView {
  id: string;
  hypothesis: Record<string, any>;
  tasks: { name: string; description?: string; formulation?: string; variables?: Record<string, string> }[];
  files: CodeFile[];
  metrics: Record<string, number> | null;
  factors: string[];
  chartHtml: string;
  feedback: { decision?: boolean; reason?: string; observations?: string; hypothesis_evaluation?: string; new_hypothesis?: string } | null;
  /** 验收: the Studio's deterministic verdict on the round's factors (studio.gate), when the gate ran. */
  gate: GateResult | null;
  /** 反思备忘录 written after this round (studio.reflection), if any. */
  reflection: Reflection | null;
  /** Display status (already translated). */
  status: string;
}

export interface GateFactor { name: string; level: "signal" | "weak" | "noise" | "duplicate" | "unreplicated" | "error"; t: number | null; horizon: number | null; nearest: string | null; corr: number | null; second_market: string | null; t2: number | null; replicated: boolean | null; reasons: string[] }
export interface GateResult { factors: GateFactor[]; decision: boolean; summary: string; hint: string; market: string; second_market: string | null; thresholds: Record<string, number>;
  /** 研究记忆 handed to the agent with the hint: power, the tested-mechanism map, the run's statistics. */
  context?: string[]; reflection?: boolean | string }

const text = (value: unknown) => (typeof value === "string" ? value : JSON.stringify(value, null, 2));

function parseMetrics(value: unknown): Record<string, number> | null {
  try {
    const data = typeof value === "string" ? JSON.parse(value) : value;
    if (!data || typeof data !== "object") return null;
    return Object.fromEntries(Object.entries(data).filter(([, v]) => typeof v === "number")) as Record<string, number>;
  } catch {
    return null;
  }
}

export function groupRounds(events: TraceEvent[]): RoundView[] {
  const groups = new Map<string, TraceEvent[]>();
  for (const event of events) {
    if (event.loop_id === undefined || event.loop_id === null) continue;
    const id = String(event.loop_id);
    if (!groups.has(id)) groups.set(id, []);
    groups.get(id)!.push(event);
  }
  return [...groups.entries()].map(([id, list]) => {
    const tagged = (tag: string) => list.filter((e) => e.tag === tag);
    const hypothesisList = tagged("research.hypothesis");
    const hypothesis = hypothesisList[hypothesisList.length - 1]?.content || {};
    const metricList = tagged("feedback.metric");
    const metricEvent = metricList[metricList.length - 1];
    const feedbackList = tagged("feedback.hypothesis_feedback");
    const feedback = feedbackList[feedbackList.length - 1]?.content || null;
    const chartList = tagged("feedback.return_chart");
    const gateList = tagged("studio.gate");
    const gate: GateResult | null = gateList.length ? gateList[gateList.length - 1].content : null;
    const reflectionList = tagged("studio.reflection");
    const reflection: Reflection | null = reflectionList.length ? reflectionList[reflectionList.length - 1].content : null;
    const files: CodeFile[] = tagged("evolving.codes").flatMap((e) =>
      (Array.isArray(e.content) ? e.content : []).flatMap((task: any) =>
        Object.entries(task.workspace || {}).map(([name, code]) => ({
          name, code: text(code), task: task.target_task_name, loop: id,
        })),
      ),
    );
    const metrics = metricEvent ? parseMetrics(metricEvent.content?.result) : null;
    const status: string = feedback
      ? feedback.decision ? t("接受") : t("拒绝")
      : metricEvent ? t("评估已返回")
      : files.length ? t("代码已生成")
      : t("假设待验证");
    return {
      id,
      hypothesis,
      tasks: tagged("research.tasks").flatMap((e) => (Array.isArray(e.content) ? e.content : [e.content])),
      files,
      metrics,
      factors: (metricEvent?.content?.workspaces?.factors || []).map((f: any) => f.name),
      chartHtml: chartList[chartList.length - 1]?.content?.chart_html || "",
      feedback,
      gate,
      reflection,
      status,
    };
  });
}

export function traceStatus(events: TraceEvent[], liveness?: "alive" | "dead" | "unknown") {
  // No events yet: either the run is still starting (its process is alive), it never reported anything,
  // or the server never loaded it. Only the server knows which.
  if (!events.length) return liveness === "alive" ? t("启动中") : liveness === "dead" ? t("已结束") : t("未加载");
  const end = [...events].reverse().find((e) => e.tag.toLowerCase() === "end");
  // No END event: the process is running, or it went away without one (server restart, crash) and the
  // server tells us it is not alive.
  if (!end) return liveness === "dead" ? t("已结束") : t("运行中");
  const code = Number(end.content?.end_code);
  return code === 0 ? t("已完成") : code === -1 ? t("已停止") : t("执行失败");
}

