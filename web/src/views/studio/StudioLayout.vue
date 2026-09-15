<template>
  <div class="studio" :class="{ 'results-collapsed': !resultsOpen }"
    :style="{ gridTemplateColumns: resultsOpen ? `${widths.rail}px 6px minmax(360px, 1fr) 6px ${widths.results}px` : `${widths.rail}px 6px minmax(360px, 1fr)` }">
    <aside class="rail">
      <a class="brand" href="#/studio/research"
        ><span class="brand-mark">R</span><span>RESEARCH STUDIO<small>RD-Agent × Qlib</small></span></a
      >
      <nav class="task-navigation" aria-label="工作任务">
        <router-link v-for="item in menu" :key="item.name" :to="{ name: item.name }" custom v-slot="{ navigate, isActive }">
          <button :class="{ selected: isActive }" :aria-current="isActive ? 'page' : undefined" @click="navigate">
            <span class="nav-symbol">{{ item.symbol }}</span>
            <span>{{ item.title }}<small>{{ item.desc }}</small></span>
            <span v-if="item.count !== undefined" class="nav-count">{{ item.count }}</span>
          </button>
        </router-link>
      </nav>
      <div class="navigation-note">
        <strong>标准工作流</strong>
        <p>研究产生候选 → 因子库挑选 → 组合回测验证。</p>
        <p>所有成功与失败都保留在运行记录中。</p>
      </div>
      <div class="rail-bottom">
        <template v-if="env">
          <i :class="{ online: env.data_ready }"></i>{{ env.data_ready ? "Qlib 数据已就绪" : "等待 Qlib 数据" }}
          <small>{{ env.start || "—" }} → {{ env.end || "—" }}<br />{{ (env.chat_model || "未配置研究模型").replace("deepseek/", "") }}</small>
        </template>
        <template v-else>
          <i></i>后端未连接
          <small>运行 <code>scripts/start-backend.sh</code> 后 <button class="text-button" @click="loadEnv">重试</button></small>
        </template>
        <a href="#/Playground">原生 Playground ↗</a>
      </div>
    </aside>
    <div class="handle handle-rail" role="separator" aria-orientation="vertical" aria-label="调整左栏宽度" @pointerdown="startDrag('rail', $event)"></div>
    <router-view />
    <div v-show="resultsOpen" class="handle handle-results" role="separator" aria-orientation="vertical" aria-label="调整右栏宽度" @pointerdown="startDrag('results', $event)"></div>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, provide } from "vue";
import { useEnvironment } from "../../composables/useEnvironment";
import { useTrace } from "../../composables/useTrace";
import { useBacktests } from "../../composables/useBacktests";
import { useFactorBasket } from "../../composables/useFactorBasket";
import { useColumnWidths } from "../../composables/useColumnWidths";
import "./studio.css";

const { env, load: loadEnv } = useEnvironment();
const trace = useTrace();
const backtests = useBacktests();
const basket = useFactorBasket();
const layout = useColumnWidths();
const { widths, startDrag, resultsOpen } = layout;
provide("layout", layout);
provide("env", env);
provide("trace", trace);
provide("backtests", backtests);
provide("basket", basket);

const menu = computed(() => [
  { name: "studio-research", symbol: "◎", title: "AI 研究", desc: "提出假设，开发并评估因子或模型" },
  { name: "studio-factors", symbol: "⊞", title: "因子库", desc: "研究产出的因子，挑选进组合", count: basket.items.length },
  { name: "studio-backtest", symbol: "◇", title: "组合回测", desc: "用已选因子构建并验证策略", count: backtests.jobs.value.length },
  { name: "studio-runs", symbol: "↗", title: "运行记录", desc: "统一查看研究与回测" },
]);

onMounted(async () => {
  await Promise.all([loadEnv(), trace.loadTraces(), backtests.load()]);
});
</script>
