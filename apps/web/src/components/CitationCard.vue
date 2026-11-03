<script setup lang="ts">
import type { Citation } from '../types/citation'

defineProps<{ citation: Citation }>()
</script>

<template>
  <div class="cite-panel">
    <div class="cite-head">
      <strong>{{ citation.law_name }} {{ citation.article_no }}</strong>
      <span v-if="citation.category" class="meta">{{ citation.category }}</span>
      <span v-if="citation.effective_date" class="meta">{{ citation.effective_date }}</span>
    </div>
    <p class="cite-text">{{ citation.text }}</p>
    <div class="cite-id">{{ citation.source_id }}</div>
  </div>
</template>

<style scoped>
.cite-panel {
  background: var(--info-soft);
  border: 1px solid color-mix(in srgb, var(--color-info) 35%, var(--border));
  border-left: 3px solid var(--color-info);
  padding: 0.55rem 0.7rem;
  font-size: var(--fs-small);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}

.cite-head {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 0.65rem;
  align-items: baseline;
  font-family: var(--font-ui);
  color: var(--text);
}

.meta {
  color: var(--muted);
  font-size: var(--fs-fine);
}

.cite-text {
  margin: 0.3rem 0 0;
  color: var(--text);
  white-space: pre-wrap;
  line-height: 1.45;
}

.cite-id {
  margin-top: 0.3rem;
  font-size: 0.7rem;
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
</style>
