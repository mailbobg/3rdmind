<template>
  <section class="surface selectable" :class="{ selected }" @click="$emit('select')">
    <div class="section-heading">
      <h3>第 {{ Number(round.id) + 1 }} 轮 · {{ round.hypothesis.hypothesis || "（无假设文本）" }}</h3>
      <span class="tag" :class="{ ok: round.status === '接受', bad: round.status === '拒绝' }">{{ round.status }}</span>
    </div>
    <p v-if="round.hypothesis.reason" class="hint clamp">{{ round.hypothesis.reason }}</p>
    <div class="chips" v-if="round.tasks.length">
      <span class="chip" v-for="t in round.tasks" :key="t.name">{{ t.name }}</span>
    </div>
    <div class="foot">
      <div class="stages">
        <span v-for="s in stages" :key="s.name" :class="{ done: s.done }">{{ s.name }}</span>
      </div>
      <div class="actions" style="margin: 0" v-if="round.factors.length || hasPrediction">
        <button v-if="round.factors.length" class="primary" @click.stop="$emit('backtest')">用 {{ round.factors.length }} 个因子回测 →</button>
        <button v-if="hasPrediction" @click.stop="$emit('backtest-prediction')">用模型预测回测 →</button>
      </div>
    </div>
  </section>
</template>
<script setup lang="ts">
import { computed } from "vue";
import type { RoundView } from "../../composables/useTrace";
const props = defineProps<{ round: RoundView; selected: boolean; hasPrediction?: boolean }>();
defineEmits<{ select: []; backtest: []; "backtest-prediction": [] }>();
const stages = computed(() => [
  { name: "假设", done: !!props.round.hypothesis.hypothesis },
  { name: "代码", done: props.round.files.length > 0 },
  { name: "评估", done: !!props.round.metrics },
  { name: "反馈", done: !!props.round.feedback },
]);
</script>
<style scoped>
.clamp { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.foot { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 10px; }
.stages { display: flex; gap: 14px; font-size: 11px; color: var(--muted); }
.stages span::before { content: "○ "; }
.stages span.done { color: var(--green); }
.stages span.done::before { content: "● "; }
</style>
