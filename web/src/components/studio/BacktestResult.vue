<!-- web/src/components/studio/BacktestResult.vue -->
<template>
  <section class="surface">
    <div class="section-heading">
      <h3>回测 {{ result.id.slice(0, 8) }}</h3>
      <span class="tag" :class="{ ok: result.status === 'completed', bad: result.status === 'failed' }">{{ statusLabel }}</span>
    </div>
    <p class="hint">
      来自 {{ result.config.trace }} · 第 {{ Number(result.config.loop_id) + 1 }} 轮 ·
      {{ result.config.factors.map((f) => `${f.name}×${f.weight}`).join("，") }} ·
      {{ result.config.start }} → {{ result.config.end }} · {{ result.config.market }} · topk {{ result.config.topk }} / n_drop {{ result.config.n_drop }}
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
<style scoped>
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 10px; margin: 10px 0; }
.cards div { border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px; }
.cards small { display: block; color: var(--muted); font-size: 11px; }
.cards strong { font-size: 16px; }
</style>
