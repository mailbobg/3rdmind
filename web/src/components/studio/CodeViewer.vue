<template>
  <div>
    <div class="actions" style="margin: 0 0 8px" v-if="files.length > 1">
      <select v-model="index" aria-label="选择文件">
        <option v-for="(f, i) in files" :key="i" :value="i">{{ f.task ? f.task + " · " : "" }}{{ f.name }}</option>
      </select>
    </div>
    <pre v-if="current"><code>{{ current.code }}</code></pre>
    <p v-else class="hint">没有代码文件。</p>
  </div>
</template>
<script setup lang="ts">
import { computed, ref, watch } from "vue";
const props = defineProps<{ files: { name: string; code: string; task?: string }[] }>();
const index = ref(0);
watch(() => props.files.length, () => { index.value = Math.max(0, props.files.length - 1); });
const current = computed(() => props.files[index.value]);
defineExpose({ current });
</script>
