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
        {{ f.name }}<template v-if="f.weight !== 1"> ×{{ f.weight }}</template>
      </span>
    </div>
    <p class="hint">
      {{ result.config.start }} → {{ result.config.end }} · {{ result.config.market }} · 基准 {{ result.config.benchmark || "SH000300" }} · topk {{ result.config.topk }} / n_drop {{ result.config.n_drop }}
    </p>
    <div v-if="result.error" class="notice">{{ result.error }}</div>
    <template v-if="result.metrics">
      <div class="cards">
        <div v-for="card in cards" :key="card.label"><small>{{ card.label }}</small><strong>{{ card.value }}</strong></div>
      </div>
      <EquityChart :rows="result.rows || []" />
      <p class="hint">{{ result.method }}</p>
    </template>
    <details v-if="result.log"><summary>执行日志</summary><pre>{{ result.log }}</pre></details>
  </section>
</template>
<script setup lang="ts">
import { computed } from "vue";
import EquityChart from "./EquityChart.vue";
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
  ];
});
</script>

