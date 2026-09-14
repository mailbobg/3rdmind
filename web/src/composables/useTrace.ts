import { computed, onBeforeUnmount, ref } from "vue";
import * as studio from "../api/studio";
import type { TraceEvent } from "../api/studio";

export interface CodeFile { name: string; code: string; task: string; loop: string }
export interface RoundView {
  id: string;
  hypothesis: Record<string, any>;
  tasks: { name: string; description?: string }[];
  files: CodeFile[];
  metrics: Record<string, number> | null;
  factors: string[];
  chartHtml: string;
  feedback: { decision?: boolean; reason?: string; observations?: string; hypothesis_evaluation?: string; new_hypothesis?: string } | null;
  status: "假设待验证" | "代码已生成" | "评估已返回" | "接受" | "拒绝";
}

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
    const files: CodeFile[] = tagged("evolving.codes").flatMap((e) =>
      (Array.isArray(e.content) ? e.content : []).flatMap((task: any) =>
        Object.entries(task.workspace || {}).map(([name, code]) => ({
          name, code: text(code), task: task.target_task_name, loop: id,
        })),
      ),
    );
    const metrics = metricEvent ? parseMetrics(metricEvent.content?.result) : null;
    const status: RoundView["status"] = feedback
      ? feedback.decision ? "接受" : "拒绝"
      : metricEvent ? "评估已返回"
      : files.length ? "代码已生成"
      : "假设待验证";
    return {
      id,
      hypothesis,
      tasks: tagged("research.tasks").flatMap((e) => (Array.isArray(e.content) ? e.content : [e.content])),
      files,
      metrics,
      factors: (metricEvent?.content?.workspaces?.factors || []).map((f: any) => f.name),
      chartHtml: chartList[chartList.length - 1]?.content?.chart_html || "",
      feedback,
      status,
    };
  });
}

export function traceStatus(events: TraceEvent[]) {
  if (!events.length) return "未加载" as const;
  const end = [...events].reverse().find((e) => e.tag.toLowerCase() === "end");
  if (!end) return "运行中" as const;
  const code = Number(end.content?.end_code);
  return code === 0 ? ("已完成" as const) : code === -1 ? ("已停止" as const) : ("执行失败" as const);
}

const STORAGE_KEY = "rd-studio-v3";
function restore(): { traceId?: string; acknowledged?: string[] } {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"); } catch { return {}; }
}
function persist(patch: Record<string, unknown>) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...restore(), ...patch })); } catch { /* storage unavailable */ }
}

export function useTrace() {
  const saved = restore();
  const traceId = ref(saved.traceId || "");
  const traceIds = ref<string[]>([]);
  const events = ref<TraceEvent[]>([]);
  const acknowledged = ref<string[]>(saved.acknowledged || []);
  const error = ref("");
  const busy = ref(false);
  let timer: ReturnType<typeof setTimeout> | undefined;
  let failures = 0;
  let disposed = false;

  const rounds = computed(() => groupRounds(events.value));
  const status = computed(() => traceStatus(events.value));
  const active = computed(() => status.value === "运行中");
  const interactionKey = (e: TraceEvent) => `${traceId.value}:${e.timestamp}:${JSON.stringify(e.content)}`;
  const interaction = computed(() =>
    active.value
      ? events.value.find((e) => e.tag === "user_interaction.request" && !acknowledged.value.includes(interactionKey(e))) || null
      : null,
  );

  async function guarded(fn: () => Promise<void>) {
    if (busy.value) return;
    busy.value = true;
    error.value = "";
    try { await fn(); } catch (e: any) { error.value = e.message; } finally { busy.value = false; }
  }

  async function refresh() {
    const id = traceId.value;
    if (!id) return;
    const data = await studio.traceSnapshot(id);
    if (id !== traceId.value || disposed) return;
    events.value = data;
  }

  function schedule() {
    clearTimeout(timer);
    if (disposed || !active.value) return;
    timer = setTimeout(async () => {
      try { await refresh(); failures = 0; }
      catch (e: any) { if (++failures >= 3) { error.value = `轮询已停止：${e.message}`; return; } }
      schedule();
    }, 3000);
  }

  async function loadTraces() {
    await guarded(async () => { traceIds.value = await studio.traces(); });
  }
  async function select(id: string) {
    traceId.value = id;
    events.value = [];
    persist({ traceId: id });
    await guarded(refresh);
    failures = 0;
    schedule();
  }
  async function stop() {
    await guarded(async () => { await studio.stopResearch(traceId.value); await refresh(); });
  }
  async function answer(payload: unknown) {
    const current = interaction.value;
    if (!current) return;
    await guarded(async () => {
      await studio.submitInteraction(traceId.value, payload);
      acknowledged.value.push(interactionKey(current));
      persist({ acknowledged: acknowledged.value.slice(-50) });
    });
  }

  onBeforeUnmount(() => { disposed = true; clearTimeout(timer); });
  return { traceId, traceIds, events, rounds, status, active, interaction, error, busy, loadTraces, select, refresh, stop, answer, schedule };
}
