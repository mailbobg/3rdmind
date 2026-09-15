<template>
  <button class="results-toggle" :title="layout.resultsOpen.value ? '隐藏右栏' : '显示右栏'" @click="layout.toggleResults()">
    {{ layout.resultsOpen.value ? "隐藏结果 ▸" : "◂ 显示结果" }}
  </button>
</template>
<script setup lang="ts">
import { useStudioContext } from "../../composables/studioContext";
const { layout } = useStudioContext();
</script>
