<template>
  <div class="table-scroll">
    <table class="corr">
      <thead><tr><th></th><th v-for="n in data.names" :key="n"><code>{{ n }}</code></th></tr></thead>
      <tbody>
        <tr v-for="(row, i) in data.matrix" :key="data.names[i]">
          <th><code>{{ data.names[i] }}</code></th>
          <td v-for="(v, j) in row" :key="j" class="num" :style="cell(v, i === j)">{{ v.toFixed(2) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
  <p class="hint" style="margin: 6px 0 0">{{ data.days }} 个交易日的截面 Spearman 相关系数均值。|ρ| ≥ 0.7 的两个因子基本是同一个信号，同时入选只是重复计权。</p>
</template>
<script setup lang="ts">
import type { CorrelationMatrix } from "../../api/studio";
defineProps<{ data: CorrelationMatrix }>();
function cell(v: number, diagonal: boolean) {
  if (diagonal) return { color: "var(--muted)" };
  const strength = Math.min(1, Math.abs(v));
  return { background: `rgba(${v >= 0 ? "23,103,78" : "178,72,58"}, ${0.08 + strength * 0.4})`, fontWeight: strength >= 0.7 ? 600 : 400 };
}
</script>
<style scoped>
.corr th { font-weight: 500; }
</style>
