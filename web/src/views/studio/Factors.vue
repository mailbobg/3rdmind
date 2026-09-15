<template>
  <main class="workspace">
    <header class="workspace-head">
      <div>
        <div class="eyebrow">QUANTITATIVE RESEARCH / FACTORS</div>
        <h1>因子库</h1>
      </div>
      <div class="toolbar">
        <input v-model="query" placeholder="搜索因子或实验" aria-label="搜索因子" />
        <button @click="load">刷新</button>
        <button class="results-toggle" :title="layout.resultsOpen.value ? '隐藏右栏' : '显示右栏'" @click="layout.toggleResults()">{{ layout.resultsOpen.value ? "隐藏结果 ▸" : "◂ 显示结果" }}</button>
      </div>
    </header>
    <div class="workspace-body">
      <div v-if="error" class="notice" role="alert">{{ error }}<button class="text-button" @click="error = ''">关闭</button></div>
      <p class="hint" style="margin: 0 0 12px">因子来自 RD-Agent 研究轮次的 <code>result.h5</code> 产物，勾选后进入组合回测。同一因子在不同轮次是不同版本。</p>
      <section v-for="group in groups" :key="group.trace" class="surface">
        <div class="section-heading">
          <h3>{{ shortName(group.trace) }}</h3>
          <span>{{ group.trace.split("/")[0] }} · {{ group.items.length }} 个因子</span>
        </div>
        <div class="table-scroll">
          <table>
            <thead>
              <tr><th></th><th>因子</th><th>轮次</th><th class="num">IC</th><th class="num">Rank IC</th><th class="num">年化超额</th></tr>
            </thead>
            <tbody>
              <tr v-for="f in group.items" :key="key(f)" class="selectable" :class="{ selected: key(f) === selectedKey }" @click="selectedKey = key(f); layout.openResults()">
                <td><input type="checkbox" :checked="basket.has(f)" @click.stop @change="basket.toggle(f)" aria-label="加入组合" /></td>
                <td><code>{{ f.name }}</code></td>
                <td>第 {{ f.loop_id + 1 }} 轮</td>
                <td class="num">{{ fmt(f.metrics["IC"]) }}</td>
                <td class="num">{{ fmt(f.metrics["Rank IC"]) }}</td>
                <td class="num" :class="sign(f.metrics['1day.excess_return_with_cost.annualized_return'])">{{ pct(f.metrics["1day.excess_return_with_cost.annualized_return"]) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      <p v-if="!groups.length && !loading" class="empty">还没有带因子产物的研究轮次。先在「AI 研究」里跑一次因子研发。</p>
    </div>
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
        <p class="hint">{{ selected.trace }} · 第 {{ selected.loop_id + 1 }} 轮</p>
        <section class="surface">
          <div class="section-heading"><h3>所在轮次的 Qlib 评估</h3><span>与同轮其他因子合并训练</span></div>
          <MetricTable :metrics="selected.metrics" />
        </section>
        <section class="surface">
          <div class="section-heading">
            <h3>factor.py</h3>
            <button v-if="selected.code" class="text-button" @click="download(`${selected.name}.py`, selected.code!)">下载代码</button>
          </div>
          <pre v-if="selected.code"><code>{{ selected.code }}</code></pre>
          <p v-else class="hint">这个实验没有记录代码事件。</p>
        </section>
      </template>
      <template v-else-if="basket.items.length">
        <section class="surface">
          <div class="section-heading"><h3>已选组合</h3><span>{{ basket.items.length }} 个因子</span></div>
          <div class="chips"><span class="chip" v-for="f in basket.items" :key="key(f)">{{ f.name }}</span></div>
          <div class="actions">
            <router-link :to="{ name: 'studio-backtest' }" custom v-slot="{ navigate }"><button class="primary" @click="navigate">去组合回测 →</button></router-link>
            <button @click="basket.clear">清空</button>
          </div>
        </section>
      </template>
      <p v-else class="empty">点一行查看因子代码与评估。</p>
    </div>
  </aside>
</template>
<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import * as studio from "../../api/studio";
import type { LibraryFactor } from "../../api/studio";
import MetricTable from "../../components/studio/MetricTable.vue";
import { download, useStudioContext } from "../../composables/studioContext";
import { basketKey as key } from "../../composables/useFactorBasket";

const { basket, layout } = useStudioContext();
const all = ref<LibraryFactor[]>([]);
const query = ref("");
const error = ref("");
const loading = ref(false);
const selectedKey = ref("");
const shortName = (id: string) => id.split("/").slice(1).join("/") || id;
const fmt = (v?: number) => (typeof v === "number" ? v.toFixed(4) : "—");
const pct = (v?: number) => (typeof v === "number" ? (v * 100).toFixed(2) + "%" : "—");
const sign = (v?: number) => (typeof v !== "number" ? "" : v >= 0 ? "pos" : "neg");

const groups = computed(() => {
  const q = query.value.trim().toLowerCase();
  const map = new Map<string, LibraryFactor[]>();
  for (const f of all.value) {
    if (q && !`${f.name} ${f.trace}`.toLowerCase().includes(q)) continue;
    if (!map.has(f.trace)) map.set(f.trace, []);
    map.get(f.trace)!.push(f);
  }
  return [...map.entries()].map(([trace, items]) => ({ trace, items }));
});
const selected = computed(() => all.value.find((f) => key(f) === selectedKey.value) || null);

async function load() {
  loading.value = true;
  try { all.value = await studio.factorLibrary(); error.value = ""; }
  catch (e) { error.value = e instanceof Error ? e.message : String(e); }
  finally { loading.value = false; }
}
onMounted(load);
</script>
