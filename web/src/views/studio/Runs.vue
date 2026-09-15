<template>
  <ObjectBar title="运行记录" :description="`${backtests.jobs.value.length} 次回测 · ${trace.traceIds.value.length} 个研究实验`" />

  <main class="workspace">
    <div class="col-head">
      <div class="seg">
        <button :class="{ on: showResearch && showBacktests }" @click="showResearch = true; showBacktests = true">全部</button>
        <button :class="{ on: showResearch && !showBacktests }" @click="showResearch = true; showBacktests = false">研究</button>
        <button :class="{ on: !showResearch && showBacktests }" @click="showResearch = false; showBacktests = true">回测</button>
      </div>
      <div class="col-actions">
        <button @click="refresh">刷新</button>
        <ResultsToggle />
      </div>
    </div>
    <div class="col-body">
      <section class="panel grow">
        <div class="panel-head"><h3>记录 <span class="hint">{{ rows.length }} 条</span></h3></div>
        <div class="panel-body flush">
          <table v-if="rows.length">
            <thead><tr><th>类型</th><th>名称</th><th>说明</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="row in rows" :key="row.key" class="selectable" :class="{ selected: row.key === selectedKey }" @click="open(row)">
                <td><span class="tag">{{ row.kind === 'research' ? '研究' : '回测' }}</span></td>
                <td><code>{{ row.name }}</code></td>
                <td class="hint">{{ row.detail }}</td>
                <td><span class="tag" :class="row.statusClass">{{ row.status }}</span></td>
              </tr>
            </tbody>
          </table>
          <p v-else class="empty">还没有记录。</p>
        </div>
      </section>
    </div>
  </main>

  <aside class="results">
    <div class="col-head">
      <div class="seg"><button class="on">{{ title }}</button></div>
      <div class="col-actions" v-if="selected">
        <router-link v-if="selected.kind === 'research'" :to="{ name: 'studio-research', query: { trace: selected.name } }" custom v-slot="{ navigate }">
          <button class="small" @click="navigate">在研究页打开 →</button>
        </router-link>
        <router-link v-else :to="{ name: 'studio-backtest' }" custom v-slot="{ navigate }">
          <button class="small" @click="navigate">在回测页打开 →</button>
        </router-link>
      </div>
    </div>
    <div class="col-body">
      <template v-if="selected?.kind === 'research'">
        <p v-if="trace.status.value === '未加载'" class="hint">这个实验的事件未加载到服务端。</p>
        <RoundDetail v-for="round in trace.rounds.value" :key="round.id" :round="round" />
      </template>
      <BacktestResult v-else-if="selected?.kind === 'backtest' && backtests.result.value" :result="backtests.result.value" />
      <p v-else class="empty">点一行查看详情。</p>
    </div>
  </aside>
</template>
<script setup lang="ts">
import { computed, ref } from "vue";
import BacktestResult from "../../components/studio/BacktestResult.vue";
import RoundDetail from "../../components/studio/RoundDetail.vue";
import ObjectBar from "../../components/studio/ObjectBar.vue";
import ResultsToggle from "../../components/studio/ResultsToggle.vue";
import { backtestStatusLabel } from "../../components/studio/backtestStatus";
import { useStudioContext } from "../../composables/studioContext";

interface Row { key: string; kind: "research" | "backtest"; name: string; detail: string; status: string; statusClass: string; id: string }

const { trace, backtests, layout } = useStudioContext();
const showResearch = ref(true);
const showBacktests = ref(true);
const selectedKey = ref("");

const rows = computed<Row[]>(() => {
  const research: Row[] = showResearch.value
    ? trace.traceIds.value.map((id) => ({
        key: `r:${id}`, kind: "research", id, name: id.split("/").slice(1).join("/") || id,
        detail: id.split("/")[0],
        status: id === trace.traceId.value ? trace.status.value : "—",
        statusClass: id === trace.traceId.value && trace.status.value === "运行中" ? "live" : "",
      }))
    : [];
  const jobs: Row[] = showBacktests.value
    ? backtests.jobs.value.map((job) => ({
        key: `b:${job.id}`, kind: "backtest", id: job.id, name: job.id.slice(0, 8),
        detail: `${job.config.factors?.length ?? 0} 因子 · ${job.config.start} → ${job.config.end} · ${job.config.market}`,
        status: backtestStatusLabel(job.status),
        statusClass: job.status === "completed" ? "ok" : job.status === "failed" ? "bad" : "live",
      }))
    : [];
  return [...jobs, ...research];
});
const selected = computed(() => rows.value.find((r) => r.key === selectedKey.value) || null);
const title = computed(() => (selected.value ? (selected.value.kind === "research" ? selected.value.name : `回测 ${selected.value.name}`) : "详情"));

async function open(row: Row) {
  selectedKey.value = row.key;
  layout.openResults();
  if (row.kind === "research") await trace.select(row.id);
  else await backtests.select(row.id);
}
async function refresh() {
  await Promise.all([trace.loadTraces(), backtests.load()]);
}
</script>
