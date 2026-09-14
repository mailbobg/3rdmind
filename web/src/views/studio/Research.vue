<template>
  <div v-if="error" class="notice" role="alert">{{ error }}<button class="text-button" @click="error = ''">关闭</button></div>

  <section class="surface">
    <div class="section-heading"><h3>启动研究</h3><span>{{ env?.chat_model || "未配置研究模型" }}</span></div>
    <div class="form-grid">
      <label>场景
        <select v-model="form.scenario">
          <option v-for="m in modes" :key="m.value" :value="m.value">{{ m.name }}</option>
        </select>
      </label>
      <label>轮数（1–30）<input v-model.number="form.loops" type="number" min="1" max="30" /></label>
      <label>时限（小时，0.1–24）<input v-model.number="form.duration" type="number" min="0.1" max="24" step="0.1" /></label>
    </div>
    <div class="actions">
      <button class="primary" :disabled="busy" @click="start">开始研究</button>
      <span class="hint">{{ modes.find((m) => m.value === form.scenario)?.desc }}</span>
    </div>
  </section>

  <div class="two-col">
    <section class="surface">
      <div class="section-heading"><h3>实验</h3><button class="text-button" @click="loadTraces">刷新</button></div>
      <p v-if="!traceIds.length" class="hint">还没有实验。</p>
      <ul class="trace-list">
        <li v-for="id in traceIds" :key="id">
          <button :class="{ selected: id === traceId }" @click="select(id)">
            <small>{{ id.split("/")[0] }}</small>{{ id.split("/").slice(1).join("/") }}
          </button>
        </li>
      </ul>
    </section>

    <div>
      <template v-if="traceId">
        <div class="section-heading">
          <h3>{{ traceId }}</h3>
          <span>
            <span class="tag" :class="{ ok: status === '已完成', bad: status === '执行失败' }">{{ status }}</span>
            <button v-if="active" :disabled="busy" @click="stop">停止</button>
            <a :href="stdoutUrl(traceId)" download>下载日志</a>
          </span>
        </div>
        <p v-if="status === '未加载'" class="hint">服务端没有加载这个实验的事件。已结束的实验需要后端以 `load_legacy_pickle_traces` 启动才可回看。</p>
        <InteractionPanel v-if="interaction" :event="interaction" :busy="busy" @submit="answer" />
        <RoundTimeline v-for="round in rounds" :key="round.id" :round="round" :trace-id="traceId" />
      </template>
      <p v-else class="hint">从左侧选择一个实验，或启动新的研究。</p>
    </div>
  </div>
</template>
<script setup lang="ts">
import { onMounted, reactive } from "vue";
import { useRoute } from "vue-router";
import * as studio from "../../api/studio";
import type { Environment } from "../../api/studio";
import { useTrace } from "../../composables/useTrace";
import InteractionPanel from "../../components/studio/InteractionPanel.vue";
import RoundTimeline from "../../components/studio/RoundTimeline.vue";

defineProps<{ env: Environment | null }>();
const { stdoutUrl } = studio;
const modes = [
  { name: "因子研发", desc: "假设 → 因子实现 → Qlib 评估", value: "Finance Data Building" },
  { name: "模型研发", desc: "模型实现与迭代验证", value: "Finance Model Implementation" },
  { name: "因子 × 模型联合", desc: "RD-Agent 原生联合研究循环", value: "Finance Whole Pipeline" },
];
const form = reactive({ scenario: modes[0].value, loops: 3, duration: 2 });
const { traceId, traceIds, rounds, status, active, interaction, error, busy, loadTraces, select, stop, answer } = useTrace();
const route = useRoute();

async function start() {
  if (!Number.isInteger(form.loops) || form.loops < 1 || form.loops > 30 || !(form.duration >= 0.1 && form.duration <= 24)) {
    error.value = "研究轮数应为 1–30，运行时限应为 0.1–24 小时。";
    return;
  }
  const data = new FormData();
  data.append("scenario", form.scenario);
  data.append("loops", String(form.loops));
  data.append("all_duration", String(form.duration));
  try {
    busy.value = true;
    const { id } = await studio.startResearch(data);
    traceIds.value = [id, ...traceIds.value.filter((t) => t !== id)];
    await select(id);
  } catch (e: any) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}

onMounted(async () => {
  await loadTraces();
  const wanted = typeof route.query.trace === "string" ? route.query.trace : traceId.value;
  if (wanted) await select(wanted);
});
</script>
<style scoped>
.two-col { display: grid; grid-template-columns: 260px minmax(0, 1fr); gap: 14px; align-items: start; }
.trace-list { list-style: none; margin: 0; padding: 0; max-height: 60vh; overflow: auto; }
.trace-list button { width: 100%; text-align: left; border: 0; border-radius: 6px; padding: 6px 8px; }
.trace-list button.selected { background: #eef4f1; color: var(--green); }
.trace-list small { display: block; color: var(--muted); font-size: 11px; }
@media (max-width: 900px) { .two-col { grid-template-columns: 1fr; } }
</style>
