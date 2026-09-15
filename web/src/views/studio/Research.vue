<template>
  <main class="workspace">
    <header class="workspace-head">
      <div>
        <div class="eyebrow">QUANTITATIVE RESEARCH / RESEARCH</div>
        <h1>{{ trace.traceId.value ? shortName(trace.traceId.value) : "AI 研究" }}</h1>
      </div>
      <div class="toolbar">
        <label>实验
          <select :value="trace.traceId.value" @change="pick(($event.target as HTMLSelectElement).value)">
            <option value="">选择实验</option>
            <option v-for="id in trace.traceIds.value" :key="id" :value="id">{{ id }}</option>
          </select>
        </label>
        <button @click="showForm = !showForm">{{ showForm ? "收起表单" : "＋ 新建研究" }}</button>
        <button class="results-toggle" :title="layout.resultsOpen.value ? '隐藏右栏' : '显示右栏'" @click="layout.toggleResults()">{{ layout.resultsOpen.value ? "隐藏结果 ▸" : "◂ 显示结果" }}</button>
      </div>
    </header>
    <div class="workspace-body">
      <div v-if="trace.error.value" class="notice" role="alert">{{ trace.error.value }}<button class="text-button" @click="trace.error.value = ''">关闭</button></div>

      <section v-if="showForm" class="surface">
        <div class="section-heading"><h3>启动研究</h3><span>{{ env?.chat_model || "未配置研究模型" }}</span></div>
        <div class="form-grid">
          <label>场景
            <select v-model="form.scenario">
              <option v-for="m in modes" :key="m.value" :value="m.value">{{ m.name }}</option>
            </select>
          </label>
          <label v-if="mode.loops">轮数（1–30）<input v-model.number="form.loops" type="number" min="1" max="30" /></label>
          <label v-if="mode.duration">时限（小时，0.1–24）<input v-model.number="form.duration" type="number" min="0.1" max="24" step="0.1" /></label>
        </div>
        <label v-if="mode.input === 'reports'" style="margin-top: 10px">研报 PDF（可多选）
          <input type="file" accept=".pdf,application/pdf" multiple @change="onFiles" />
          <span class="hint" v-if="files.length">{{ files.map((f) => f.name).join("，") }}</span>
        </label>
        <template v-if="mode.input === 'paper'">
          <label style="margin-top: 10px">论文 PDF
            <input type="file" accept=".pdf,application/pdf" @change="onFiles" />
            <span class="hint" v-if="files.length">{{ files[0].name }}</span>
          </label>
          <label style="margin-top: 6px">或论文链接（未上传文件时使用）
            <input v-model="form.link" placeholder="https://arxiv.org/pdf/…" />
          </label>
        </template>
        <label v-if="mode.objective" style="margin-top: 10px">研究方向（agent 首次确认时预填）
          <textarea v-model="form.objective" rows="2" placeholder="例如：研究沪深300中量价动量因子的增量信息，并评估与现有特征组合后的效果。"></textarea>
        </label>
        <div class="actions">
          <button class="dark" :disabled="trace.busy.value" @click="start">开始研究</button>
          <span class="hint">{{ mode.desc }}</span>
        </div>
      </section>

      <template v-if="trace.traceId.value">
        <div class="section-heading">
          <h3>研究轮次</h3>
          <span>
            <span class="tag" :class="{ ok: status === '已完成', bad: status === '执行失败', live: status === '运行中' }">{{ status }}</span>
            <button v-if="trace.active.value" :disabled="trace.busy.value" @click="trace.stop" style="margin-left: 8px">停止</button>
          </span>
        </div>
        <p v-if="status === '未加载'" class="hint">服务端没有加载这个实验的事件。已结束的实验需要后端以 <code>UI_LOAD_LEGACY_PICKLE_TRACES=true</code> 启动才可回看。</p>
        <RoundCard v-for="round in trace.rounds.value" :key="round.id" :round="round" :selected="round.id === roundId" @select="roundId = round.id; layout.openResults()" />
        <p v-if="status === '运行中' && !trace.rounds.value.length" class="empty">研究已启动，等待第一轮假设…</p>
      </template>
      <p v-else-if="!showForm" class="empty">选择一个实验，或新建研究。</p>
    </div>
  </main>

  <aside class="results">
    <header class="result-head">
      <div>
        <div class="eyebrow">ROUND DETAIL</div>
        <h2>{{ activeRound ? `第 ${Number(activeRound.id) + 1} 轮` : "轮次详情" }}</h2>
      </div>
      <div class="toolbar" v-if="activeRound">
        <button v-if="activeRound.factors.length" class="primary" @click="sendToBacktest(activeRound)">用 {{ activeRound.factors.length }} 个因子回测 →</button>
        <button v-if="hasPrediction(activeRound)" class="primary" @click="sendPrediction(activeRound)">用模型预测回测 →</button>
        <a v-if="trace.traceId.value" class="text-button" :href="stdoutUrl(trace.traceId.value)" download>日志</a>
      </div>
    </header>
    <div class="result-scroll">
      <InteractionPanel v-if="trace.interaction.value" :event="trace.interaction.value" :busy="trace.busy.value" :default-instruction="form.objective" @submit="trace.answer" />
      <RoundDetail v-if="activeRound" :round="activeRound" />
      <p v-else class="empty">在左侧选择一轮查看假设、评估与代码。</p>
    </div>
  </aside>
</template>
<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import * as studio from "../../api/studio";
import { useStudioContext } from "../../composables/studioContext";
import { persistStudioState, restoreStudioState } from "../../composables/studioStorage";
import InteractionPanel from "../../components/studio/InteractionPanel.vue";
import RoundCard from "../../components/studio/RoundCard.vue";
import RoundDetail from "../../components/studio/RoundDetail.vue";
import type { RoundView } from "../../composables/useTrace";

const { env, trace, basket, layout } = useStudioContext();
const { stdoutUrl } = studio;
const route = useRoute();
const router = useRouter();
interface Mode { name: string; desc: string; value: string; loops: boolean; duration: boolean; objective: boolean; input?: "reports" | "paper" }
// The six scenarios the log server's /upload accepts (rdagent/log/server/security.py); Data Science needs an
// MLE-bench competition and dataset outside this UI, so it stays in the native Playground.
const modes: Mode[] = [
  { name: "因子研发", desc: "假设 → 因子实现 → Qlib 评估", value: "Finance Data Building", loops: true, duration: true, objective: true },
  { name: "模型研发", desc: "模型实现与迭代验证", value: "Finance Model Implementation", loops: true, duration: true, objective: true },
  { name: "因子 × 模型联合", desc: "RD-Agent 原生联合研究循环", value: "Finance Whole Pipeline", loops: true, duration: true, objective: true },
  { name: "研报因子提取", desc: "上传研报 PDF → 提取因子 → 实现与 Qlib 评估", value: "Finance Data Building (Reports)", loops: false, duration: true, objective: false, input: "reports" },
  { name: "论文模型实现", desc: "上传论文 PDF 或给链接 → 提取模型结构 → 实现", value: "General Model Implementation", loops: false, duration: false, objective: false, input: "paper" },
];
const saved = restoreStudioState();
const form = reactive({ scenario: modes[0].value, loops: 3, duration: 2, objective: saved.objective || "", link: "" });
const files = ref<File[]>([]);
const mode = computed(() => modes.find((m) => m.value === form.scenario) || modes[0]);
watch(() => form.scenario, () => { files.value = []; });
function onFiles(event: Event) {
  files.value = [...((event.target as HTMLInputElement).files || [])];
}
const showForm = ref(!!route.query.new || !trace.traceId.value);
watch(() => route.query.new, (value) => { if (value) showForm.value = true; });
const roundId = ref("");
const shortName = (id: string) => id.split("/").slice(1).join("/") || id;
const status = computed(() => trace.status.value);
const activeRound = computed(() => {
  const rounds = trace.rounds.value;
  return rounds.find((r) => r.id === roundId.value) || rounds[rounds.length - 1] || null;
});
watch(() => form.objective, (objective) => persistStudioState({ objective }));
watch(() => trace.interaction.value, (request) => { if (request) layout.openResults(); });

async function pick(id: string) {
  roundId.value = "";
  if (id) await trace.select(id);
  else trace.traceId.value = "";
}
async function start() {
  if (mode.value.loops && (!Number.isInteger(form.loops) || form.loops < 1 || form.loops > 30)) {
    trace.error.value = "研究轮数应为 1–30。";
    return;
  }
  if (mode.value.duration && !(form.duration >= 0.1 && form.duration <= 24)) {
    trace.error.value = "运行时限应为 0.1–24 小时。";
    return;
  }
  if (mode.value.input === "reports" && !files.value.length) {
    trace.error.value = "请至少上传一份研报 PDF。";
    return;
  }
  if (mode.value.input === "paper" && !files.value.length && !/^https?:\/\//.test(form.link.trim())) {
    trace.error.value = "请上传论文 PDF，或填写以 http(s) 开头的链接。";
    return;
  }
  const data = new FormData();
  data.append("scenario", form.scenario);
  if (mode.value.loops) data.append("loops", String(form.loops));
  if (mode.value.duration) data.append("all_duration", String(form.duration));
  for (const file of files.value) data.append("files", file, file.name);
  // The server reads the paper link from the "files" form field when no file is attached.
  if (mode.value.input === "paper" && !files.value.length) data.append("files", form.link.trim());
  try {
    trace.busy.value = true;
    const { id } = await studio.startResearch(data);
    trace.traceIds.value = [id, ...trace.traceIds.value.filter((t) => t !== id)];
    showForm.value = false;
    await trace.select(id);
  } catch (e) {
    trace.error.value = e instanceof Error ? e.message : String(e);
  } finally {
    trace.busy.value = false;
  }
}
function sendToBacktest(round: RoundView) {
  basket.addRound(trace.traceId.value, Number(round.id), round.factors);
  router.push({ name: "studio-backtest" });
}
function sendPrediction(round: RoundView) {
  basket.addPrediction(trace.traceId.value, Number(round.id));
  router.push({ name: "studio-backtest" });
}

// Which rounds recorded a Qlib model prediction lives on disk, so it comes from /studio/rounds rather than the event stream.
const predictionLoops = ref<Set<number>>(new Set());
const hasPrediction = (round: RoundView) => predictionLoops.value.has(Number(round.id));
async function loadPredictionLoops(id: string) {
  predictionLoops.value = new Set();
  if (!id) return;
  try {
    const rounds = await studio.rounds(id);
    if (id === trace.traceId.value) predictionLoops.value = new Set(rounds.filter((r) => r.prediction).map((r) => r.loop_id));
  } catch { /* the trace may not be loaded on the server; the round view already says so */ }
}
watch(() => [trace.traceId.value, trace.rounds.value.length] as const, ([id]) => loadPredictionLoops(id), { immediate: true });

onMounted(async () => {
  const wanted = typeof route.query.trace === "string" ? route.query.trace : trace.traceId.value;
  if (wanted && (wanted !== trace.traceId.value || !trace.events.value.length)) await trace.select(wanted);
});
</script>
