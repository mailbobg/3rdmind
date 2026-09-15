<!-- web/src/components/studio/BacktestResult.vue -->
<template>
  <section class="surface">
    <div class="section-heading">
      <h3>回测 {{ result.id.slice(0, 8) }}</h3>
      <span class="tag" :class="{ ok: result.status === 'completed', bad: result.status === 'failed' }">{{ statusLabel }}</span>
    </div>
    <div class="chips" style="margin-bottom: 8px">
      <template v-if="legacy"><span class="tag">旧格式回测 · {{ result.config.factors.length }} 个因子</span></template>
      <span v-else class="chip" v-for="f in result.config.factors" :key="`${f.trace}#${f.loop_id}#${f.name}`" :title="`${f.trace ?? result.config.trace} · 第 ${Number(f.loop_id ?? result.config.loop_id) + 1} 轮`">
        <template v-if="f.kind === 'prediction'">模型 · </template>{{ f.name }}<template v-if="f.weight !== 1"> ×{{ f.weight }}</template>
      </span>
    </div>
    <p class="hint">
      {{ result.config.start }} → {{ result.config.end }} · {{ result.config.market }} · 基准 {{ result.config.benchmark || "SH000300" }} · topk {{ result.config.topk }} / n_drop {{ result.config.n_drop }}
      · {{ result.config.model?.method === "lgbm" ? `LightGBM（训练 ${result.config.model.train.join("→")}，验证 ${result.config.model.valid.join("→")}）` : "排名加权" }}
    </p>
    <div v-if="result.error" class="notice">{{ result.error }}</div>
    <template v-if="result.metrics">
      <div class="cards">
        <div v-for="card in cards" :key="card.label" :title="card.hint"><small>{{ card.label }}</small><strong :class="card.tone">{{ card.value }}</strong></div>
      </div>
      <p class="verdict" v-for="line in verdict" :key="line">{{ line }}</p>
      <EquityChart :rows="result.rows || []" />
      <p class="hint">{{ result.method }}</p>
    </template>
  </section>
  <section class="surface" v-if="result.model">
    <div class="section-heading"><h3>LightGBM 训练</h3><span>{{ result.model.train_rows.toLocaleString() }} 训练样本 · {{ result.model.valid_rows.toLocaleString() }} 验证样本</span></div>
    <div class="cards">
      <div><small>最佳迭代</small><strong>{{ result.model.best_iteration }}</strong></div>
      <div><small>验证 L2</small><strong>{{ result.model.valid_l2.toFixed(4) }}</strong></div>
    </div>
    <div class="table-scroll">
      <table>
        <thead><tr><th>信号</th><th class="num">重要性（gain）</th><th style="width: 40%"></th></tr></thead>
        <tbody>
          <tr v-for="[name, gain] in importance" :key="name">
            <td><code>{{ name }}</code></td>
            <td class="num">{{ gain.toFixed(1) }}</td>
            <td><div class="bar" :style="{ width: (gain / importance[0][1]) * 100 + '%' }"></div></td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
  <TradeTables v-if="result.metrics" :trades="result.trades || []" :instruments="result.instruments || []" :holdings="result.holdings" />
  <section class="surface" v-if="result.log">
    <details><summary>执行日志</summary><pre>{{ result.log }}</pre></details>
  </section>
</template>
<script setup lang="ts">
import { computed } from "vue";
import EquityChart from "./EquityChart.vue";
import TradeTables from "./TradeTables.vue";
import type { BacktestResult } from "../../api/studio";
import { backtestStatusLabel } from "./backtestStatus";
const props = defineProps<{ result: BacktestResult }>();
const statusLabel = computed(() => backtestStatusLabel(props.result.status));
// Jobs written before factors carried their round have no loop_id anywhere in the config.
const legacy = computed(() => (props.result.config.loop_id === undefined || props.result.config.loop_id === null)
  && !props.result.config.factors.some((f) => f.loop_id !== undefined && f.loop_id !== null));
const percent = (v?: number | null) => (typeof v === "number" && Number.isFinite(v) ? (v * 100).toFixed(2) + "%" : "—");
const tone = (v?: number | null) => (typeof v !== "number" ? "" : v >= 0 ? "pos" : "neg");
const cards = computed(() => {
  const m = props.result.metrics!;
  const excess = m.total_return - m.benchmark_return;
  return [
    { label: "总收益（扣费）", value: percent(m.total_return), tone: tone(m.total_return), hint: "回测区间内的净值变化，已扣手续费" },
    { label: "超额收益", value: percent(excess), tone: tone(excess), hint: "总收益减去基准指数同期收益；负数意味着不如直接买指数" },
    { label: "基准收益", value: percent(m.benchmark_return), tone: "", hint: "基准指数同期收益" },
    { label: "复利年化", value: percent(m.annualized_return), tone: tone(m.annualized_return), hint: "按 252 个交易日折算的年化收益" },
    { label: "夏普", value: typeof m.sharpe === "number" ? m.sharpe.toFixed(2) : "—", tone: "", hint: "日收益均值 ÷ 波动 × √252；1 以上算不错，0.5 以下基本靠运气" },
    { label: "最大回撤", value: percent(m.max_drawdown), tone: "neg", hint: "净值从高点回落的最大幅度" },
    { label: "信号 IC", value: typeof m.signal_ic === "number" ? m.signal_ic.toFixed(4) : "—", tone: tone(m.signal_ic), hint: "最终评分与次日收益的日均相关系数；|IC| < 0.01 接近噪声" },
    { label: "信号 Rank IC", value: typeof m.signal_rank_ic === "number" ? m.signal_rank_ic.toFixed(4) : "—", tone: tone(m.signal_rank_ic), hint: "评分排名与次日收益排名的日均相关系数" },
    { label: "交易日数", value: String(m.days ?? "—"), tone: "", hint: "样本太短（< 120 天）时以上指标都不可靠" },
  ];
});
// A few plain-language rules so the numbers get read the same way every time.
const verdict = computed(() => {
  const m = props.result.metrics!;
  const lines: string[] = [];
  const excess = m.total_return - m.benchmark_return;
  lines.push(excess >= 0 ? `跑赢基准 ${percent(excess)}。` : `跑输基准 ${percent(-excess)}：这段时间不如直接持有指数。`);
  if (typeof m.signal_ic === "number" && Math.abs(m.signal_ic) < 0.01 && typeof m.signal_rank_ic === "number" && Math.abs(m.signal_rank_ic) < 0.01)
    lines.push("评分对次日收益几乎没有预测力（|IC| < 0.01），收益主要来自运气或市场本身，回到因子库换信号比调参数更有用。");
  else if (typeof m.signal_ic === "number" && m.signal_ic < -0.01)
    lines.push("评分与次日收益负相关：信号方向反了，排名加权模式下把权重改成负数再试。");
  if (typeof m.sharpe === "number" && m.sharpe < 0.5 && excess >= 0) lines.push("夏普低于 0.5，收益波动大，不宜据此下结论。");
  if (props.result.model && props.result.model.best_iteration <= 20)
    lines.push(`LightGBM 在第 ${props.result.model.best_iteration} 轮就早停：训练集里学不到多少东西，信号本身偏弱。`);
  if ((m.days ?? 0) < 120) lines.push("交易日不足 120 天，样本太短。");
  return lines;
});
const importance = computed(() =>
  Object.entries(props.result.model?.feature_importance || {}).sort((a, b) => b[1] - a[1]) as [string, number][]);
</script>

<style scoped>
.bar { height: 8px; border-radius: 4px; background: var(--green); min-width: 2px; }
.verdict { margin: 4px 0; padding: 6px 10px; background: var(--soft); border-left: 3px solid var(--green); border-radius: 4px; font-size: 12px; }
.pos { color: var(--green); }
.neg { color: var(--danger); }
</style>
