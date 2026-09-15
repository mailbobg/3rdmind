<template>
  <main class="workspace">
    <header class="workspace-head">
      <div>
        <div class="eyebrow">QUANTITATIVE RESEARCH / FACTORS</div>
        <h1>因子库</h1>
      </div>
      <div class="toolbar">
        <input v-model="query" placeholder="搜索因子、描述或实验" aria-label="搜索因子" />
        <label class="check"><input type="checkbox" v-model="acceptedOnly" /> 只看 agent 接受的轮次</label>
        <button :disabled="analyzing" @click="analyzeAll">{{ analyzing ? `分析中 ${analyzed}/${pending.length}…` : "分析全部" }}</button>
        <button @click="load">刷新</button>
        <button class="results-toggle" :title="layout.resultsOpen.value ? '隐藏右栏' : '显示右栏'" @click="layout.toggleResults()">{{ layout.resultsOpen.value ? "隐藏结果 ▸" : "◂ 显示结果" }}</button>
      </div>
    </header>
    <div class="workspace-body">
      <div v-if="error" class="notice" role="alert">{{ error }}<button class="text-button" @click="error = ''">关闭</button></div>
      <section class="surface guide">
        <strong>怎么挑因子</strong>
        <ol>
          <li><b>单独有没有用</b>：看单因子 IC 与 Rank IC 的符号和 ICIR（均值 ÷ 波动，越高越稳）。|IC| &lt; 0.01 且 ICIR 接近 0 的因子基本是噪声；IC 为负的因子回测时把权重设成 −1 即可反向使用。</li>
          <li><b>放一起合不合适</b>：篮内两两相关性低（|ρ| &lt; 0.5）的因子才互补，高相关的只是同一个信号重复计权。</li>
          <li><b>能不能覆盖回测期</b>：覆盖区间要包住你打算回测的日期，否则回测会直接报错。</li>
        </ol>
        <p class="hint">单因子指标由后端按逐日截面相关计算（标签为次日收益），首次计算每个因子约 10 秒，之后缓存。agent 结论是它在原生流程里对整轮假设的评价，不是对单个因子的。</p>
      </section>

      <section v-for="group in groups" :key="group.trace" class="surface">
        <div class="section-heading">
          <h3>{{ shortName(group.trace) }}</h3>
          <span>{{ group.trace.split("/")[0] }} · {{ group.items.length }} 个因子</span>
        </div>
        <div class="table-scroll">
          <table class="library">
            <thead>
              <tr>
                <th></th><th>因子</th><th>轮次 · agent 结论</th>
                <th class="num">IC</th><th class="num">Rank IC</th><th class="num">ICIR</th><th>覆盖</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="f in group.items" :key="key(f)" class="selectable" :class="{ selected: key(f) === selectedKey }" @click="select(f)">
                <td><input type="checkbox" :checked="basket.has(f)" @click.stop @change="basket.toggle(f)" aria-label="加入组合" /></td>
                <td class="name-cell">
                  <code>{{ f.name }}</code>
                  <div class="desc">{{ f.description || "（agent 没有记录描述）" }}</div>
                </td>
                <td>
                  第 {{ f.loop_id + 1 }} 轮
                  <span v-if="f.decision === true" class="tag ok">接受</span>
                  <span v-else-if="f.decision === false" class="tag bad">拒绝</span>
                  <span v-else class="tag">无结论</span>
                </td>
                <template v-if="f.analysis">
                  <td class="num" :class="sign(f.analysis.ic.mean)">{{ f.analysis.ic.mean.toFixed(4) }}</td>
                  <td class="num" :class="sign(f.analysis.rank_ic.mean)">{{ f.analysis.rank_ic.mean.toFixed(4) }}</td>
                  <td class="num">{{ f.analysis.ic.ir == null ? "—" : f.analysis.ic.ir.toFixed(2) }}</td>
                  <td class="hint nowrap">{{ f.analysis.coverage.start }} → {{ f.analysis.coverage.end }}</td>
                </template>
                <template v-else>
                  <td colspan="4" class="hint">
                    <span v-if="busyKey === key(f)">分析中…</span>
                    <button v-else class="text-button" @click.stop="analyze(f)">计算单因子指标</button>
                  </td>
                </template>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      <p v-if="!groups.length && !loading" class="empty">还没有带因子产物的研究轮次。先在「AI 研究」里跑一次因子研发。</p>
    </div>

    <footer class="basket-bar" v-if="basket.items.length">
      <div class="basket-info">
        <strong>组合篮 · {{ basket.items.length }} 个信号</strong>
        <div class="chips">
          <span class="chip" v-for="f in basket.items" :key="key(f)" :title="`${f.trace} · 第 ${f.loop_id + 1} 轮`">
            {{ f.name }} <button class="chip-x" @click="basket.toggle(f)" aria-label="移出">×</button>
          </span>
        </div>
        <div class="hint" v-if="basketFactors.length >= 2">
          <template v-if="correlation">最高两两相关 |ρ| = <b :class="maxCorr >= 0.7 ? 'neg' : maxCorr >= 0.5 ? '' : 'pos'">{{ maxCorr.toFixed(2) }}</b>
            <span v-if="maxCorr >= 0.7">，有因子基本重复，建议只留一个</span>
            <span v-else-if="maxCorr >= 0.5">，相关偏高</span>
            <span v-else>，互补性好</span>
          </template>
          <template v-else-if="correlationError">相关性：{{ correlationError }}</template>
          <template v-else>正在计算相关性…</template>
        </div>
      </div>
      <div class="actions" style="margin: 0">
        <button @click="basket.clear">清空</button>
        <router-link :to="{ name: 'studio-backtest' }" custom v-slot="{ navigate }"><button class="dark" @click="navigate">去组合回测 →</button></router-link>
      </div>
    </footer>
  </main>

  <aside class="results">
    <header class="result-head">
      <div>
        <div class="eyebrow">FACTOR DETAIL</div>
        <h2>{{ selected ? selected.name : "因子详情" }}</h2>
      </div>
      <div class="toolbar" v-if="selected">
        <button :class="basket.has(selected) ? '' : 'primary'" @click="basket.toggle(selected)">{{ basket.has(selected) ? "移出组合" : "加入组合" }}</button>
      </div>
    </header>
    <div class="result-scroll">
      <template v-if="selected">
        <section class="surface">
          <div class="section-heading"><h3>这是什么</h3><span>{{ selected.trace }} · 第 {{ selected.loop_id + 1 }} 轮</span></div>
          <p style="margin: 0 0 8px">{{ selected.description || "agent 没有记录描述。" }}</p>
          <Formula v-if="selected.formulation" :source="selected.formulation" />
          <div v-if="selected.variables && Object.keys(selected.variables).length" class="hint" style="margin-top: 6px">
            变量：<span v-for="(meaning, v) in selected.variables" :key="v"><code>{{ v }}</code> {{ meaning }}； </span>
          </div>
        </section>
        <section class="surface">
          <div class="section-heading"><h3>为什么提出</h3>
            <span v-if="selected.decision === true" class="tag ok">agent 接受本轮</span>
            <span v-else-if="selected.decision === false" class="tag bad">agent 拒绝本轮</span>
          </div>
          <p v-if="selected.hypothesis" style="margin: 0 0 6px">{{ selected.hypothesis }}</p>
          <p v-else class="hint">这一轮没有记录假设文本。</p>
          <p v-if="selected.reason" class="hint">agent 评价：{{ selected.reason }}</p>
        </section>
        <section class="surface">
          <div class="section-heading"><h3>单因子分析</h3><span>沪深300 · 次日收益</span></div>
          <template v-if="selected.analysis">
            <div class="cards">
              <div><small>IC 均值</small><strong :class="sign(selected.analysis.ic.mean)">{{ selected.analysis.ic.mean.toFixed(4) }}</strong></div>
              <div><small>ICIR</small><strong>{{ selected.analysis.ic.ir == null ? "—" : selected.analysis.ic.ir.toFixed(2) }}</strong></div>
              <div><small>IC &gt; 0 的天数占比</small><strong>{{ (selected.analysis.ic.positive_ratio * 100).toFixed(0) }}%</strong></div>
              <div><small>Rank IC 均值</small><strong :class="sign(selected.analysis.rank_ic.mean)">{{ selected.analysis.rank_ic.mean.toFixed(4) }}</strong></div>
              <div><small>Rank ICIR</small><strong>{{ selected.analysis.rank_ic.ir == null ? "—" : selected.analysis.rank_ic.ir.toFixed(2) }}</strong></div>
              <div><small>交易日 / 样本</small><strong>{{ selected.analysis.days }} / {{ selected.analysis.rows.toLocaleString() }}</strong></div>
            </div>
            <p class="hint">覆盖 {{ selected.analysis.coverage.start }} → {{ selected.analysis.coverage.end }}。</p>
            <p class="hint" style="margin: 8px 0 2px">按月 Rank IC</p>
            <IcBars :monthly="selected.analysis.monthly" field="rank_ic" label="Rank IC" />
          </template>
          <p v-else-if="busyKey === key(selected)" class="hint">分析中，约 10 秒…</p>
          <p v-else class="hint">尚未计算。<button class="text-button" @click="analyze(selected)">现在计算</button></p>
        </section>
        <section class="surface" v-if="correlation && basketFactors.length >= 2">
          <div class="section-heading"><h3>篮内相关性</h3><span>{{ basketFactors.length }} 个因子</span></div>
          <CorrelationMatrix :data="correlation" />
        </section>
        <section class="surface">
          <div class="section-heading">
            <h3>所在轮次的 Qlib 评估</h3><span>与同轮其他因子合并训练的结果，不是单因子</span>
          </div>
          <MetricTable :metrics="selected.metrics" />
        </section>
        <section class="surface">
          <div class="section-heading">
            <h3>factor.py</h3>
            <button v-if="selected.code" class="text-button" @click="download(`${selected.name}.py`, selected.code!)">下载代码</button>
          </div>
          <pre v-if="selected.code"><code>{{ selected.code }}</code></pre>
          <p v-else class="hint">这个实验没有记录代码。</p>
        </section>
      </template>
      <template v-else-if="correlation && basketFactors.length >= 2">
        <section class="surface">
          <div class="section-heading"><h3>篮内相关性</h3><span>{{ basketFactors.length }} 个因子</span></div>
          <CorrelationMatrix :data="correlation" />
        </section>
      </template>
      <p v-else class="empty">点一行查看因子说明、单因子分析与代码。</p>
    </div>
  </aside>
</template>
<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import * as studio from "../../api/studio";
import type { CorrelationMatrix as Corr, FactorRef, LibraryFactor } from "../../api/studio";
import CorrelationMatrix from "../../components/studio/CorrelationMatrix.vue";
import Formula from "../../components/studio/Formula.vue";
import IcBars from "../../components/studio/IcBars.vue";
import MetricTable from "../../components/studio/MetricTable.vue";
import { download, useStudioContext } from "../../composables/studioContext";
import { basketKey as key } from "../../composables/useFactorBasket";

const { basket, layout } = useStudioContext();
const all = ref<LibraryFactor[]>([]);
const query = ref("");
const acceptedOnly = ref(false);
const error = ref("");
const loading = ref(false);
const selectedKey = ref("");
const busyKey = ref("");
const analyzing = ref(false);
const analyzed = ref(0);
const shortName = (id: string) => id.split("/").slice(1).join("/") || id;
const sign = (v?: number | null) => (typeof v !== "number" ? "" : v >= 0 ? "pos" : "neg");

const groups = computed(() => {
  const q = query.value.trim().toLowerCase();
  const map = new Map<string, LibraryFactor[]>();
  for (const f of all.value) {
    if (acceptedOnly.value && f.decision !== true) continue;
    if (q && !`${f.name} ${f.description || ""} ${f.trace}`.toLowerCase().includes(q)) continue;
    if (!map.has(f.trace)) map.set(f.trace, []);
    map.get(f.trace)!.push(f);
  }
  return [...map.entries()].map(([trace, items]) => ({ trace, items }));
});
const selected = computed(() => all.value.find((f) => key(f) === selectedKey.value) || null);
const pending = computed(() => all.value.filter((f) => !f.analysis));

async function load() {
  loading.value = true;
  try { all.value = await studio.factorLibrary(); error.value = ""; }
  catch (e) { error.value = e instanceof Error ? e.message : String(e); }
  finally { loading.value = false; }
}
async function analyze(f: LibraryFactor) {
  busyKey.value = key(f);
  try { f.analysis = await studio.factorAnalysis(f); }
  catch (e) { error.value = `${f.name}：${e instanceof Error ? e.message : String(e)}`; }
  finally { busyKey.value = ""; }
}
async function analyzeAll() {
  // Sequential on purpose: each analysis is a Qlib subprocess and parallel runs would fight for CPU and memory.
  analyzing.value = true;
  analyzed.value = 0;
  try { for (const f of [...pending.value]) { await analyze(f); analyzed.value++; } }
  finally { analyzing.value = false; }
}
function select(f: LibraryFactor) {
  selectedKey.value = key(f);
  layout.openResults();
  if (!f.analysis && busyKey.value !== key(f)) analyze(f);
}

// Pairwise correlation of the factors (not model predictions) currently in the basket.
const basketFactors = computed<FactorRef[]>(() =>
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
watch(basketFactors, (refs) => {
  clearTimeout(correlationTimer);
  correlation.value = null;
  correlationError.value = "";
  if (refs.length < 2) return;
  correlationTimer = setTimeout(async () => {
    try { correlation.value = await studio.factorCorrelation(refs); }
    catch (e) { correlationError.value = e instanceof Error ? e.message : String(e); }
  }, 400);
}, { immediate: true, deep: true });

onMounted(load);
</script>
<style scoped>
.guide { background: var(--soft); }
.guide ol { margin: 6px 0 8px; padding-left: 20px; }
.guide li { margin: 4px 0; }
.check { flex-direction: row; align-items: center; gap: 6px; color: var(--ink); white-space: nowrap; }
.library .name-cell { max-width: 420px; }
.library .desc { color: var(--muted); font-size: 11px; line-height: 1.5; margin-top: 2px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.nowrap { white-space: nowrap; }
.basket-bar { display: flex; justify-content: space-between; align-items: center; gap: 14px; padding: 12px 22px; border-top: 1px solid var(--line); background: var(--paper); border-radius: 0 0 16px 16px; }
.basket-info { display: grid; gap: 6px; min-width: 0; }
.chip-x { border: 0; background: none; padding: 0 0 0 4px; color: var(--muted); cursor: pointer; font-size: 12px; }
.pos { color: var(--green); }
.neg { color: var(--danger); }
</style>
