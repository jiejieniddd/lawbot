<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ChatDotRound, Close, Delete, Document, Paperclip, Promotion, Setting } from '@element-plus/icons-vue'
import { api, streamChat, type ChatEvent, type Citation } from '../api/client'
import ResumePreviewDialog from '../components/settings/ResumePreviewDialog.vue'
import SettingsModal from '../components/settings/SettingsModal.vue'
import PixelToggle from '../components/theme/PixelToggle.vue'
import { CAREER_DISCLAIMER } from '../constants/disclaimer'
import { useAuthStore } from '../stores/auth'
import { useResumeStore } from '../stores/resume'
import { useThemeStore } from '../stores/theme'
import { renderMarkdown } from '../utils/markdown'
import {
  RESUME_ACCEPT,
  formatResumeUploadMessage,
  validateResumeFile,
} from '../utils/resumeFile'

type Conversation = { id: string; title: string; status: string }
type Message = {
  id?: string
  role: string
  content: string
  citations?: Citation[]
}

const auth = useAuthStore()
const resumeStore = useResumeStore()
const themeStore = useThemeStore()
const route = useRoute()
const router = useRouter()

const conversations = ref<Conversation[]>([])
const messages = ref<Message[]>([])
const input = ref('')
const sending = ref(false)
/** Conversation id currently streaming; used to skip empty GET /messages overwrites. */
const streamingConvId = ref('')
const loadingList = ref(false)
const loadingMessages = ref(false)
const deletingId = ref('')
const streamingText = ref('')
const streamStatus = ref('正在检索…')
const showStreamStatus = ref(true)
const disclaimer = CAREER_DISCLAIMER
const messagesEl = ref<HTMLElement | null>(null)
const messagesEndEl = ref<HTMLElement | null>(null)
const railOpen = ref(false)
const settingsOpen = ref(false)
const resumeFileInput = ref<HTMLInputElement | null>(null)
const removingResume = ref(false)

const resumeAttachLabel = computed(() => {
  const row = resumeStore.active
  if (!row) return ''
  return row.filename || resumeStore.badgeLabel
})

/** Idle watchdog: align with backend LLM_STREAM_IDLE_SECONDS (120s) + buffer. */
const STREAM_IDLE_MS = 180_000

const activeId = computed(() => (route.params.id as string) || '')
const isStreaming = computed(() => sending.value)
const displayLabel = computed(
  () => auth.user?.display_name?.trim() || auth.user?.email || '',
)
const avatarSrc = computed(() => auth.user?.avatar_url || '')
const avatarInitial = computed(() => {
  const label = displayLabel.value || '?'
  return label.slice(0, 1).toUpperCase()
})

function scrollToBottom() {
  void nextTick(() => {
    const box = messagesEl.value
    if (box) {
      box.scrollTop = box.scrollHeight
      return
    }
    messagesEndEl.value?.scrollIntoView({ block: 'end' })
  })
}

function openConversation(id: string) {
  railOpen.value = false
  router.push(`/chat/${id}`)
}

async function loadConversations() {
  loadingList.value = true
  try {
    conversations.value = await api<Conversation[]>('/api/v1/conversations')
  } catch (e) {
    ElMessage.error((e as Error).message || '加载会话失败')
  } finally {
    loadingList.value = false
  }
}

async function loadMessages(id: string) {
  // First-send race: route watch must not replace optimistic user bubble with [].
  if (sending.value && streamingConvId.value === id) return
  loadingMessages.value = true
  try {
    messages.value = await api<Message[]>(`/api/v1/conversations/${id}/messages`)
    scrollToBottom()
  } catch (e) {
    ElMessage.error((e as Error).message || '加载消息失败')
    messages.value = []
  } finally {
    loadingMessages.value = false
  }
}

async function createConversation() {
  try {
    const conv = await api<Conversation>('/api/v1/conversations', {
      method: 'POST',
      body: JSON.stringify({}),
    })
    await loadConversations()
    railOpen.value = false
    router.push(`/chat/${conv.id}`)
  } catch (e) {
    ElMessage.error((e as Error).message || '创建会话失败')
  }
}

function chineseErrorMessage(err: unknown, fallback: string): string {
  let raw = ''
  if (typeof err === 'string') raw = err.trim()
  else if (err && typeof err === 'object' && 'message' in err) {
    raw = String((err as { message: unknown }).message || '').trim()
  }
  if (!raw) return fallback
  // fetch/abort noise from Chrome etc. — never surface English network strings
  if (
    /failed to fetch|networkerror|load failed|aborted|bodystreambuffer|the user aborted/i.test(
      raw,
    )
  ) {
    return fallback
  }
  if (/internal server error|request failed|^error$/i.test(raw) && !/[\u4e00-\u9fff]/.test(raw)) {
    return fallback
  }
  return raw
}

async function deleteConversation(id: string, e?: Event) {
  e?.stopPropagation()
  if (deletingId.value) return
  try {
    await ElMessageBox.confirm('删除后无法恢复', '确定删除该会话？', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger cb-msgbox-danger',
    })
  } catch {
    return
  }
  deletingId.value = id
  try {
    await api(`/api/v1/conversations/${id}`, { method: 'DELETE' })
    conversations.value = conversations.value.filter((c) => c.id !== id)
    ElMessage.success('已删除')
    if (activeId.value === id) {
      messages.value = []
      streamingText.value = ''
      await router.push('/chat')
    }
  } catch (err) {
    ElMessage.error(chineseErrorMessage(err, '删除失败'))
  } finally {
    deletingId.value = ''
  }
}

function onComposerKeydown(e: KeyboardEvent) {
  if (e.isComposing || e.keyCode === 229) return
  if (e.key !== 'Enter') return
  if (e.shiftKey) return
  // Enter or Ctrl/Cmd+Enter → send; Shift+Enter keeps newline
  e.preventDefault()
  void send()
}

async function send() {
  if (!input.value.trim() || sending.value) return
  const content = input.value.trim()
  let cid = activeId.value
  let needNavigate = false
  if (!cid) {
    try {
      const conv = await api<Conversation>('/api/v1/conversations', {
        method: 'POST',
        body: JSON.stringify({}),
      })
      cid = conv.id
      needNavigate = true
      await loadConversations()
    } catch (e) {
      ElMessage.error((e as Error).message || '创建会话失败')
      return
    }
  }

  input.value = ''
  // Optimistic user bubble before route replace so watch cannot wipe with [].
  messages.value.push({ role: 'user', content })
  sending.value = true
  streamingConvId.value = cid
  streamingText.value = ''
  streamStatus.value = '正在检索…'
  showStreamStatus.value = true
  scrollToBottom()

  if (needNavigate) {
    void router.replace(`/chat/${cid}`)
  }

  const controller = new AbortController()
  let idleTimer: ReturnType<typeof setTimeout> | null = null
  const clearIdle = () => {
    if (idleTimer != null) {
      clearTimeout(idleTimer)
      idleTimer = null
    }
  }
  const bumpIdle = () => {
    clearIdle()
    idleTimer = setTimeout(() => {
      controller.abort()
    }, STREAM_IDLE_MS)
  }
  bumpIdle()

  try {
    await streamChat(
      cid,
      content,
      (ev: ChatEvent) => {
        bumpIdle()
        if (ev.type === 'status') {
          const msg = String(ev.data.message || '').trim()
          if (msg) streamStatus.value = msg
        } else if (ev.type === 'token') {
          showStreamStatus.value = false
          streamingText.value += String(ev.data.text || '')
          scrollToBottom()
        } else if (ev.type === 'citation') {
          // Backend may still emit citations for RAG; UI no longer displays them.
        } else if (ev.type === 'done') {
          messages.value.push({
            id: String(ev.data.message_id || ''),
            role: 'assistant',
            content: streamingText.value,
          })
          streamingText.value = ''
          showStreamStatus.value = false
          scrollToBottom()
          void loadConversations()
        } else if (ev.type === 'error') {
          ElMessage.error(chineseErrorMessage(ev.data.message, '生成失败，请稍后重试'))
          streamingText.value = ''
          showStreamStatus.value = false
        }
      },
      { signal: controller.signal },
    )
  } catch (e) {
    const aborted = controller.signal.aborted
    const partial = streamingText.value.trim()
    if (partial) {
      messages.value.push({
        role: 'assistant',
        content: streamingText.value,
      })
      ElMessage.warning('生成超时，内容可能不完整')
      streamingText.value = ''
      showStreamStatus.value = false
      scrollToBottom()
    } else {
      // Prefer explicit Chinese for abort/network; never toast raw "Failed to fetch".
      ElMessage.error(
        aborted
          ? '生成超时，请稍后重试'
          : chineseErrorMessage(e, '生成失败，请稍后重试'),
      )
      streamingText.value = ''
      showStreamStatus.value = false
    }
  } finally {
    clearIdle()
    sending.value = false
    streamingConvId.value = ''
  }
}

async function logout() {
  await auth.logout()
  router.push('/login')
}

function openResumePicker() {
  if (resumeStore.uploading || removingResume.value) return
  resumeFileInput.value?.click()
}

async function onResumeFileChange(e: Event) {
  const inputEl = e.target as HTMLInputElement
  const file = inputEl.files?.[0]
  inputEl.value = ''
  if (!file) return

  const err = validateResumeFile(file)
  if (err) {
    ElMessage.error(err)
    return
  }

  try {
    const row = await resumeStore.upload(file)
    const toast = formatResumeUploadMessage(row)
    if (toast.type === 'warning') ElMessage.warning(toast.message)
    else ElMessage.success(toast.message)
  } catch (err) {
    ElMessage.error((err as Error).message || '简历上传失败')
  }
}

async function removeActiveResume() {
  const id = resumeStore.active?.id
  if (!id || removingResume.value || resumeStore.uploading) return
  removingResume.value = true
  try {
    await resumeStore.remove(id)
    ElMessage.success('已删除当前简历')
  } catch (err) {
    ElMessage.error((err as Error).message || '删除失败')
  } finally {
    removingResume.value = false
  }
}

onMounted(async () => {
  try {
    await auth.fetchMe()
    await resumeStore.fetchActive().catch(() => undefined)
  } catch (e) {
    ElMessage.error((e as Error).message || '获取用户信息失败')
  }
  await loadConversations()
  if (activeId.value) await loadMessages(activeId.value)
})

watch(
  () => route.params.id,
  async (id) => {
    if (!id) {
      messages.value = []
      return
    }
    // Streaming into this conversation: keep optimistic local messages.
    if (sending.value && streamingConvId.value === id) return
    await loadMessages(id as string)
  },
)

watch(
  () => route.query.settings,
  (value) => {
    if (value === '1' || value === 'true') {
      settingsOpen.value = true
      const nextQuery = { ...route.query }
      delete nextQuery.settings
      void router.replace({ path: route.path, query: nextQuery })
    }
  },
  { immediate: true },
)
</script>

<template>
  <div class="workbench" :class="{ 'rail-open': railOpen }">
    <div v-if="railOpen" class="rail-backdrop" @click="railOpen = false" />
    <aside class="rail">
      <div class="rail-chrome">
        <div class="rail-brand">
          <span class="brand-text">CareerBot</span>
          <span class="brand-badge" aria-hidden="true" />
        </div>
        <nav class="rail-nav">
          <router-link class="nav-link active" to="/chat">求职助手</router-link>
          <router-link class="nav-link" to="/interview">模拟面试</router-link>
        </nav>
        <el-button type="primary" class="new-chat" @click="createConversation">新咨询</el-button>
      </div>
      <div v-loading="loadingList" class="session-list">
        <p v-if="!loadingList && conversations.length === 0" class="empty-hint">
          暂无会话，点击「新咨询」开始
        </p>
        <div
          v-for="c in conversations"
          :key="c.id"
          class="session"
          :class="{ active: c.id === activeId }"
        >
          <button type="button" class="session-open" @click="openConversation(c.id)">
            <el-icon class="session-icon" :size="14"><ChatDotRound /></el-icon>
            <span class="session-title">{{ c.title }}</span>
          </button>
          <button
            type="button"
            class="session-delete"
            :disabled="deletingId === c.id"
            :aria-label="`删除会话 ${c.title}`"
            @click="deleteConversation(c.id, $event)"
          >
            <el-icon :size="14"><Delete /></el-icon>
          </button>
        </div>
      </div>
      <div class="rail-foot rail-chrome">
        <div class="identity">
          <div class="avatar" aria-hidden="true">
            <img v-if="avatarSrc" :src="avatarSrc" alt="" />
            <span v-else>{{ avatarInitial }}</span>
          </div>
          <div class="identity-text">
            <div class="name">{{ displayLabel }}</div>
            <button type="button" class="profile-link" @click="settingsOpen = true">
              <el-icon :size="14"><Setting /></el-icon>
              设置
            </button>
          </div>
        </div>
        <el-button text type="danger" @click="logout">退出</el-button>
      </div>
    </aside>

    <section class="stage">
      <header class="stage-bar">
        <button type="button" class="rail-toggle" aria-label="会话列表" @click="railOpen = !railOpen">
          会话
        </button>
        <h1 class="stage-title">求职助手</h1>
        <button
          v-if="resumeStore.badgeLabel"
          type="button"
          class="resume-chip"
          title="查看当前简历"
          @click="resumeStore.openPreview()"
        >
          <el-icon :size="14"><Document /></el-icon>
          {{ resumeStore.badgeLabel }}
        </button>
        <div class="stage-bar-actions">
          <PixelToggle
            :checked="themeStore.isLight"
            :height="28"
            :sound="true"
            @update:checked="themeStore.setLight"
          />
          <button type="button" class="stage-user" @click="settingsOpen = true">
            <span class="avatar sm" aria-hidden="true">
              <img v-if="avatarSrc" :src="avatarSrc" alt="" />
              <span v-else>{{ avatarInitial }}</span>
            </span>
            {{ displayLabel }}
          </button>
        </div>
      </header>

      <div ref="messagesEl" v-loading="loadingMessages" class="thread-scroll">
        <div class="thread">
          <div v-if="!loadingMessages && !messages.length && !isStreaming" class="thread-empty">
            <div class="sticker-cluster" aria-hidden="true">
              <span class="sticker coral" />
              <span class="sticker mint" />
              <span class="sticker sunny" />
              <span class="sticker round seafoam" />
            </div>
            <p class="empty-title">发一条，开聊</p>
            <p class="empty-sub">用大白话说说你遇到的事</p>
          </div>
          <article v-for="(m, i) in messages" :key="m.id || i" class="turn" :class="m.role">
            <div
              v-if="m.role === 'assistant'"
              class="speech assistant md-body"
              v-html="renderMarkdown(m.content)"
            />
            <div v-else class="speech user">{{ m.content }}</div>
          </article>
          <article v-if="isStreaming" class="turn assistant">
            <div
              v-if="streamingText"
              class="speech assistant md-body"
              v-html="renderMarkdown(streamingText)"
            />
            <div v-if="showStreamStatus || !streamingText" class="stream-live" aria-live="polite">
              <span class="stream-dot" />
              {{ streamStatus }}
            </div>
          </article>
          <div ref="messagesEndEl" class="thread-end" aria-hidden="true" />
        </div>
      </div>

      <div class="composer-dock">
        <div class="composer-shell">
          <el-input
            v-model="input"
            class="composer-input"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 5 }"
            :disabled="sending"
            placeholder="用大白话说说你遇到的事…"
            @keydown="onComposerKeydown"
          />
          <div class="composer-toolbar">
            <div class="composer-toolbar-left">
              <input
                ref="resumeFileInput"
                class="resume-file-input"
                type="file"
                :accept="RESUME_ACCEPT"
                tabindex="-1"
                @change="onResumeFileChange"
              />
              <button
                type="button"
                class="attach-btn"
                :disabled="resumeStore.uploading || removingResume"
                :aria-label="resumeStore.uploading ? '简历上传中' : '上传简历'"
                :title="resumeStore.uploading ? '解析中…' : '上传简历（PDF / DOCX / PNG）'"
                @click="openResumePicker"
              >
                <el-icon :size="18"><Paperclip /></el-icon>
              </button>
              <div v-if="resumeStore.active" class="resume-attach-chip">
                <el-icon class="resume-attach-icon" :size="14"><Document /></el-icon>
                <span class="resume-attach-text" :title="resumeStore.badgeLabel || resumeAttachLabel">
                  {{ resumeAttachLabel }}
                </span>
                <button
                  type="button"
                  class="resume-attach-remove"
                  :disabled="resumeStore.uploading || removingResume"
                  aria-label="移除当前简历"
                  @click="removeActiveResume"
                >
                  <el-icon :size="12"><Close /></el-icon>
                </button>
              </div>
              <span v-else-if="resumeStore.uploading" class="resume-attach-hint">解析中…</span>
            </div>
            <el-button
              class="composer-send"
              type="primary"
              :loading="sending"
              :disabled="sending || !input.trim()"
              aria-label="发送"
              @click="send"
            >
              <el-icon v-if="!sending"><Promotion /></el-icon>
              <span v-if="!sending">发送</span>
            </el-button>
          </div>
        </div>
        <p class="disclaimer" :title="disclaimer">{{ disclaimer }}</p>
        <p class="source-credit">
          岗位资料含
          <a href="https://www.onetcenter.org/database.html" target="_blank" rel="noopener noreferrer">O*NET 31.0 Database</a>
          （美国劳工部，<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener noreferrer">CC BY 4.0</a>）；中文岗位别名由 CareerBot 添加。
        </p>
      </div>
    </section>
  </div>
  <SettingsModal v-model:open="settingsOpen" />
  <ResumePreviewDialog />
</template>

<style scoped>
.workbench {
  display: grid;
  grid-template-columns: var(--space-rail) 1fr;
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
  background: var(--color-white);
}

.rail {
  background: var(--color-white);
  border-right: 4px solid var(--color-ink);
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  padding: var(--spacing-16);
  gap: var(--spacing-16);
  z-index: 20;
}

.rail-chrome {
  flex-shrink: 0;
}

.rail-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: var(--spacing-16);
  transform: rotate(-2deg);
}

.brand-text {
  font-family: var(--font-ui);
  font-weight: var(--font-weight-black);
  font-size: 28px;
  letter-spacing: -0.03em;
  line-height: 1;
  color: var(--color-ink);
}

.brand-badge {
  width: 14px;
  height: 14px;
  background: var(--color-sunny);
  border: 2px solid var(--color-ink);
  flex-shrink: 0;
}

.rail-nav {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 12px;
}

.nav-link {
  border: 3px solid var(--color-ink);
  padding: 8px 10px;
  text-decoration: none;
  color: inherit;
  font-weight: var(--font-weight-bold);
  background: var(--surface);
}

.nav-link.active {
  background: var(--color-sunny);
  box-shadow: 3px 3px 0 var(--color-ink);
}

.new-chat {
  width: 100%;
}

.session-list {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.empty-hint {
  margin: var(--spacing-16) 0;
  color: var(--color-ink);
  font-size: var(--text-label);
  font-weight: var(--font-weight-bold);
  line-height: 1.45;
  border: 2px solid var(--color-ink);
  padding: 12px;
  background: var(--color-sunny);
  box-shadow: 4px 4px 0 var(--color-ink);
  transform: rotate(-1deg);
}

.session {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px;
  border: 2px solid transparent;
  color: var(--color-ink);
  background: var(--color-white);
  transition:
    transform var(--duration-spring) var(--ease-spring),
    box-shadow var(--duration-spring) var(--ease-spring),
    background-color var(--duration-spring) var(--ease-spring);
}

.session:hover {
  background: var(--color-sunny);
  border-color: var(--color-ink);
  box-shadow: 4px 4px 0 var(--color-mint);
  transform: rotate(1deg);
}

.session.active {
  background: var(--color-coral);
  color: var(--color-white);
  border-color: var(--color-ink);
  box-shadow: 4px 4px 0 var(--color-ink);
  transform: rotate(-1deg);
}

.session-open {
  appearance: none;
  border: 0;
  background: transparent;
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  text-align: left;
  padding: 8px;
  cursor: pointer;
  font: inherit;
  font-size: var(--text-label);
  font-weight: var(--font-weight-bold);
  color: inherit;
  line-height: 1.35;
}

.session-icon {
  flex-shrink: 0;
}

.session-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-delete {
  appearance: none;
  border: 2px solid transparent;
  background: transparent;
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  padding: 0;
  display: inline-grid;
  place-items: center;
  cursor: pointer;
  color: inherit;
  opacity: 0.4;
}

.session:hover .session-delete,
.session.active .session-delete {
  opacity: 1;
}

.session-delete:hover:not(:disabled) {
  border-color: var(--color-ink);
  background: var(--color-white);
  color: var(--color-peach);
}

.session-delete:disabled {
  cursor: wait;
  opacity: 0.4;
}

.rail-foot {
  margin-top: auto;
  padding-top: var(--spacing-16);
  border-top: 4px solid var(--color-ink);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-8);
}

.identity {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1;
}

.identity-text {
  min-width: 0;
}

.name {
  font-size: var(--text-label);
  font-weight: var(--font-weight-black);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.profile-link {
  appearance: none;
  border: 0;
  background: transparent;
  padding: 0;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font: inherit;
  font-size: var(--fs-fine);
  font-weight: var(--font-weight-bold);
  color: var(--color-mint);
  cursor: pointer;
  text-align: left;
}

.profile-link:hover {
  color: var(--color-coral);
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 0;
  overflow: hidden;
  flex-shrink: 0;
  background: var(--color-sunny);
  border: 2px solid var(--color-ink);
  color: var(--color-ink);
  font-size: 12px;
  font-weight: var(--font-weight-black);
  display: grid;
  place-items: center;
  box-shadow: 3px 3px 0 var(--color-mint);
}

.avatar.sm {
  width: 28px;
  height: 28px;
  box-shadow: 2px 2px 0 var(--color-coral);
}

.avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.stage {
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
  overflow: hidden;
  background: var(--color-white);
}

.stage-bar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: var(--spacing-16);
  padding: var(--spacing-16) var(--spacing-24);
  border-bottom: 4px solid var(--color-ink);
  background: var(--surface);
}

.stage-bar-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-left: auto;
  flex-shrink: 0;
  max-width: min(280px, 46vw);
}

.rail-toggle {
  display: none;
  appearance: none;
  border: 4px solid var(--color-ink);
  background: var(--color-sunny);
  color: var(--color-ink);
  border-radius: 0;
  padding: 8px 12px;
  font: inherit;
  font-size: var(--text-label);
  font-weight: var(--font-weight-black);
  cursor: pointer;
  box-shadow: 4px 4px 0 var(--color-ink);
  transform: rotate(-2deg);
}

.stage-title {
  margin: 0;
  font-family: var(--font-ui);
  font-size: clamp(24px, 3vw, 40px);
  font-weight: var(--font-weight-black);
  letter-spacing: var(--tracking-heading);
  line-height: 1;
  flex: 1;
  transform: rotate(-1deg);
}

.resume-chip {
  appearance: none;
  border: 2px solid var(--color-ink);
  background: var(--color-sunny);
  color: var(--color-ink);
  border-radius: 0;
  padding: 4px 10px;
  font: inherit;
  font-size: 12px;
  font-weight: var(--font-weight-bold);
  cursor: pointer;
  max-width: 12rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  box-shadow: 3px 3px 0 var(--color-coral);
  transform: rotate(2deg);
  transition:
    transform var(--duration-spring) var(--ease-spring),
    box-shadow var(--duration-spring) var(--ease-spring);
}

.resume-chip.mint {
  background: var(--color-seafoam);
  box-shadow: 3px 3px 0 var(--color-mint);
  transform: rotate(-2deg);
}

.resume-chip:hover {
  transform: translateY(-3px) rotate(3deg);
  box-shadow: 5px 5px 0 var(--color-ink);
}

.stage-user {
  appearance: none;
  border: 2px solid var(--color-ink);
  background: var(--color-white);
  padding: 4px 10px 4px 4px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--color-ink);
  font: inherit;
  font-size: var(--text-label);
  font-weight: var(--font-weight-bold);
  cursor: pointer;
  box-shadow: 3px 3px 0 var(--color-mint);
  transform: rotate(1deg);
  transition:
    transform var(--duration-spring) var(--ease-spring),
    box-shadow var(--duration-spring) var(--ease-spring);
}

.stage-user:hover {
  transform: translateY(-3px) rotate(-1deg);
  box-shadow: 5px 5px 0 var(--color-coral);
}

.thread-scroll {
  flex: 1;
  min-height: 0;
  width: 100%;
  overflow: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--color-ink) transparent;
}

.thread-scroll::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

.thread-scroll::-webkit-scrollbar-track,
.thread-scroll::-webkit-scrollbar-track-piece {
  background: transparent;
}

.thread-scroll::-webkit-scrollbar-thumb {
  background: var(--color-ink);
  border-radius: 0;
}

.thread {
  display: flex;
  flex-direction: column;
  gap: var(--element-gap);
  padding: var(--spacing-24);
  max-width: min(880px, var(--page-max-width));
  width: 100%;
  margin: 0 auto;
  box-sizing: border-box;
}

.thread-empty {
  margin: var(--spacing-64) auto;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-16);
}

.sticker-cluster {
  display: flex;
  gap: 8px;
  align-items: center;
  transform: rotate(-3deg);
  margin-bottom: 8px;
}

.sticker {
  width: 20px;
  height: 20px;
  border: 2px solid var(--color-ink);
}

.sticker.round {
  border-radius: 50%;
  width: 16px;
  height: 16px;
}

.sticker.coral {
  background: var(--color-coral);
}

.sticker.mint {
  background: var(--color-mint);
}

.sticker.sunny {
  background: var(--color-sunny);
}

.sticker.seafoam {
  background: var(--color-seafoam);
}

.empty-title {
  margin: 0;
  font-size: clamp(28px, 5vw, 56px);
  font-weight: var(--font-weight-black);
  line-height: 1;
  letter-spacing: var(--tracking-display);
  transform: rotate(-2deg);
}

.empty-sub {
  margin: 0;
  font-size: var(--text-body);
  font-weight: var(--font-weight-bold);
  border: 2px solid var(--color-ink);
  padding: 8px 12px;
  background: var(--color-seafoam);
  box-shadow: 4px 4px 0 var(--color-ink);
  transform: rotate(1deg);
}

.thread-end {
  height: 1px;
  width: 100%;
  flex-shrink: 0;
}

.turn {
  display: flex;
  flex-direction: column;
  max-width: 100%;
}

.turn.user {
  align-items: flex-end;
}

.turn.assistant {
  align-items: flex-start;
}

.speech {
  max-width: min(640px, 100%);
  padding: 16px 20px;
  border-radius: 0;
  font-size: var(--text-body);
  font-weight: var(--font-weight-bold);
  line-height: var(--leading-body);
  border: 4px solid var(--color-ink);
}

.speech.user {
  background: var(--color-coral);
  color: var(--color-white);
  white-space: pre-wrap;
  box-shadow: 6px 6px 0 var(--color-ink);
  transform: rotate(1deg);
}

.speech.assistant {
  background: var(--color-white);
  color: var(--color-ink);
  box-shadow: 8px 8px 0 var(--color-mint);
  transform: rotate(-1deg);
}

.speech.md-body {
  white-space: normal;
}

.speech.md-body :deep(h2),
.speech.md-body :deep(h3) {
  margin: 0.75em 0 0.35em;
  font-size: 20px;
  font-weight: var(--font-weight-black);
  line-height: 1.15;
  font-family: var(--font-ui);
}

.speech.md-body :deep(h2:first-child),
.speech.md-body :deep(h3:first-child) {
  margin-top: 0;
}

.speech.md-body :deep(p) {
  margin: 0.4em 0;
}

.speech.md-body :deep(ul),
.speech.md-body :deep(ol) {
  margin: 0.4em 0;
  padding-left: 1.35em;
}

.speech.md-body :deep(li) {
  margin: 0.2em 0;
}

.speech.md-body :deep(blockquote) {
  margin: 0.5em 0;
  padding: 0.5em 0.75em;
  border-left: 4px solid var(--color-ink);
  color: var(--color-ink);
  background: var(--color-sunny);
}

.speech.md-body :deep(strong) {
  font-weight: var(--font-weight-black);
}

.speech.md-body :deep(a) {
  color: var(--color-mint);
  text-decoration: underline;
}

.speech.md-body :deep(code) {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 0.9em;
  padding: 0.1em 0.3em;
  background: var(--color-sunny);
  border: 2px solid var(--color-ink);
  border-radius: 0;
}

.speech.md-body :deep(pre) {
  margin: 0.5em 0;
  padding: 0.75em;
  overflow: auto;
  background: var(--color-seafoam);
  border: 2px solid var(--color-ink);
  border-radius: 0;
}

.speech.md-body :deep(pre code) {
  padding: 0;
  background: transparent;
  border: 0;
}

.stream-live {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  font-size: var(--text-label);
  font-weight: var(--font-weight-bold);
  color: var(--color-ink);
  border: 2px solid var(--color-ink);
  background: var(--color-sunny);
  padding: 6px 10px;
  box-shadow: 3px 3px 0 var(--color-ink);
  transform: rotate(-1deg);
}

.stream-dot {
  width: 10px;
  height: 10px;
  border-radius: 0;
  background: var(--color-mint);
  border: 2px solid var(--color-ink);
  animation: pulse 1s ease-in-out infinite;
}

@keyframes pulse {
  0%,
  100% {
    opacity: 0.35;
  }
  50% {
    opacity: 1;
  }
}

.composer-dock {
  flex-shrink: 0;
  background: transparent;
  padding: 0 var(--spacing-24) var(--spacing-16);
  max-width: min(880px, var(--page-max-width));
  width: 100%;
  margin: 0 auto;
  box-sizing: border-box;
}

.composer-shell {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 16px;
  background: var(--color-white);
  border: 4px solid var(--color-ink);
  border-radius: 0;
  box-shadow: 8px 8px 0 var(--color-mint);
  transform: rotate(-1deg);
  transition:
    transform var(--duration-spring) var(--ease-spring),
    box-shadow var(--duration-spring) var(--ease-spring);
}

.composer-shell:focus-within {
  transform: translateY(-4px) rotate(0deg);
  box-shadow: 10px 10px 0 var(--color-coral);
}

.composer-input {
  width: 100%;
  min-width: 0;
}

.composer-input :deep(.el-textarea__inner) {
  border: 0 !important;
  box-shadow: none !important;
  background: transparent !important;
  padding: 4px 0 !important;
  resize: none;
  font-size: var(--text-body);
  font-weight: var(--font-weight-bold);
  line-height: 1.45;
  color: var(--color-ink);
}

.composer-input :deep(.el-textarea__inner:focus) {
  box-shadow: none !important;
}

.composer-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 40px;
}

.composer-toolbar-left {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.resume-file-input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  pointer-events: none;
}

.attach-btn {
  appearance: none;
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  padding: 0;
  display: inline-grid;
  place-items: center;
  border: 2px solid var(--color-ink);
  border-radius: 0;
  background: var(--color-white);
  color: var(--color-ink);
  cursor: pointer;
  box-shadow: 3px 3px 0 var(--color-mint);
  transform: rotate(-2deg);
  transition:
    transform var(--duration-spring) var(--ease-spring),
    box-shadow var(--duration-spring) var(--ease-spring),
    background-color var(--duration-spring) var(--ease-spring);
}

.attach-btn:hover:not(:disabled) {
  background: var(--color-sunny);
  transform: translateY(-3px) rotate(2deg);
  box-shadow: 5px 5px 0 var(--color-coral);
}

.attach-btn:disabled {
  opacity: 0.55;
  cursor: wait;
  transform: none;
}

.resume-attach-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  max-width: min(220px, 48vw);
  padding: 4px 6px 4px 8px;
  border: 2px solid var(--color-ink);
  background: var(--color-seafoam);
  box-shadow: 3px 3px 0 var(--color-mint);
  font-size: 12px;
  font-weight: var(--font-weight-bold);
  color: var(--color-ink);
}

.resume-attach-icon {
  flex-shrink: 0;
}

.resume-attach-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.resume-attach-remove {
  appearance: none;
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  padding: 0;
  display: inline-grid;
  place-items: center;
  border: 2px solid var(--color-ink);
  background: var(--color-white);
  color: var(--color-ink);
  cursor: pointer;
}

.resume-attach-remove:hover:not(:disabled) {
  background: var(--color-peach);
  color: var(--color-white);
}

.resume-attach-remove:disabled {
  opacity: 0.5;
  cursor: wait;
}

.resume-attach-hint {
  font-size: 12px;
  font-weight: var(--font-weight-bold);
  color: var(--color-ink);
}

.composer-send {
  flex-shrink: 0;
  min-width: auto !important;
  height: auto !important;
  padding: 10px 18px !important;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.disclaimer {
  margin: var(--spacing-16) 0 0;
  font-size: 12px;
  font-weight: var(--font-weight-bold);
  color: var(--color-ink);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  overflow: hidden;
  border-top: 2px solid var(--color-ink);
  padding-top: 8px;
}

.source-credit {
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.4;
  color: var(--color-ink);
}

.source-credit a {
  color: inherit;
  text-decoration: underline;
}

.rail-backdrop {
  display: none;
}

@media (max-width: 860px) {
  .workbench {
    grid-template-columns: 1fr;
  }

  .rail-toggle {
    display: inline-flex;
  }

  .rail {
    position: fixed;
    inset: 0 auto 0 0;
    width: min(var(--space-rail), 86vw);
    transform: translateX(-105%);
    transition: transform var(--duration-spring) var(--ease-spring);
    box-shadow: none;
  }

  .workbench.rail-open .rail {
    transform: none;
    box-shadow: 8px 0 0 var(--color-ink);
  }

  .rail-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    background: color-mix(in srgb, var(--color-ink) 45%, transparent);
    z-index: 15;
  }

  .stage-title {
    font-size: 24px;
  }

  .composer-shell,
  .composer-shell:focus-within,
  .speech.user,
  .speech.assistant {
    transform: none;
  }

  .stage-bar-actions {
    max-width: min(200px, 52vw);
  }

  .stage-user {
    max-width: 7.5rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

@media (prefers-reduced-motion: reduce) {
  .rail {
    transition: none;
  }
  .stream-dot {
    animation: none;
  }
  .session,
  .resume-chip,
  .stage-user,
  .composer-shell,
  .speech.user,
  .speech.assistant,
  .attach-btn,
  .attach-btn:hover:not(:disabled) {
    transform: none !important;
  }
}
</style>
