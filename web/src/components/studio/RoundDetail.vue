<template>
  <div>
    <section class="surface" v-if="round.hypothesis.hypothesis || round.hypothesis.reason">
      <div class="section-heading"><h3>研究假设</h3><span>第 {{ Number(round.id) + 1 }} 轮</span></div>
      <p style="margin: 0 0 6px">{{ round.hypothesis.hypothesis }}</p>
      <p class="hint" v-if="round.hypothesis.reason">{{ round.hypothesis.reason }}</p>
      <p class="hint" v-if="round.hypothesis.concise_knowledge">经验：{{ round.hypothesis.concise_knowledge }}</p>
    </section>
    <section class="surface" v-if="round.metrics">
      <div class="section-heading"><h3>原生 Qlib 评估</h3><span>LightGBM · TopkDropout</span></div>
      <MetricTable :metrics="round.metrics" />
    </section>
    <section class="surface" v-if="round.chartHtml">
      <div class="section-heading"><h3>收益图</h3></div>
      <iframe :srcdoc="round.chartHtml" sandbox="allow-scripts" style="width: 100%; height: 420px; border: 0"></iframe>
    </section>
    <section class="surface" v-if="round.feedback">
      <div class="section-heading">
        <h3>Agent 反馈</h3>
        <span class="tag" :class="round.feedback.decision ? 'ok' : 'bad'">{{ round.feedback.decision ? "接受" : "拒绝" }}</span>
      </div>
      <p v-if="round.feedback.observations">{{ round.feedback.observations }}</p>
      <p v-if="round.feedback.hypothesis_evaluation">{{ round.feedback.hypothesis_evaluation }}</p>
      <p v-if="round.feedback.reason">{{ round.feedback.reason }}</p>
      <p v-if="round.feedback.new_hypothesis" class="hint">下一步：{{ round.feedback.new_hypothesis }}</p>
    </section>
    <section class="surface" v-if="round.files.length">
      <div class="section-heading">
        <h3>生成代码</h3>
        <button class="text-button" @click="downloadCurrent">下载代码</button>
      </div>
      <CodeViewer ref="viewer" :files="round.files" />
    </section>
    <p v-if="!round.metrics && !round.files.length && !round.feedback" class="empty">这一轮还没有产出。</p>
  </div>
</template>
<script setup lang="ts">
import { ref } from "vue";
import CodeViewer from "./CodeViewer.vue";
import MetricTable from "./MetricTable.vue";
import { download } from "../../composables/studioContext";
import type { RoundView } from "../../composables/useTrace";
const props = defineProps<{ round: RoundView }>();
const viewer = ref<InstanceType<typeof CodeViewer> | null>(null);
function downloadCurrent() {
  const file = viewer.value?.current || props.round.files[0];
  if (file) download(`${file.task || "round"}-${file.name}`, file.code);
}
</script>
