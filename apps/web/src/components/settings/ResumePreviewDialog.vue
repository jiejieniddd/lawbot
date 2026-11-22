<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { Close } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useResumeStore } from '../../stores/resume'

const resumeStore = useResumeStore()
const dialogEl = ref<HTMLElement | null>(null)
const downloading = ref(false)

const title = computed(() => resumeStore.previewRecord?.filename || '简历预览')

const structuredLines = computed(() => {
  const s = resumeStore.previewRecord?.structured
  if (!s || typeof s !== 'object') return [] as string[]
  return Object.entries(s)
    .slice(0, 12)
    .map(([k, v]) => {
      const val = Array.isArray(v) ? v.join('、') : typeof v === 'object' ? JSON.stringify(v) : String(v ?? '')
      return `${k}：${val}`
    })
})

function close() {
  resumeStore.closePreview()
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.preventDefault()
    close()
  }
}

async function onDownload() {
  downloading.value = true
  try {
    await resumeStore.downloadActiveFile(resumeStore.previewRecord)
  } catch (e) {
    ElMessage.error((e as Error).message || '下载失败')
  } finally {
    downloading.value = false
  }
}

watch(
  () => resumeStore.previewOpen,
  async (isOpen) => {
    if (isOpen) {
      document.addEventListener('keydown', onKeydown)
      await nextTick()
      dialogEl.value?.focus()
    } else {
      document.removeEventListener('keydown', onKeydown)
    }
  },
)

onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="resumeStore.previewOpen"
      class="preview-overlay"
      @click.self="close"
    >
      <div
        ref="dialogEl"
        class="preview-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="resume-preview-title"
        tabindex="-1"
      >
        <header class="preview-head">
          <h1 id="resume-preview-title">{{ title }}</h1>
          <button type="button" class="preview-x" aria-label="关闭" @click="close">
            <el-icon :size="18"><Close /></el-icon>
          </button>
        </header>

        <div class="preview-body">
          <div v-if="resumeStore.previewLoading" class="preview-state">加载中…</div>
          <div v-else-if="resumeStore.previewError" class="preview-state error">
            {{ resumeStore.previewError }}
          </div>

          <template v-else-if="resumeStore.previewKind === 'pdf' && resumeStore.previewUrl">
            <iframe
              class="preview-frame"
              :src="resumeStore.previewUrl"
              title="PDF 预览"
            />
          </template>

          <template v-else-if="resumeStore.previewKind === 'png' && resumeStore.previewUrl">
            <div class="preview-img-wrap">
              <img :src="resumeStore.previewUrl" alt="简历图片预览" class="preview-img" />
            </div>
          </template>

          <template v-else>
            <div class="preview-docx">
              <p class="docx-note">
                浏览器无法直接预览 Word（DOCX）文件。可下载原文件，或查看下方已解析摘要。
              </p>
              <dl class="docx-meta">
                <div>
                  <dt>文件名</dt>
                  <dd>{{ resumeStore.previewRecord?.filename || '—' }}</dd>
                </div>
                <div>
                  <dt>解析状态</dt>
                  <dd>{{ resumeStore.previewRecord?.parse_status || '—' }}</dd>
                </div>
                <div>
                  <dt>意图</dt>
                  <dd>{{ resumeStore.previewRecord?.intent || '—' }}</dd>
                </div>
                <div v-if="resumeStore.previewRecord?.skills?.length">
                  <dt>技能</dt>
                  <dd>{{ resumeStore.previewRecord.skills.join(' · ') }}</dd>
                </div>
                <div v-if="structuredLines.length">
                  <dt>结构化摘要</dt>
                  <dd>
                    <ul>
                      <li v-for="(line, i) in structuredLines" :key="i">{{ line }}</li>
                    </ul>
                  </dd>
                </div>
              </dl>
              <el-button type="primary" :loading="downloading" @click="onDownload">
                下载原文件
              </el-button>
            </div>
          </template>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.preview-overlay {
  position: fixed;
  inset: 0;
  z-index: 1100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--spacing-16);
  background: color-mix(in srgb, var(--color-ink) 55%, transparent);
}

.preview-dialog {
  width: min(920px, 100%);
  height: min(88vh, 720px);
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  background: var(--color-white);
  border: 4px solid var(--color-ink);
  box-shadow: 12px 12px 0 var(--color-mint);
  overflow: hidden;
  outline: none;
  transform: rotate(-0.5deg);
}

.preview-head {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: var(--spacing-16) var(--spacing-24);
  border-bottom: 4px solid var(--color-ink);
  background: var(--color-sunny);
}

.preview-head h1 {
  margin: 0;
  font-family: var(--font-ui);
  font-size: var(--text-subheading);
  font-weight: var(--font-weight-black);
  color: var(--color-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-x {
  appearance: none;
  flex-shrink: 0;
  border: 4px solid var(--color-ink);
  background: var(--color-white);
  width: 2.25rem;
  height: 2.25rem;
  color: var(--color-ink);
  cursor: pointer;
  display: grid;
  place-items: center;
  box-shadow: 3px 3px 0 var(--color-coral);
  font-weight: var(--font-weight-black);
}

.preview-x:hover {
  background: var(--color-coral);
  color: var(--color-white);
  transform: translateY(-2px) rotate(3deg);
}

.preview-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--color-white);
}

.preview-state {
  padding: 32px;
  font-weight: var(--font-weight-bold);
  color: var(--color-ink);
}

.preview-state.error {
  color: var(--color-peach);
}

.preview-frame {
  flex: 1;
  width: 100%;
  border: 0;
  background: var(--color-white);
}

.preview-img-wrap {
  flex: 1;
  overflow: auto;
  display: grid;
  place-items: center;
  padding: 16px;
}

.preview-img {
  max-width: 100%;
  height: auto;
  border: 3px solid var(--color-ink);
  box-shadow: 6px 6px 0 var(--color-mint);
}

.preview-docx {
  padding: 24px;
  overflow: auto;
  color: var(--color-ink);
}

.docx-note {
  margin: 0 0 16px;
  font-weight: var(--font-weight-bold);
  line-height: 1.5;
}

.docx-meta {
  margin: 0 0 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.docx-meta dt {
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  opacity: 0.7;
  margin-bottom: 4px;
}

.docx-meta dd {
  margin: 0;
  font-weight: var(--font-weight-bold);
}

.docx-meta ul {
  margin: 0;
  padding-left: 1.2em;
}

@media (max-width: 720px) {
  .preview-dialog {
    width: 100%;
    height: min(94vh, 720px);
    transform: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .preview-dialog,
  .preview-x:hover {
    transform: none;
  }
}
</style>
