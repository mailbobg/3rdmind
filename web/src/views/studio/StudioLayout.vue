<template>
  <div class="studio">
    <aside class="rail">
      <a class="brand" href="#/studio/research">RESEARCH STUDIO<small>RD-Agent × Qlib</small></a>
      <nav aria-label="Studio 导航">
        <router-link :to="{ name: 'studio-research' }">研究<small>启动 RD-Agent 研究，查看假设、代码与评估</small></router-link>
        <router-link :to="{ name: 'studio-strategy' }">策略回测<small>用研究产出的因子构建组合并回测</small></router-link>
      </nav>
      <div class="rail-bottom">
        <template v-if="env">
          <i :class="{ online: env.data_ready }"></i>{{ env.data_ready ? "Qlib 数据已就绪" : "等待 Qlib 数据" }}
          <div>{{ env.start || "—" }} → {{ env.end || "—" }}</div>
          <div>{{ (env.chat_model || "未配置研究模型").replace("deepseek/", "") }}</div>
        </template>
        <template v-else>
          <i></i>后端未连接
          <div>运行 <code>scripts/start-backend.sh</code> 后 <button class="text-button" @click="load">重试</button></div>
        </template>
        <div><a href="#/Playground">原生 Playground ↗</a></div>
      </div>
    </aside>
    <main class="workspace">
      <router-view :env="env" />
    </main>
  </div>
</template>
<script setup lang="ts">
import { onMounted } from "vue";
import { useEnvironment } from "../../composables/useEnvironment";
import "./studio.css";
const { env, load } = useEnvironment();
onMounted(load);
</script>
