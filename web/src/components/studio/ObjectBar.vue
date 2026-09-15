<template>
  <header class="object-bar">
    <div class="ob-main">
      <h1 :title="title">{{ title }}</h1>
      <div class="ob-desc" v-if="description" :title="description">{{ description }}</div>
    </div>
    <slot />
    <span v-if="tag" class="ob-tag">{{ tag }}</span>
  </header>
</template>
<script setup lang="ts">
defineProps<{ title: string; description?: string; tag?: string }>();
</script>
