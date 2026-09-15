import { getCurrentInstance, onBeforeUnmount, ref } from "vue";
import * as studio from "../api/studio";
import type { BacktestRequest, BacktestResult, BacktestSummary } from "../api/studio";

export function validateRequest(c: BacktestRequest): string | null {
  if (!c.factors.length || c.factors.length > 20) return "请选择 1–20 个因子。";
  if (!c.factors.every((f) => f.trace && Number.isInteger(f.loop_id))) return "每个因子都要来自某个实验轮次。";
  if (!c.factors.every((f) => Number.isFinite(f.weight))) return "因子权重必须是数字。";
  if (c.factors.reduce((s, f) => s + Math.abs(f.weight), 0) === 0) return "至少一个因子的权重不为 0。";
  if (!c.start || !c.end || c.start >= c.end) return "开始日期必须早于结束日期。";
  if (c.model?.method === "lgbm") {
    const [ts, te] = c.model.train, [vs, ve] = c.model.valid;
    if (!ts || !te || !vs || !ve) return "请填写训练和验证区间。";
    if (ts >= te || vs >= ve) return "训练、验证区间的开始必须早于结束。";
    if (te >= vs) return "验证区间必须在训练区间之后。";
    if (ve >= c.start) return "回测必须在验证区间之后开始。";
  }
  if (!["csi300", "csi500", "all"].includes(c.market)) return "不支持的股票池。";
  if (!c.benchmark || !c.benchmark.trim()) return "请填写基准指数代码。";
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
    try { await fn(); } catch (e) { error.value = e instanceof Error ? e.message : String(e); } finally { busy.value = false; }
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
      // Deliberately a 1-strike policy (stop on the first poll error), unlike useTrace's
      // 3-strike tolerance: a single backtest job failing to poll is not worth retrying blind.
      try { await fetchSelected(); if (!isActive(result.value?.status)) jobs.value = await studio.backtests(); }
      catch (e) { error.value = e instanceof Error ? e.message : String(e); return; }
      schedule();
    }, 3000);
  }
  async function select(id: string) {
    selectedId.value = id;
    result.value = null;
    await guarded(fetchSelected);
    schedule();
  }
  /** Submit a backtest; resolves to true when the server accepted it, false on validation or request failure. */
  async function run(config: BacktestRequest): Promise<boolean> {
    const message = validateRequest(config);
    if (message) { error.value = message; return false; }
    let accepted = false;
    await guarded(async () => {
      const { id } = await studio.runBacktest(config);
      jobs.value = await studio.backtests();
      selectedId.value = id;
      result.value = { id, status: "queued", config };
      accepted = true;
      schedule();
    });
    return accepted;
  }

  function dispose() { disposed = true; clearTimeout(timer); }
  if (getCurrentInstance()) onBeforeUnmount(dispose);
  return { jobs, selectedId, result, error, busy, load, select, run, dispose };
}
