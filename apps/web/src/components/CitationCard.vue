<script setup lang="ts">
import { CollectionTag } from '@element-plus/icons-vue'
import type { Citation } from '../types/citation'

defineProps<{ citation: Citation }>()
</script>

<template>
  <div class="cite-panel">
    <div class="cite-head">
      <span class="cite-label">
        <el-icon :size="14"><CollectionTag /></el-icon>
        知识点
      </span>
      <strong>{{ citation.law_name }}</strong>
      <span v-if="citation.article_no" class="meta">分类：{{ citation.article_no }}</span>
      <span v-else-if="citation.category" class="meta">分类：{{ citation.category }}</span>
    </div>
    <p class="cite-text">{{ citation.text }}</p>
    <div class="cite-id">{{ citation.source_id }}</div>
  </div>
</template>

<style scoped>
.cite-panel {
  background: var(--color-white);
  border: 4px solid var(--color-ink);
  padding: 14px 16px;
  font-size: var(--text-label);
  font-weight: var(--font-weight-bold);
  border-radius: 0;
  box-shadow: 6px 6px 0 var(--color-mint);
  transform: rotate(-1deg);
  transition:
    transform var(--duration-spring) var(--ease-spring),
    box-shadow var(--duration-spring) var(--ease-spring);
}

.cite-panel:hover {
  transform: translateY(-6px) rotate(1deg);
  box-shadow: 10px 10px 0 var(--color-coral);
}

.cite-head {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  align-items: center;
  font-family: var(--font-ui);
  color: var(--color-ink);
}

.cite-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: var(--font-weight-bold);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  background: var(--color-sunny);
  border: 2px solid var(--color-ink);
  padding: 2px 8px;
}

.meta {
  color: var(--color-ink);
  font-size: 12px;
  background: var(--color-seafoam);
  border: 2px solid var(--color-ink);
  padding: 2px 8px;
}

.cite-text {
  margin: 10px 0 0;
  color: var(--color-ink);
  white-space: pre-wrap;
  line-height: 1.5;
}

.cite-id {
  margin-top: 10px;
  font-size: 11px;
  color: var(--color-ink);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  border-top: 2px solid var(--color-ink);
  padding-top: 8px;
}

@media (prefers-reduced-motion: reduce) {
  .cite-panel,
  .cite-panel:hover {
    transform: none;
  }
}
</style>
