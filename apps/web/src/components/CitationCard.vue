<script setup lang="ts">
import type { Citation } from '../types/citation'

defineProps<{ citation: Citation }>()
</script>

<template>
  <div class="cite">
    <div class="cite-head">
      <strong>{{ citation.law_name }} {{ citation.article_no }}</strong>
      <span v-if="citation.category" class="meta">{{ citation.category }}</span>
      <span v-if="citation.effective_date" class="meta">{{ citation.effective_date }}</span>
    </div>
    <p class="cite-text">{{ citation.text }}</p>
    <div class="cite-id">source_id: {{ citation.source_id }}</div>
  </div>
</template>

<style scoped>
.cite {
  background: #fff8e8;
  border-left: 3px solid #c2a05e;
  padding: 8px 10px;
  font-size: 0.85rem;
  max-width: 640px;
}
.cite-head {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
  align-items: baseline;
}
.meta {
  color: #8a7350;
  font-size: 0.75rem;
}
.cite-text {
  margin: 4px 0 0;
  color: #444;
  white-space: pre-wrap;
}
.cite-id {
  margin-top: 4px;
  font-size: 0.7rem;
  color: #999;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
</style>
