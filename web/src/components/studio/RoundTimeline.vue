<template>
  <section class="surface">
    <div class="section-heading">
      <h3>第 {{ Number(round.id) + 1 }} 轮 · {{ round.hypothesis.hypothesis || "（无假设文本）" }}</h3>
      <span class="tag" :class="{ ok: round.status === '接受', bad: round.status === '拒绝' }">{{ round.status }}</span>
    </div>
    <p v-if="round.hypothesis.reason" class="hint">{{ round.hypothesis.reason }}</p>
    <div v-if="round.tasks.length" class="actions">
      <span class="tag" v-for="t in round.tasks" :key="t.name">{{ t.name }}</span>
    </div>
    <details v-if="round.files.length"><summary>生成代码（{{ round.files.length }} 个文件）</summary><CodeViewer :files="round.files" /></details>
    <details v-if="round.metrics" open><summary>原生 Qlib 评估</summary><MetricTable :metrics="round.metrics" /></details>
    <details v-if="round.chartHtml"><summary>收益图</summary>
      <iframe :srcdoc="round.chartHtml" sandbox="allow-scripts" style="width: 100%; height: 460px; border: 0"></iframe>
    </details>
    <div v-if="round.feedback" class="surface" style="margin: 8px 0 0">
      <strong>反馈：{{ round.feedback.decision ? "接受" : "拒绝" }}</strong>
      <p v-if="round.feedback.observations">{{ round.feedback.observations }}</p>
      <p v-if="round.feedback.hypothesis_evaluation">{{ round.feedback.hypothesis_evaluation }}</p>
      <p v-if="round.feedback.reason">{{ round.feedback.reason }}</p>
      <p v-if="round.feedback.new_hypothesis" class="hint">下一步：{{ round.feedback.new_hypothesis }}</p>
    </div>
    <div class="actions" v-if="round.factors.length">
      <router-link class="primary" custom v-slot="{ navigate }" :to="{ name: 'studio-strategy', query: { trace: traceId, loop: round.id } }">
        <button class="primary" @click="navigate">用这一轮的 {{ round.factors.length }} 个因子回测 →</button>
      </router-link>
    </div>
  </section>
</template>
<script setup lang="ts">
import CodeViewer from "./CodeViewer.vue";
import MetricTable from "./MetricTable.vue";
import type { RoundView } from "../../composables/useTrace";
defineProps<{ round: RoundView; traceId: string }>();
</script>
