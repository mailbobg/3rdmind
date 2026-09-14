<!-- web/src/views/studio/Strategy.vue -->
<template>
  <div v-if="error || pageError" class="notice" role="alert">{{ error || pageError }}<button class="text-button" @click="error = ''; pageError = ''">关闭</button></div>

  <section class="surface">
    <div class="section-heading"><h3>因子来源</h3><span>研究轮次的因子直接进入回测</span></div>
    <div class="form-grid">
      <label>实验
        <select v-model="traceId" @change="loadRounds">
          <option value="">选择实验</option>
          <option v-for="id in traceIds" :key="id" :value="id">{{ id }}</option>
        </select>
      </label>
      <label>轮次
        <select v-model="loopId" :disabled="!roundList.length" @change="pickRound">
          <option v-for="r in roundList" :key="r.loop_id" :value="r.loop_id">第 {{ r.loop_id + 1 }} 轮 · {{ r.factors.length }} 个因子</option>
        </select>
      </label>
    </div>
    <p v-if="traceId && !roundList.length" class="hint">这个实验没有带因子结果的轮次。</p>
    <div v-if="selection.length" class="table-scroll">
      <table>
        <thead><tr><th></th><th>因子</th><th class="num">权重</th></tr></thead>
        <tbody>
          <tr v-for="f in selection" :key="f.name">
            <td><input type="checkbox" v-model="f.enabled" /></td>
            <td>{{ f.name }}</td>
            <td class="num"><input type="number" step="0.5" v-model.number="f.weight" style="width: 80px" /></td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>

  <section class="surface">
    <div class="section-heading"><h3>策略参数</h3><button class="text-button" @click="toggleSource">{{ source ? "隐藏" : "查看" }}策略源码</button></div>
    <pre v-if="source">{{ source }}</pre>
    <div class="form-grid">
      <label>开始<input type="date" v-model="params.start" /></label>
      <label>结束<input type="date" v-model="params.end" /></label>
      <label>股票池<select v-model="params.market"><option value="csi300">沪深300</option><option value="csi500">中证500</option><option value="all">全市场</option></select></label>
      <label>topk<input type="number" v-model.number="params.topk" min="1" max="500" /></label>
      <label>n_drop<input type="number" v-model.number="params.n_drop" min="0" max="500" /></label>
      <label>初始资金<input type="number" v-model.number="params.account" min="1000" step="100000" /></label>
      <label>买入费率<input type="number" v-model.number="params.open_cost" min="0" max="0.1" step="0.0001" /></label>
      <label>卖出费率<input type="number" v-model.number="params.close_cost" min="0" max="0.1" step="0.0001" /></label>
    </div>
    <div class="actions">
      <button class="primary" :disabled="busy || !env?.data_ready" @click="submit">运行回测</button>
      <span v-if="!env?.data_ready" class="hint">Qlib 数据未就绪，无法回测。</span>
    </div>
  </section>

  <div class="two-col">
    <section class="surface">
      <div class="section-heading"><h3>回测记录</h3><button class="text-button" @click="load">刷新</button></div>
      <p v-if="!jobs.length" class="hint">还没有回测。</p>
      <ul class="job-list">
        <li v-for="job in jobs" :key="job.id">
          <button :class="{ selected: job.id === selectedId }" @click="select(job.id)">
            <span class="tag" :class="{ ok: job.status === 'completed', bad: job.status === 'failed' }">{{ backtestStatusLabel(job.status) }}</span>
            {{ traceLabel(job.config.trace) }} · 第 {{ Number(job.config.loop_id) + 1 }} 轮 · {{ job.config.factors?.length ?? 0 }} 因子
            <small>{{ job.config.start }} → {{ job.config.end }}</small>
          </button>
        </li>
      </ul>
    </section>
    <BacktestResult v-if="result" :result="result" />
    <p v-else class="hint">选择一条回测记录查看结果。</p>
  </div>
</template>
<script setup lang="ts">
import { onMounted, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";
import * as studio from "../../api/studio";
import type { Environment, Round } from "../../api/studio";
import { useBacktests } from "../../composables/useBacktests";
import BacktestResult from "../../components/studio/BacktestResult.vue";
import { backtestStatusLabel } from "../../components/studio/backtestStatus";
import { persistStudioState, restoreStudioState } from "../../composables/studioStorage";

const props = defineProps<{ env: Environment | null }>();
const route = useRoute();
const { jobs, selectedId, result, error, busy, load, select, run } = useBacktests();

function restore(): any { return restoreStudioState(); }
function persist(patch: Record<string, unknown>) { persistStudioState(patch); }

const saved = restore();
const traceIds = ref<string[]>([]);
const traceId = ref<string>(typeof route.query.trace === "string" ? route.query.trace : saved.strategyTrace || "");
const roundList = ref<Round[]>([]);
const loopId = ref<number>(typeof route.query.loop === "string" ? Number(route.query.loop) : saved.strategyLoop ?? 0);
const selection = ref<{ name: string; weight: number; enabled: boolean }[]>([]);
const params = reactive({
  start: "", end: "", market: "csi300" as "csi300" | "csi500" | "all",
  topk: 10, n_drop: 2, account: 1000000, open_cost: 0.0005, close_cost: 0.0015,
  ...(saved.params || {}),
});
const pageError = ref("");
const source = ref("");

function traceLabel(trace?: string) {
  if (!trace) return "—";
  const parts = trace.split("/");
  return parts[parts.length - 1] || "—";
}

function defaultDates() {
  if (params.start && params.end) return;
  const end = props.env?.end;
  if (!end) return;
  params.end = end;
  const start = new Date(end);
  start.setFullYear(start.getFullYear() - 1);
  params.start = start.toISOString().slice(0, 10);
}
watch(() => props.env, defaultDates, { immediate: true });

async function loadRounds() {
  const id = traceId.value;
  roundList.value = [];
  selection.value = [];
  if (!id) return;
  let rounds: Round[];
  try {
    rounds = (await studio.rounds(id)).filter((r) => r.factors.length);
  } catch (e: any) {
    if (id !== traceId.value) return;
    pageError.value = e.message;
    return;
  }
  if (id !== traceId.value) return;
  roundList.value = rounds;
  if (!roundList.value.some((r) => r.loop_id === loopId.value)) {
    loopId.value = roundList.value.length ? roundList.value[roundList.value.length - 1].loop_id : 0;
  }
  pickRound();
}
function pickRound() {
  const round = roundList.value.find((r) => r.loop_id === loopId.value);
  selection.value = (round?.factors || []).map((name) => ({ name, weight: 1, enabled: true }));
  persist({ strategyTrace: traceId.value, strategyLoop: loopId.value });
}
async function toggleSource() {
  if (source.value) { source.value = ""; return; }
  try { source.value = (await studio.strategySource()).code; } catch (e: any) { pageError.value = e.message; }
}
async function submit() {
  persist({ params: { ...params } });
  await run({
    trace: traceId.value, loop_id: loopId.value,
    factors: selection.value.filter((f) => f.enabled).map((f) => ({ name: f.name, weight: Number(f.weight) })),
    ...params,
  });
}

onMounted(async () => {
  try { traceIds.value = await studio.traces(); } catch (e: any) { pageError.value = e.message; }
  await loadRounds();
  await load();
  if (jobs.value.length && !selectedId.value) await select(jobs.value[0].id);
});
</script>
<style scoped>
.two-col { display: grid; grid-template-columns: 300px minmax(0, 1fr); gap: 14px; align-items: start; }
.job-list { list-style: none; margin: 0; padding: 0; max-height: 60vh; overflow: auto; }
.job-list button { width: 100%; text-align: left; border: 0; border-radius: 6px; padding: 6px 8px; }
.job-list button.selected { background: #eef4f1; }
.job-list small { display: block; color: var(--muted); font-size: 11px; }
@media (max-width: 900px) { .two-col { grid-template-columns: 1fr; } }
</style>
