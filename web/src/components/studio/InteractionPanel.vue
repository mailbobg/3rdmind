<template>
  <section class="surface">
    <div class="section-heading"><h3>RD-Agent 等待你的确认</h3><span>{{ event.timestamp }}</span></div>
    <p class="hint" style="margin: 0 0 8px">{{ stageHint }}</p>
    <label v-for="field in fields" :key="field.key">
      {{ field.label }}
      <textarea v-if="typeof field.value === 'string'" :value="field.value" rows="3" @input="update(field.key, ($event.target as HTMLTextAreaElement).value)" />
      <input v-else-if="typeof field.value === 'boolean'" type="checkbox" :checked="field.value" @change="update(field.key, ($event.target as HTMLInputElement).checked)" />
    </label>
    <details>
      <summary class="hint">完整 JSON</summary>
      <textarea v-model="text" rows="10" style="width: 100%; font-family: monospace" />
    </details>
    <div v-if="parseError" class="notice">{{ parseError }}</div>
    <div class="actions">
      <button class="primary" :disabled="busy || !!parseError" @click="submit">{{ edited ? "提交修改" : "按原案继续" }}</button>
    </div>
  </section>
</template>
<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { TraceEvent } from "../../api/studio";
const props = defineProps<{ event: TraceEvent; busy: boolean; defaultInstruction?: string }>();
const emit = defineEmits<{ submit: [payload: object] }>();
const text = ref("");
// Keyed on timestamp (part of the interaction key) rather than the whole event object, so a
// poll refresh that replaces `events` with an equal-but-new object does not wipe in-progress edits.
watch(() => props.event.timestamp, () => {
  const content = props.event.content;
  // The research objective typed on the start form pre-fills the agent's first user_instruction request.
  const seeded = props.defaultInstruction && content && typeof content === "object" && "user_instruction" in content
    ? { ...content, user_instruction: content.user_instruction || props.defaultInstruction }
    : content;
  text.value = JSON.stringify(seeded, null, 2);
}, { immediate: true });
const parsed = computed(() => { try { return { value: JSON.parse(text.value), error: "" }; } catch { return { value: null, error: "JSON 格式错误。" }; } });
const parseError = computed(() => parsed.value.error);
const original = computed(() => JSON.stringify(props.event.content, null, 2));
const edited = computed(() => text.value !== original.value);
const stageHint = computed(() => {
  const c = props.event.content || {};
  if ("features" in c) return "基础特征集：agent 会在这些 Qlib 特征之上补充新因子，不改直接继续。";
  if ("user_instruction" in c) return "开始前的总体指示：可留空，agent 会自行选题。";
  if ("hypothesis" in c) return "这一轮 agent 提出的假设：认可就直接继续，也可以改写后提交。";
  if ("decision" in c) return "这一轮的评估结论：不同意 agent 的判断可以在这里改。";
  return "不改直接提交即按 agent 的原案继续。";
});
const labels: Record<string, string> = { user_instruction: "研究方向", hypothesis: "研究假设", reason: "依据与反馈", decision: "评估决定" };
const fields = computed(() => {
  const data = parsed.value.value;
  if (!data || typeof data !== "object") return [];
  return Object.keys(labels).filter((k) => k in data).map((k) => ({ key: k, label: labels[k], value: data[k] }));
});
function update(key: string, value: unknown) {
  const data = parsed.value.value;
  if (!data) return;
  data[key] = value;
  text.value = JSON.stringify(data, null, 2);
}
function submit() {
  const data = parsed.value.value;
  if (!data || typeof data !== "object" || Array.isArray(data)) return;
  // The native feature-selection request expects only the feature dictionary back.
  emit("submit", "features" in props.event.content && data.features ? data.features : data);
}
</script>
