<script setup lang="ts">
import { nextTick, onUnmounted, ref, watch } from 'vue'
import { Close } from '@element-plus/icons-vue'
import SettingsPanel from './SettingsPanel.vue'

const open = defineModel<boolean>('open', { default: false })

const dialogEl = ref<HTMLElement | null>(null)

function close() {
  open.value = false
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.preventDefault()
    close()
  }
}

watch(open, async (isOpen) => {
  if (isOpen) {
    document.addEventListener('keydown', onKeydown)
    await nextTick()
    dialogEl.value?.focus()
  } else {
    document.removeEventListener('keydown', onKeydown)
  }
})

onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="settings-overlay"
      @click.self="close"
    >
      <div
        ref="dialogEl"
        class="settings-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-dialog-title"
        tabindex="-1"
      >
        <header class="settings-head">
          <h1 id="settings-dialog-title">系统设置</h1>
          <button type="button" class="settings-x" aria-label="关闭" @click="close">
            <el-icon :size="18"><Close /></el-icon>
          </button>
        </header>
        <SettingsPanel @close="close" />
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.settings-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--spacing-16);
  background: color-mix(in srgb, var(--color-ink) 55%, transparent);
}

.settings-dialog {
  width: min(920px, 100%);
  height: min(86vh, 640px);
  max-height: min(86vh, 720px);
  display: flex;
  flex-direction: column;
  background: var(--color-white);
  border-radius: 0;
  border: 4px solid var(--color-ink);
  box-shadow: 12px 12px 0 var(--color-mint);
  overflow: hidden;
  outline: none;
  transform: rotate(-1deg);
}

.settings-dialog :deep(.panel-body) {
  flex: 1;
  min-height: 0;
}

.settings-head {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--spacing-16) var(--spacing-24);
  border-bottom: 4px solid var(--color-ink);
  background: var(--color-sunny);
}

.settings-head h1 {
  margin: 0;
  font-family: var(--font-ui);
  font-size: var(--text-subheading);
  font-weight: var(--font-weight-black);
  letter-spacing: -0.02em;
  line-height: 1;
  color: var(--color-ink);
}

.settings-x {
  appearance: none;
  border: 4px solid var(--color-ink);
  background: var(--color-white);
  width: 2.25rem;
  height: 2.25rem;
  border-radius: 0;
  font-size: 1.35rem;
  line-height: 1;
  color: var(--color-ink);
  cursor: pointer;
  display: grid;
  place-items: center;
  box-shadow: 3px 3px 0 var(--color-coral);
  font-weight: var(--font-weight-black);
  transition:
    transform var(--duration-spring) var(--ease-spring),
    box-shadow var(--duration-spring) var(--ease-spring);
}

.settings-x:hover {
  background: var(--color-coral);
  color: var(--color-white);
  transform: translateY(-2px) rotate(3deg);
  box-shadow: 5px 5px 0 var(--color-ink);
}

@media (max-width: 720px) {
  .settings-overlay {
    padding: 0.5rem;
  }
  .settings-dialog {
    width: 100%;
    height: min(94vh, 640px);
    max-height: 94vh;
    border-radius: 0;
    transform: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .settings-dialog,
  .settings-x:hover {
    transform: none;
  }
}
</style>
