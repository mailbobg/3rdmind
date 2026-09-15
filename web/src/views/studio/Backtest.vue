<template>
  <main class="workspace">
    <header class="workspace-head">
      <div>
        <div class="eyebrow">QUANTITATIVE RESEARCH / PORTFOLIO</div>
        <h1>组合回测</h1>
      </div>
      <div class="toolbar">
        <button @click="toggleSource">{{ source ? "隐藏策略源码" : "查看策略源码" }}</button>
        <button class="dark" :disabled="backtests.busy.value || !env?.data_ready || !basket.items.length" @click="submit">▶ 运行回测</button>
        <button class="results-toggle" :title="layout.resultsOpen.value ? '隐藏右栏' : '显示右栏'" @click="layout.toggleResults()">{{ layout.resultsOpen.value ? "隐藏结果 ▸" : "◂ 显示结果" }}</button>
      </div>
    </header>
    <div class="workspace-body">
      <div v-if="backtests.error.value || pageError" class="notice" role="alert">
        {{ backtests.error.value || pageError }}<button class="text-button" @click="backtests.error.value = ''; pageError = ''">关闭</button>
      </div>
      <div v-if="!env" class="notice">后端未连接，无法回测。运行 <code>scripts/start-backend.sh</code> 后刷新。</div>
      <div v-else-if="!env.data_ready" class="notice">Qlib 数据未就绪（{{ env.provider_uri }}），无法回测。</div>

      <section class="surface">
        <div class="section-heading">
          <h3>回测什么：信号篮</h3>
          <span>{{ basket.items.length }} 个信号 · <router-link :to="{ name: 'studio-factors' }">去因子库增减</router-link></span>
        </div>
        <div v-if="basket.items.length" class="table-scroll">
          <table>
            <thead><tr><th>信号</th><th>来源</th><th class="num">IC</th><th class="num">Rank IC</th><th>覆盖</th><th class="num">权重</th><th></th></tr></thead>
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
                <td class="num"><input type="number" step="0.5" :value="f.weight" style="width: 72px" :title="'负权重 = 反向使用这个信号'" @change="basket.setWeight(f, Number(($event.target as HTMLInputElement).value))" /></td>
                <td><button class="text-button" @click="basket.toggle(f)">移除</button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="hint">还没有选信号。去 <router-link :to="{ name: 'studio-factors' }">因子库</router-link> 勾选，或在研究轮次里点"用 N 个因子回测"。</p>
        <div v-if="basket.items.length" class="hint" style="margin-top: 8px">
          <div>IC 为负的信号请把权重设为 −1 反向使用（排名加权模式下有效；LightGBM 会自己学方向）。</div>
          <div v-if="factorRefs.length >= 2">
            <template v-if="correlation">篮内最高两两相关 |ρ| = <b :class="maxCorr >= 0.7 ? 'neg' : ''">{{ maxCorr.toFixed(2) }}</b><span v-if="maxCorr >= 0.7">，有信号基本重复，建议只留一个。</span></template>
            <template v-else-if="correlationError">相关性：{{ correlationError }}</template>
            <template v-else>正在计算篮内相关性…</template>
          </div>
          <div v-if="coverage">信号共同覆盖 <b>{{ coverage.start }} → {{ coverage.end }}</b>
            <span v-if="coverageUnknown"> （另有 {{ coverageUnknown }} 个信号未分析，未计入）</span>。
            <button class="text-button" @click="fitToCoverage">按覆盖区间填回测日期</button>
          </div>
        </div>
      </section>

      <section class="surface">
        <div class="section-heading"><h3>信号怎么变成评分</h3><span>{{ method === "lgbm" ? "LightGBM 回归 · 标签为次日收益的截面 z-score" : "截面百分位排名 · 按权重加权" }}</span></div>
        <p class="hint" style="margin: 0 0 8px">排名加权：每天把每个信号在全市场做百分位排名，再按权重求和，简单、不用训练、结果可解释。训练 LightGBM：用历史区间学信号与次日收益的非线性关系，需要足够长的训练期，且信号弱时很快早停。</p>
        <div class="actions" style="margin: 0 0 10px">
          <label class="radio"><input type="radio" value="rank" v-model="method" /> 排名加权</label>
          <label class="radio"><input type="radio" value="lgbm" v-model="method" /> 训练 LightGBM</label>
        </div>
        <template v-if="method === 'lgbm'">
          <div class="form-grid">
            <label>训练开始<input type="date" v-model="lgbm.train[0]" /></label>
            <label>训练结束<input type="date" v-model="lgbm.train[1]" /></label>
            <label>验证开始<input type="date" v-model="lgbm.valid[0]" /></label>
            <label>验证结束<input type="date" v-model="lgbm.valid[1]" /></label>
          </div>
          <p class="hint" style="margin: 8px 0 0">训练 → 验证 → 回测三段必须依次不重叠；验证集用于早停。权重列在此模式下不生效。</p>
          <details>
            <summary>LightGBM 参数</summary>
            <div class="form-grid">
              <label>learning_rate<input type="number" step="0.01" min="0.001" max="1" v-model.number="lgbm.params.learning_rate" /></label>
              <label>num_leaves<input type="number" min="2" max="1024" v-model.number="lgbm.params.num_leaves" /></label>
              <label>max_depth<input type="number" min="-1" max="64" v-model.number="lgbm.params.max_depth" /></label>
              <label>n_estimators<input type="number" min="10" max="5000" v-model.number="lgbm.params.n_estimators" /></label>
              <label>early_stopping<input type="number" min="0" max="1000" v-model.number="lgbm.params.early_stopping_rounds" /></label>
              <label>colsample_bytree<input type="number" step="0.05" min="0.1" max="1" v-model.number="lgbm.params.colsample_bytree" /></label>
              <label>subsample<input type="number" step="0.05" min="0.1" max="1" v-model.number="lgbm.params.subsample" /></label>
              <label>lambda_l2<input type="number" step="1" min="0" v-model.number="lgbm.params.lambda_l2" /></label>
            </div>
          </details>
        </template>
      </section>

      <section class="surface">
        <div class="section-heading"><h3>评分怎么变成持仓</h3><span>TopkDropoutStrategy · 前一日评分 · 当日收盘成交</span></div>
        <p class="hint" style="margin: 0 0 8px">每天按评分从高到低，持有前 topk 只；已持有但跌出前列的，每天最多换出 n_drop 只。换手越高，费率影响越大。</p>
        <div class="form-grid">
          <label>开始<input type="date" v-model="params.start" /></label>
          <label>结束<input type="date" v-model="params.end" /></label>
          <label>股票池<select v-model="params.market"><option value="csi300">沪深300</option><option value="csi500">中证500</option><option value="all">全市场</option></select></label>
          <label title="用于对比的指数代码">基准指数<input v-model="params.benchmark" /></label>
          <label title="每天持有的股票数量">持股数 topk<input type="number" v-model.number="params.topk" min="1" max="500" /></label>
          <label title="每天最多换出的股票数量">每日换出 n_drop<input type="number" v-model.number="params.n_drop" min="0" max="500" /></label>
          <label>初始资金<input type="number" v-model.number="params.account" min="1000" step="100000" /></label>
          <label title="0.0005 = 万分之五">买入费率<input type="number" v-model.number="params.open_cost" min="0" max="0.1" step="0.0001" /></label>
          <label title="0.0015 = 千分之一点五，含印花税">卖出费率<input type="number" v-model.number="params.close_cost" min="0" max="0.1" step="0.0001" /></label>
        </div>
        <div v-if="dateWarning" class="notice" style="margin: 10px 0 0">{{ dateWarning }}</div>
        <p v-else class="hint" style="margin: 10px 0 0">回测区间必须落在信号覆盖范围内，超出会直接报错而不是延续持仓。</p>
      </section>

      <section v-if="source" class="surface">
        <div class="section-heading"><h3>studio_worker.py</h3><span>只读 · 服务端执行</span></div>
        <pre><code>{{ source }}</code></pre>
      </section>
    </div>
  </main>

  <aside class="results">
    <header class="result-head">
      <div>
        <div class="eyebrow">BACKTEST RESULT</div>
        <h2>{{ result ? `回测 ${result.id.slice(0, 8)}` : "回测结果" }}</h2>
      </div>
      <div class="toolbar">
        <select :value="backtests.selectedId.value" aria-label="回测历史" @change="backtests.select(($event.target as HTMLSelectElement).value); layout.openResults()">
          <option value="">回测历史</option>
          <option v-for="job in backtests.jobs.value" :key="job.id" :value="job.id">{{ jobLabel(job) }}</option>
        </select>
        <button v-if="result?.metrics" class="text-button" @click="exportResult">导出 JSON</button>
      </div>
    </header>
    <div class="result-scroll">
      <BacktestResult v-if="result" :result="result" />
      <p v-else class="empty">运行回测后在这里看指标、净值曲线与日志。</p>
    </div>
  </aside>
</template>
<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import * as studio from "../../api/studio";
import type { BacktestSummary, CorrelationMatrix as Corr, FactorRef, FactorWeight, LibraryFactor } from "../../api/studio";
import BacktestResult from "../../components/studio/BacktestResult.vue";
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

async function toggleSource() {
  if (source.value) { source.value = ""; return; }
  try { source.value = (await studio.strategySource()).code; } catch (e) { pageError.value = e instanceof Error ? e.message : String(e); }
}
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
