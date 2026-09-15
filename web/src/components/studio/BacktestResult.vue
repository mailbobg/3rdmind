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
        <div v-for="card in cards" :key="card.label"><small>{{ card.label }}</small><strong>{{ card.value }}</strong></div>
      </div>
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
const cards = computed(() => {
  const m = props.result.metrics!;
  return [
    { label: "总收益（扣费）", value: percent(m.total_return) },
    { label: "复利年化", value: percent(m.annualized_return) },
    { label: "夏普", value: typeof m.sharpe === "number" ? m.sharpe.toFixed(2) : "—" },
    { label: "最大回撤", value: percent(m.max_drawdown) },
    { label: "基准收益", value: percent(m.benchmark_return) },
    { label: "交易日数", value: String(m.days ?? "—") },
    { label: "信号 IC", value: typeof m.signal_ic === "number" ? m.signal_ic.toFixed(4) : "—" },
    { label: "信号 Rank IC", value: typeof m.signal_rank_ic === "number" ? m.signal_rank_ic.toFixed(4) : "—" },
  ];
});
const importance = computed(() =>
  Object.entries(props.result.model?.feature_importance || {}).sort((a, b) => b[1] - a[1]) as [string, number][]);
</script>

<style scoped>
.bar { height: 8px; border-radius: 4px; background: var(--green); min-width: 2px; }
</style>
