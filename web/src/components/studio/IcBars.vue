<template>
  <div class="ic-bars" role="img" :aria-label="`按月 ${label}`">
    <div v-for="m in months" :key="m.month" class="col" :title="`${m.month}：${m.value == null ? '—' : m.value.toFixed(4)}`">
      <div class="bar" :class="(m.value ?? 0) >= 0 ? 'pos' : 'neg'" :style="barStyle(m.value)"></div>
    </div>
  </div>
  <div class="axis"><span>{{ months[0]?.month }}</span><span>{{ months[months.length - 1]?.month }}</span></div>
</template>
<script setup lang="ts">
import { computed } from "vue";
const props = defineProps<{ monthly: { month: string; ic: number | null; rank_ic: number | null }[]; field: "ic" | "rank_ic"; label: string }>();
const months = computed(() => props.monthly.map((m) => ({ month: m.month, value: m[props.field] })));
const scale = computed(() => Math.max(0.02, ...months.value.map((m) => Math.abs(m.value ?? 0))));
function barStyle(value: number | null) {
  const h = value == null ? 0 : (Math.abs(value) / scale.value) * 50;
  return value == null || value >= 0 ? { height: h + "%", bottom: "50%" } : { height: h + "%", top: "50%" };
}
</script>
<style scoped>
.ic-bars { display: flex; gap: 2px; height: 90px; align-items: stretch; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); background: linear-gradient(to bottom, transparent 50%, var(--line) 50%, var(--line) calc(50% + 1px), transparent calc(50% + 1px)); }
.col { flex: 1; position: relative; min-width: 3px; }
.bar { position: absolute; left: 0; right: 0; border-radius: 1px; }
.bar.pos { background: var(--green); }
.bar.neg { background: var(--danger); }
.axis { display: flex; justify-content: space-between; font-size: 10px; color: var(--muted); margin-top: 2px; }
</style>
