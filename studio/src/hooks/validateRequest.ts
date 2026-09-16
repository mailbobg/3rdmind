import type { BacktestRequest } from "../api/studio";

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
