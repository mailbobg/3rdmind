<template>
  <ObjectBar :title="trace.traceId.value ? shortName(trace.traceId.value) : 'AI 研究'" :description="objectDesc" :tag="objectTag">
    <span v-if="trace.traceId.value" class="tag" :class="{ ok: status === '已完成', bad: status === '执行失败', live: status === '运行中' }">{{ status }}</span>
  </ObjectBar>

  <main class="workspace">
    <div class="col-head">
      <div class="seg">
        <button :class="{ on: tab === 'rounds' }" @click="tab = 'rounds'">◎ 研究轮次</button>
        <button :class="{ on: tab === 'new' }" @click="tab = 'new'">＋ 新建研究</button>
      </div>
      <div class="col-actions">
        <select :value="trace.traceId.value" style="max-width: 280px" @change="pick(($event.target as HTMLSelectElement).value)">
          <option value="">选择实验</option>
          <option v-for="id in trace.traceIds.value" :key="id" :value="id">{{ id }}</option>
        </select>
        <button v-if="trace.active.value" :disabled="trace.busy.value" @click="trace.stop">■ 停止</button>
        <a v-if="trace.traceId.value" class="text-button" :href="stdoutUrl(trace.traceId.value)" download>日志</a>
        <ResultsToggle />
      </div>
    </div>
    <div class="col-body">
      <div v-if="trace.error.value" class="notice" role="alert">{{ trace.error.value }}<button class="text-button" @click="trace.error.value = ''">关闭</button></div>

      <template v-if="tab === 'new'">
        <div class="param-bar">
          <span class="p">场景 <select v-model="form.scenario"><option v-for="m in modes" :key="m.value" :value="m.value">{{ m.name }}</option></select> <i class="info" :title="mode.desc">i</i></span>
          <span class="p" v-if="mode.loops">轮数 <input type="number" v-model.number="form.loops" min="1" max="30" /> <i class="info" title="1–30">i</i></span>
          <span class="p" v-if="mode.duration">时限（小时） <input type="number" v-model.number="form.duration" min="0.1" max="24" step="0.1" /> <i class="info" title="0.1–24">i</i></span>
          <span class="p" v-if="mode.input === 'reports'">研报 PDF <input type="file" accept=".pdf,application/pdf" multiple @change="onFiles" /></span>
          <span class="p" v-if="mode.input === 'paper'">论文 PDF <input type="file" accept=".pdf,application/pdf" @change="onFiles" /></span>
          <span class="p" v-if="mode.input === 'paper'">或链接 <input v-model="form.link" placeholder="https://arxiv.org/pdf/…" style="width: 220px" /></span>
        </div>
        <section class="panel grow">
          <div class="panel-head"><h3>{{ mode.name }}</h3><span class="status">{{ env?.chat_model || "未配置研究模型" }}</span></div>
          <div class="panel-body">
            <p class="hint" style="margin: 0 0 8px">{{ mode.desc }}</p>
            <label v-if="mode.objective">研究方向（可选）
              <textarea v-model="form.objective" rows="5" placeholder="留空则由 agent 自行选题。填了会作为总体指示进入每一轮的假设生成，例如：研究沪深300中量价动量因子的增量信息。"></textarea>
            </label>
            <p v-if="mode.objective" class="hint" style="margin: 8px 0 0">假设由 agent 自己提出并按前几轮的成败迭代。运行中它会在三个节点停下来让你确认（开始前的方向与基础特征、每轮的假设、每轮的反馈），面板里不改直接提交就按它的原案继续；不提交它会一直等。</p>
            <p v-if="files.length" class="hint" style="margin: 8px 0 0">已选文件：{{ files.map((f) => f.name).join("，") }}</p>
          </div>
          <div class="panel-foot"><button class="dark" :disabled="trace.busy.value" @click="start">▶ 开始研究</button></div>
        </section>
      </template>

      <template v-else>
        <section class="panel grow">
          <div class="panel-head">
            <h3>研究轮次 <span class="hint">{{ trace.rounds.value.length }} 轮</span></h3>
            <span class="status" v-if="trace.traceId.value">{{ status }}</span>
          </div>
          <div class="panel-body">
            <p v-if="!trace.traceId.value" class="empty">从右上角选择一个实验，或新建研究。</p>
            <p v-else-if="status === '启动中'" class="empty">agent 正在初始化，第一条事件到达前这里是空的，通常几十秒。</p>
            <p v-else-if="status === '未加载'" class="hint">服务端没有加载这个实验的事件。已结束的实验需要后端以 <code>UI_LOAD_LEGACY_PICKLE_TRACES=true</code> 启动才可回看。</p>
            <p v-else-if="status === '已结束' && !trace.rounds.value.length" class="hint">这个实验的进程已结束，且没有留下任何事件；看日志里的报错。</p>
            <p v-else-if="status === '运行中' && !trace.rounds.value.length" class="empty">研究已启动，等待第一轮假设…</p>
            <div class="rounds">
              <RoundCard v-for="round in trace.rounds.value" :key="round.id" :round="round" :selected="round.id === roundId" :has-prediction="hasPrediction(round)"
                @select="roundId = round.id; layout.openResults()" @backtest="sendToBacktest(round)" @backtest-prediction="sendPrediction(round)" />
            </div>
          </div>
        </section>
      </template>
    </div>
  </main>

  <aside class="results">
    <div class="col-head">
      <div class="seg"><button class="on">{{ activeRound ? `第 ${Number(activeRound.id) + 1} 轮` : "轮次详情" }}</button></div>
      <div class="col-actions" v-if="activeRound">
        <button v-if="activeRound.factors.length" class="primary small" @click="sendToBacktest(activeRound)">用 {{ activeRound.factors.length }} 个因子回测 →</button>
        <button v-if="hasPrediction(activeRound)" class="small" @click="sendPrediction(activeRound)">用模型预测回测 →</button>
      </div>
    </div>
    <div class="col-body">
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
import ObjectBar from "../../components/studio/ObjectBar.vue";
import ResultsToggle from "../../components/studio/ResultsToggle.vue";
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
const tab = ref<"rounds" | "new">(route.query.new || !trace.traceId.value ? "new" : "rounds");
watch(() => route.query.new, (value) => { if (value) tab.value = "new"; });
const objectDesc = computed(() => {
  if (!trace.traceId.value) return "启动 RD-Agent 研究，查看假设、代码与评估";
  const last = trace.rounds.value[trace.rounds.value.length - 1];
  return last?.hypothesis?.hypothesis || trace.traceId.value;
});
const objectTag = computed(() => trace.traceId.value ? (modes.find((m) => trace.traceId.value.startsWith(m.value + "/"))?.name || trace.traceId.value.split("/")[0]) : undefined);
const roundId = ref("");
const shortName = (id: string) => id.split("/").slice(1).join("/") || id;
// While the first snapshot of a freshly selected experiment is in flight there are no events yet;
// show that as loading rather than as "not loaded on the server".
const status = computed(() => (trace.busy.value && !trace.events.value.length ? "加载中" : trace.status.value));
const activeRound = computed(() => {
  const rounds = trace.rounds.value;
  return rounds.find((r) => r.id === roundId.value) || rounds[rounds.length - 1] || null;
});
watch(() => form.objective, (objective) => persistStudioState({ objective }));
watch(() => trace.interaction.value, (request) => { if (request) layout.openResults(); });

async function pick(id: string) {
  roundId.value = "";
  // The URL's ?trace= only seeds the first load; once the user picks, the picked one must win on reload.
  if (route.query.trace || route.query.new) router.replace({ name: "studio-research" });
  if (id) await trace.select(id);
  else trace.clear();
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
    tab.value = "rounds";
    if (route.query.new) router.replace({ name: "studio-research" });
    await trace.select(id, true);
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
  if (route.query.trace) router.replace({ name: "studio-research" });
});
</script>
<style scoped>
.rounds { display: grid; gap: 8px; }
</style>
