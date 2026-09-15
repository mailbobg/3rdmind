<template>
  <ObjectBar title="组合回测" :description="objectDesc" :tag="method === 'lgbm' ? 'LightGBM' : '排名加权'" />

  <main class="workspace">
    <div class="col-head">
      <div class="seg">
        <button :class="{ on: tab === 'params' }" @click="tab = 'params'">⚙ 参数设置</button>
        <button :class="{ on: tab === 'source' }" @click="tab = 'source'; loadSource()">‹› 策略源码</button>
      </div>
      <div class="col-actions">
        <button class="dark" :disabled="backtests.busy.value || !env?.data_ready || !basket.items.length" @click="submit">▶ 运行回测</button>
        <ResultsToggle />
      </div>
    </div>
    <div class="col-body">
      <div v-if="backtests.error.value || pageError" class="notice" role="alert">
        {{ backtests.error.value || pageError }}<button class="text-button" @click="backtests.error.value = ''; pageError = ''">关闭</button>
      </div>
      <div v-if="!env" class="notice">后端未连接，无法回测。运行 <code>scripts/start-backend.sh</code> 后刷新。</div>
      <div v-else-if="!env.data_ready" class="notice">Qlib 数据未就绪（{{ env.provider_uri }}），无法回测。</div>

      <template v-if="tab === 'params'">
        <div class="param-bar">
          <span class="p">时间 <input type="date" v-model="params.start" /> <span class="arrow">→</span> <input type="date" v-model="params.end" /></span>
          <span class="p">初始资金 <input type="number" v-model.number="params.account" min="1000" step="100000" /></span>
          <span class="p">股票池 <select v-model="params.market"><option value="csi300">沪深300</option><option value="csi500">中证500</option><option value="all">全市场</option></select></span>
          <span class="p">基准 <input v-model="params.benchmark" /></span>
          <span class="p">持股数 <input type="number" v-model.number="params.topk" min="1" max="500" /> <i class="info" title="每天按评分从高到低持有前 topk 只">i</i></span>
          <span class="p">每日换出 <input type="number" v-model.number="params.n_drop" min="0" max="500" /> <i class="info" title="已持有但跌出前列的，每天最多换出 n_drop 只；换手越高费率影响越大">i</i></span>
          <span class="p">买入费率 <input type="number" v-model.number="params.open_cost" min="0" max="0.1" step="0.0001" /> <i class="info" title="0.0005 = 万分之五">i</i></span>
          <span class="p">卖出费率 <input type="number" v-model.number="params.close_cost" min="0" max="0.1" step="0.0001" /> <i class="info" title="0.0015 = 千分之一点五，含印花税">i</i></span>
        </div>
        <div class="param-bar">
          <span class="p">信号合成
            <select v-model="method"><option value="rank">排名加权</option><option value="lgbm">训练 LightGBM</option></select>
            <i class="info" :title="method === 'lgbm' ? '用训练区间学信号与次日收益的关系，验证区间早停，预测值当评分；三段区间依次不重叠，权重列不生效' : '每天把每个信号做截面百分位排名，按权重求和；不用训练，可解释'">i</i>
          </span>
          <template v-if="method === 'lgbm'">
            <span class="sep"></span>
            <span class="p">训练 <input type="date" v-model="lgbm.train[0]" /> <span class="arrow">→</span> <input type="date" v-model="lgbm.train[1]" /></span>
            <span class="p">验证 <input type="date" v-model="lgbm.valid[0]" /> <span class="arrow">→</span> <input type="date" v-model="lgbm.valid[1]" /></span>
            <span class="p">learning_rate <input type="number" step="0.01" min="0.001" max="1" v-model.number="lgbm.params.learning_rate" /></span>
            <span class="p">num_leaves <input type="number" min="2" max="1024" v-model.number="lgbm.params.num_leaves" /></span>
            <span class="p">max_depth <input type="number" min="-1" max="64" v-model.number="lgbm.params.max_depth" /></span>
            <span class="p">n_estimators <input type="number" min="10" max="5000" v-model.number="lgbm.params.n_estimators" /></span>
            <span class="p">early_stopping <input type="number" min="0" max="1000" v-model.number="lgbm.params.early_stopping_rounds" /></span>
          </template>
        </div>
        <div v-if="dateWarning" class="notice">{{ dateWarning }}<button v-if="coverage" class="text-button" @click="fitToCoverage">按覆盖区间填日期</button></div>

        <section class="panel grow">
          <div class="panel-head">
            <h3>信号篮 <span class="hint">{{ basket.items.length }} 个 · <router-link :to="{ name: 'studio-factors' }">去因子库增减</router-link></span></h3>
            <span class="status" :class="{ bad: maxCorr >= 0.7 }">
              <template v-if="coverage">覆盖 {{ coverage.start }} → {{ coverage.end }}</template>
              <template v-if="coverage && factorRefs.length >= 2"> · </template>
              <template v-if="factorRefs.length >= 2">
                <template v-if="correlation">最高相关 {{ maxCorr.toFixed(2) }}<template v-if="maxCorr >= 0.7">（有信号重复）</template></template>
                <template v-else-if="correlationError">相关性计算失败</template>
                <template v-else>计算相关性…</template>
              </template>
            </span>
          </div>
          <div class="panel-body flush">
            <table v-if="basket.items.length">
              <thead><tr><th>信号</th><th>来源</th><th class="num">IC</th><th class="num">Rank IC</th><th>覆盖</th><th class="num">权重 <i class="info" title="负权重 = 反向使用；LightGBM 模式下不生效">i</i></th><th></th></tr></thead>
              <tbody>
                <tr v-for="f in basket.items" :key="key(f)">
                  <td>
                    <span v-if="f.kind === 'prediction'" class="tag">模型</span> <code>{{ f.name }}</code>
                    <div class="hint desc" v-if="info(f)?.description">{{ info(f)!.description }}</div>
                  </td>
                  <td class="hint nowrap">{{ shortName(f.trace) }} · 第 {{ f.loop_id + 1 }} 轮</td>
                  <td class="num" :class="sign(info(f)?.analysis?.ic.mean)">{{ fmt4(info(f)?.analysis?.ic.mean) }}</td>
                  <td class="num" :class="sign(info(f)?.analysis?.rank_ic.mean)">{{ fmt4(info(f)?.analysis?.rank_ic.mean) }}</td>
                  <td class="hint nowrap">{{ info(f)?.analysis ? `${info(f)!.analysis!.coverage.start} → ${info(f)!.analysis!.coverage.end}` : f.kind === "prediction" ? "模型测试期" : "未分析" }}</td>
                  <td class="num"><input type="number" step="0.5" :value="f.weight" style="width: 64px; padding: 2px 6px" :disabled="method === 'lgbm'" @change="basket.setWeight(f, Number(($event.target as HTMLInputElement).value))" /></td>
                  <td><button class="text-button" @click="basket.toggle(f)">移除</button></td>
                </tr>
              </tbody>
            </table>
            <p v-else class="empty">还没有选信号。去 <router-link :to="{ name: 'studio-factors' }">因子库</router-link> 勾选，或在研究轮次里点"用 N 个因子回测"。</p>
          </div>
          <div class="panel-foot" v-if="basket.items.length">
            <span>TopkDropoutStrategy · 前一日评分 · 当日收盘成交</span>
            <span v-if="coverageUnknown">{{ coverageUnknown }} 个信号未做单因子分析，覆盖区间未计入</span>
          </div>
        </section>
      </template>

      <section v-else class="panel grow">
        <div class="panel-head"><h3>studio_worker.py</h3><span class="status">只读 · 服务端执行</span></div>
        <div class="panel-body flush"><pre style="border: 0; border-radius: 0; height: 100%"><code>{{ source || "加载中…" }}</code></pre></div>
      </section>
    </div>
  </main>

  <aside class="results">
    <div class="col-head">
      <div class="seg"><button class="on">回测结果</button></div>
      <div class="col-actions">
        <select :value="backtests.selectedId.value" aria-label="回测历史" style="max-width: 300px" @change="backtests.select(($event.target as HTMLSelectElement).value); layout.openResults()">
          <option value="">回测历史</option>
          <option v-for="job in backtests.jobs.value" :key="job.id" :value="job.id">{{ jobLabel(job) }}</option>
        </select>
        <button v-if="result?.metrics" class="small" @click="exportResult">导出 JSON</button>
      </div>
    </div>
    <div class="col-body">
      <BacktestResult v-if="result" :result="result" />
      <p v-else class="empty">运行回测后在这里看指标、净值曲线、持仓与成交。</p>
    </div>
  </aside>
</template>
<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import * as studio from "../../api/studio";
import type { BacktestSummary, CorrelationMatrix as Corr, FactorRef, FactorWeight, LibraryFactor } from "../../api/studio";
import BacktestResult from "../../components/studio/BacktestResult.vue";
import ObjectBar from "../../components/studio/ObjectBar.vue";
import ResultsToggle from "../../components/studio/ResultsToggle.vue";
import { backtestStatusLabel } from "../../components/studio/backtestStatus";
import { download, useStudioContext } from "../../composables/studioContext";
import { persistStudioState, restoreStudioState } from "../../composables/studioStorage";
import { basketKey as key } from "../../composables/useFactorBasket";

const { env, backtests, basket, layout } = useStudioContext();
const saved = restoreStudioState();
const params = reactive({
  start: "", end: "", market: "csi300" as "csi300" | "csi500" | "all", benchmark: "SH000300",
  topk: 10, n_drop: 2, account: 1000000, open_cost: 0.0005, close_cost: 0.0015,
  ...(saved.params || {}),
});
const method = ref<"rank" | "lgbm">(saved.model?.method === "lgbm" ? "lgbm" : "rank");
const lgbm = reactive({
  train: ["", ""] as [string, string],
  valid: ["", ""] as [string, string],
  params: { learning_rate: 0.05, num_leaves: 63, max_depth: 8, n_estimators: 1000, early_stopping_rounds: 50,
            colsample_bytree: 0.8, subsample: 0.8, lambda_l2: 1 },
  ...(saved.model?.method === "lgbm" ? { train: saved.model.train, valid: saved.model.valid, params: { ...saved.model.params } } : {}),
});
const pageError = ref("");
const source = ref("");
const tab = ref<"params" | "source">("params");
const objectDesc = computed(() =>
  basket.items.length
    ? `${basket.items.length} 个信号：${basket.items.map((f) => f.name).join("、")} · ${params.start || "?"} → ${params.end || "?"} · ${params.market}`
    : "信号篮为空，先去因子库挑选");
async function loadSource() {
  if (source.value) return;
  try { source.value = (await studio.strategySource()).code; } catch (e) { pageError.value = e instanceof Error ? e.message : String(e); }
}

// Factor descriptions and cached single-factor analyses come from the library; keyed the same way as the basket.
const library = ref<Record<string, LibraryFactor>>({});
const info = (f: FactorWeight) => library.value[key(f)];
const fmt4 = (v?: number | null) => (typeof v === "number" ? v.toFixed(4) : "—");
const sign = (v?: number | null) => (typeof v !== "number" ? "" : v >= 0 ? "pos" : "neg");
async function loadLibrary() {
  try { library.value = Object.fromEntries((await studio.factorLibrary()).map((f) => [key(f), f])); }
  catch { /* the signal table degrades to names only */ }
}

const factorRefs = computed<FactorRef[]>(() =>
  basket.items.filter((f) => (f.kind || "factor") === "factor").map((f) => ({ trace: f.trace, loop_id: f.loop_id, name: f.name })));
const correlation = ref<Corr | null>(null);
const correlationError = ref("");
const maxCorr = computed(() => {
  if (!correlation.value) return 0;
  let m = 0;
  correlation.value.matrix.forEach((row, i) => row.forEach((v, j) => { if (i !== j) m = Math.max(m, Math.abs(v)); }));
  return m;
});
let correlationTimer: ReturnType<typeof setTimeout> | undefined;
watch(factorRefs, (refs) => {
  clearTimeout(correlationTimer);
  correlation.value = null;
  correlationError.value = "";
  if (refs.length < 2) return;
  correlationTimer = setTimeout(async () => {
    try { correlation.value = await studio.factorCorrelation(refs); }
    catch (e) { correlationError.value = e instanceof Error ? e.message : String(e); }
  }, 400);
}, { immediate: true, deep: true });

// Intersection of the analysed signals' coverage: the widest window a backtest can use without an error.
const coverage = computed(() => {
  const spans = basket.items.map((f) => info(f)?.analysis?.coverage).filter((c): c is { start: string; end: string } => !!c);
  if (!spans.length) return null;
  return { start: spans.reduce((a, c) => (c.start > a ? c.start : a), spans[0].start), end: spans.reduce((a, c) => (c.end < a ? c.end : a), spans[0].end) };
});
const coverageUnknown = computed(() => basket.items.filter((f) => !info(f)?.analysis).length);
const dateWarning = computed(() => {
  if (!coverage.value || !params.start || !params.end) return "";
  if (params.start <= coverage.value.start) return `回测开始日 ${params.start} 不晚于信号首日 ${coverage.value.start}：策略要用前一天的评分，请把开始日往后挪。`;
  if (params.end > coverage.value.end) return `回测结束日 ${params.end} 超出信号覆盖末日 ${coverage.value.end}，会直接报错。`;
  return "";
});
function fitToCoverage() {
  if (!coverage.value) return;
  const start = new Date(coverage.value.start);
  start.setDate(start.getDate() + 1);
  params.start = start.toISOString().slice(0, 10);
  params.end = coverage.value.end;
}
const result = computed(() => backtests.result.value);
const shortName = (id: string) => id.split("/").slice(1).join("/") || id;
const jobLabel = (job: BacktestSummary) =>
  `${backtestStatusLabel(job.status)}${job.total_return != null ? ` ${(job.total_return * 100).toFixed(1)}%` : ""} · ${job.config.factors?.length ?? 0} 信号 · ${job.config.model?.method === "lgbm" ? "LGBM" : "排名"} · ${job.config.start} → ${job.config.end}`;

const shiftYears = (date: string, years: number) => { const d = new Date(date); d.setFullYear(d.getFullYear() + years); return d.toISOString().slice(0, 10); };
const dayBefore = (date: string) => { const d = new Date(date); d.setDate(d.getDate() - 1); return d.toISOString().slice(0, 10); };
function defaultDates() {
  if (!params.start || !params.end) {
    const end = env.value?.end;
    if (!end) return;
    params.end = end;
    params.start = shiftYears(end, -1);
  }
  // Default model windows: the two years before the backtest, split 1 + 1, and never overlapping it.
  if (!lgbm.train[0] && params.start) {
    lgbm.valid = [shiftYears(params.start, -1), dayBefore(params.start)];
    lgbm.train = [shiftYears(params.start, -2), dayBefore(lgbm.valid[0])];
  }
}
watch(env, defaultDates, { immediate: true });

function modelConfig() {
  return method.value === "lgbm"
    ? { method: "lgbm" as const, train: [...lgbm.train] as [string, string], valid: [...lgbm.valid] as [string, string], params: { ...lgbm.params } }
    : { method: "rank" as const };
}
async function submit() {
  const model = modelConfig();
  const accepted = await backtests.run({ factors: basket.items.map((f) => ({ ...f, weight: Number(f.weight) })), model, ...params });
  // Only remember parameters the server accepted, so a typo does not come back on the next visit.
  if (accepted) { persistStudioState({ params: { ...params }, model }); layout.openResults(); }
}
function exportResult() {
  if (result.value) download(`backtest-${result.value.id.slice(0, 8)}.json`, JSON.stringify(result.value, null, 2), "application/json");
}

onMounted(async () => {
  loadLibrary();
  if (!backtests.jobs.value.length) await backtests.load();
  if (!backtests.selectedId.value && backtests.jobs.value.length) await backtests.select(backtests.jobs.value[0].id);
});
</script>
<style scoped>
.radio { flex-direction: row; align-items: center; gap: 6px; color: var(--ink); }
.desc { font-size: 11px; max-width: 360px; white-space: normal; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.nowrap { white-space: nowrap; }
.pos { color: var(--green); }
.neg { color: var(--danger); }
</style>
