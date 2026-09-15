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
      </div>
    </header>
    <div class="workspace-body">
      <div v-if="backtests.error.value || pageError" class="notice" role="alert">
        {{ backtests.error.value || pageError }}<button class="text-button" @click="backtests.error.value = ''; pageError = ''">关闭</button>
      </div>
      <div v-if="env && !env.data_ready" class="notice">Qlib 数据未就绪（{{ env.provider_uri }}），无法回测。</div>

      <section class="surface">
        <div class="section-heading">
          <h3>因子信号</h3>
          <span>{{ basket.items.length }} 个因子 · 截面百分位排名后按权重合成</span>
        </div>
        <div v-if="basket.items.length" class="table-scroll">
          <table>
            <thead><tr><th>因子</th><th>来源</th><th class="num">权重</th><th></th></tr></thead>
            <tbody>
              <tr v-for="f in basket.items" :key="key(f)">
                <td><code>{{ f.name }}</code></td>
                <td class="hint">{{ shortName(f.trace) }} · 第 {{ f.loop_id + 1 }} 轮</td>
                <td class="num"><input type="number" step="0.5" :value="f.weight" style="width: 80px" @change="basket.setWeight(f, Number(($event.target as HTMLInputElement).value))" /></td>
                <td><button class="text-button" @click="basket.toggle(f)">移除</button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="hint">还没有选因子。去 <router-link :to="{ name: 'studio-factors' }">因子库</router-link> 勾选，或在研究轮次里点"用 N 个因子回测"。</p>
      </section>

      <section class="surface">
        <div class="section-heading"><h3>策略与回测参数</h3><span>TopkDropoutStrategy · 前一日信号 · 收盘成交</span></div>
        <div class="form-grid">
          <label>开始<input type="date" v-model="params.start" /></label>
          <label>结束<input type="date" v-model="params.end" /></label>
          <label>股票池<select v-model="params.market"><option value="csi300">沪深300</option><option value="csi500">中证500</option><option value="all">全市场</option></select></label>
          <label>基准<input v-model="params.benchmark" /></label>
          <label>topk<input type="number" v-model.number="params.topk" min="1" max="500" /></label>
          <label>n_drop<input type="number" v-model.number="params.n_drop" min="0" max="500" /></label>
          <label>初始资金<input type="number" v-model.number="params.account" min="1000" step="100000" /></label>
          <label>买入费率<input type="number" v-model.number="params.open_cost" min="0" max="0.1" step="0.0001" /></label>
          <label>卖出费率<input type="number" v-model.number="params.close_cost" min="0" max="0.1" step="0.0001" /></label>
        </div>
        <p class="hint" style="margin: 10px 0 0">回测区间必须落在因子数据覆盖范围内，超出会直接报错而不是延续持仓。</p>
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
        <select :value="backtests.selectedId.value" aria-label="回测历史" @change="backtests.select(($event.target as HTMLSelectElement).value)">
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
import type { BacktestSummary } from "../../api/studio";
import BacktestResult from "../../components/studio/BacktestResult.vue";
import { backtestStatusLabel } from "../../components/studio/backtestStatus";
import { download, useStudioContext } from "../../composables/studioContext";
import { persistStudioState, restoreStudioState } from "../../composables/studioStorage";
import { basketKey as key } from "../../composables/useFactorBasket";

const { env, backtests, basket } = useStudioContext();
const saved = restoreStudioState();
const params = reactive({
  start: "", end: "", market: "csi300" as "csi300" | "csi500" | "all", benchmark: "SH000300",
  topk: 10, n_drop: 2, account: 1000000, open_cost: 0.0005, close_cost: 0.0015,
  ...(saved.params || {}),
});
const pageError = ref("");
const source = ref("");
const result = computed(() => backtests.result.value);
const shortName = (id: string) => id.split("/").slice(1).join("/") || id;
const jobLabel = (job: BacktestSummary) =>
  `${backtestStatusLabel(job.status)} · ${job.config.factors?.length ?? 0} 因子 · ${job.config.start} → ${job.config.end}`;

function defaultDates() {
  if (params.start && params.end) return;
  const end = env.value?.end;
  if (!end) return;
  params.end = end;
  const start = new Date(end);
  start.setFullYear(start.getFullYear() - 1);
  params.start = start.toISOString().slice(0, 10);
}
watch(env, defaultDates, { immediate: true });

async function toggleSource() {
  if (source.value) { source.value = ""; return; }
  try { source.value = (await studio.strategySource()).code; } catch (e) { pageError.value = e instanceof Error ? e.message : String(e); }
}
async function submit() {
  persistStudioState({ params: { ...params } });
  await backtests.run({ factors: basket.items.map((f) => ({ ...f, weight: Number(f.weight) })), ...params });
}
function exportResult() {
  if (result.value) download(`backtest-${result.value.id.slice(0, 8)}.json`, JSON.stringify(result.value, null, 2), "application/json");
}

onMounted(async () => {
  if (!backtests.jobs.value.length) await backtests.load();
  if (!backtests.selectedId.value && backtests.jobs.value.length) await backtests.select(backtests.jobs.value[0].id);
});
</script>
