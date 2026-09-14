import { getCurrentInstance, onBeforeUnmount, ref } from "vue";
import * as studio from "../api/studio";
import type { BacktestRequest, BacktestResult, BacktestSummary } from "../api/studio";

export function validateRequest(c: BacktestRequest): string | null {
  if (!c.trace || c.loop_id === undefined || c.loop_id === null) return "请先选择实验和轮次。";
  if (!c.factors.length || c.factors.length > 20) return "请选择 1–20 个因子。";
  if (!c.factors.every((f) => Number.isFinite(f.weight))) return "因子权重必须是数字。";
  if (c.factors.reduce((s, f) => s + Math.abs(f.weight), 0) === 0) return "至少一个因子的权重不为 0。";
  if (!c.start || !c.end || c.start >= c.end) return "开始日期必须早于结束日期。";
  if (!["csi300", "csi500", "all"].includes(c.market)) return "不支持的股票池。";
  if (!Number.isInteger(c.topk) || c.topk < 1 || c.topk > 500) return "topk 应为 1–500 的整数。";
  if (!Number.isInteger(c.n_drop) || c.n_drop < 0 || c.n_drop > c.topk) return "n_drop 应为 0–topk 的整数。";
  if (!(c.account >= 1000 && c.account <= 1e10)) return "初始资金应在 1,000 到 100 亿之间。";
  for (const cost of [c.open_cost, c.close_cost]) if (!(cost >= 0 && cost <= 0.1)) return "费率应在 0 到 0.1 之间。";
  return null;
}

const isActive = (status?: string) => status === "queued" || status === "running";

export function useBacktests() {
  const jobs = ref<BacktestSummary[]>([]);
  const selectedId = ref("");
  const result = ref<BacktestResult | null>(null);
  const error = ref("");
  const busy = ref(false);
  let timer: ReturnType<typeof setTimeout> | undefined;
  let disposed = false;

  // busy is purely a UI indicator for "a user action is in flight" — it never gates
  // concurrent calls.
  async function guarded(fn: () => Promise<void>) {
    busy.value = true;
    error.value = "";
    try { await fn(); } catch (e: any) { error.value = e.message; } finally { busy.value = false; }
  }
  async function load() { await guarded(async () => { jobs.value = await studio.backtests(); }); }
  async function fetchSelected() {
    const id = selectedId.value;
    if (!id) return;
    const data = await studio.backtest(id);
    if (id === selectedId.value && !disposed) result.value = data;
  }

  // Background polling deliberately does not touch `busy`: it is not a user action,
  // and buttons must stay enabled/clickable while polling runs in the background.
  function schedule() {
    clearTimeout(timer);
    if (disposed || !isActive(result.value?.status)) return;
    timer = setTimeout(async () => {
      try { await fetchSelected(); if (!isActive(result.value?.status)) jobs.value = await studio.backtests(); }
      catch (e: any) { error.value = e.message; return; }
      schedule();
    }, 3000);
  }
  async function select(id: string) {
    selectedId.value = id;
    result.value = null;
    await guarded(fetchSelected);
    schedule();
  }
  async function run(config: BacktestRequest) {
    const message = validateRequest(config);
    if (message) { error.value = message; return; }
    await guarded(async () => {
      const { id } = await studio.runBacktest(config);
      jobs.value = await studio.backtests();
      selectedId.value = id;
      result.value = { id, status: "queued", config };
    });
    schedule();
  }

  function dispose() { disposed = true; clearTimeout(timer); }
  if (getCurrentInstance()) onBeforeUnmount(dispose);
  return { jobs, selectedId, result, error, busy, load, select, run, dispose };
}
