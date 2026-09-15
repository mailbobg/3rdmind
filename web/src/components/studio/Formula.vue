<template>
  <div class="formula" v-html="html"></div>
</template>
<script setup lang="ts">
import { computed } from "vue";
import katex from "katex";
import "katex/dist/katex.min.css";
const props = defineProps<{ source: string }>();
// Agent formulations are LaTeX fragments; render them, and fall back to the raw text when KaTeX cannot parse.
const html = computed(() => {
  try { return katex.renderToString(props.source, { displayMode: true, throwOnError: true, strict: "ignore" }); }
  catch { return `<code>${props.source.replace(/&/g, "&amp;").replace(/</g, "&lt;")}</code>`; }
});
</script>
<style scoped>
.formula { background: var(--soft); border: 1px solid var(--line); border-radius: 8px; padding: 6px 10px; overflow-x: auto; font-size: 13px; }
.formula :deep(.katex-display) { margin: 6px 0; }
</style>
