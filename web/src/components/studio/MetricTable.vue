<template>
  <div class="table-scroll">
    <table>
      <thead><tr><th>指标</th><th class="num">值</th></tr></thead>
      <tbody>
        <tr v-for="[key, value] in rows" :key="key"><td class="metric-key">{{ key }}</td><td class="num">{{ format(value) }}</td></tr>
      </tbody>
    </table>
  </div>
</template>
<script setup lang="ts">
import { computed } from "vue";
const props = defineProps<{ metrics: Record<string, number> }>();
const preferred = ["IC", "ICIR", "Rank IC", "Rank ICIR",
  "1day.excess_return_with_cost.annualized_return", "1day.excess_return_with_cost.information_ratio",
  "1day.excess_return_with_cost.max_drawdown"];
const rows = computed(() => {
  const entries = Object.entries(props.metrics);
  const head = preferred.filter((k) => k in props.metrics).map((k) => [k, props.metrics[k]] as [string, number]);
  const rest = entries.filter(([k]) => !preferred.includes(k));
  return [...head, ...rest];
});
const format = (v: number) => (Number.isFinite(v) ? Number(v.toPrecision(5)).toString() : "—");
</script>
<style scoped>
.metric-key { word-break: break-all; font-family: ui-monospace, Menlo, monospace; font-size: 11px; }
.num { white-space: nowrap; }
</style>
