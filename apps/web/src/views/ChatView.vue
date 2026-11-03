<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Promotion } from '@element-plus/icons-vue'
import { api, streamChat, type ChatEvent, type Citation } from '../api/client'
import CitationCard from '../components/CitationCard.vue'
import { LEGAL_DISCLAIMER } from '../constants/disclaimer'
import { useAuthStore } from '../stores/auth'
import { renderMarkdown } from '../utils/markdown'

type Conversation = { id: string; title: string; status: string }
type Message = {
  id?: string
  role: string
  content: string
  citations?: Citation[]
}

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const conversations = ref<Conversation[]>([])
const messages = ref<Message[]>([])
const input = ref('')
const sending = ref(false)
const loadingList = ref(false)
const loadingMessages = ref(false)
const streamingText = ref('')
const streamingCitations = ref<Citation[]>([])
const disclaimer = LEGAL_DISCLAIMER
const messagesEl = ref<HTMLElement | null>(null)
const messagesEndEl = ref<HTMLElement | null>(null)
const railOpen = ref(false)

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
  let cid = activeId.value
  if (!cid) {
    try {
      const conv = await api<Conversation>('/api/v1/conversations', {
        method: 'POST',
        body: JSON.stringify({}),
      })
      cid = conv.id
      await loadConversations()
      router.replace(`/chat/${cid}`)
    } catch (e) {
      ElMessage.error((e as Error).message || '创建会话失败')
      return
    }
  }

  const content = input.value.trim()
  input.value = ''
  messages.value.push({ role: 'user', content })
  sending.value = true
  streamingText.value = ''
  streamingCitations.value = []
  scrollToBottom()

  try {
    await streamChat(cid, content, (ev: ChatEvent) => {
      if (ev.type === 'token') {
        streamingText.value += String(ev.data.text || '')
        scrollToBottom()
      } else if (ev.type === 'citation') {
        streamingCitations.value.push(ev.data as unknown as Citation)
        scrollToBottom()
      } else if (ev.type === 'done') {
        messages.value.push({
          id: String(ev.data.message_id || ''),
          role: 'assistant',
          content: streamingText.value,
          citations: [...streamingCitations.value],
        })
        streamingText.value = ''
        streamingCitations.value = []
        scrollToBottom()
        void loadConversations()
      } else if (ev.type === 'error') {
        ElMessage.error(String(ev.data.message || 'error'))
        streamingText.value = ''
        streamingCitations.value = []
      }
    })
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    sending.value = false
  }
}

async function logout() {
  await auth.logout()
  router.push('/login')
}

onMounted(async () => {
  try {
    await auth.fetchMe()
  } catch (e) {
    ElMessage.error((e as Error).message || '获取用户信息失败')
  }
  await loadConversations()
  if (activeId.value) await loadMessages(activeId.value)
})

watch(
  () => route.params.id,
  async (id) => {
    if (id) await loadMessages(id as string)
    else messages.value = []
  },
)
</script>

<template>
  <div class="workbench" :class="{ 'rail-open': railOpen }">
    <div v-if="railOpen" class="rail-backdrop" @click="railOpen = false" />
    <aside class="rail">
      <div class="rail-chrome">
        <div class="rail-brand">LawBot</div>
        <el-button type="primary" class="new-chat" @click="createConversation">新咨询</el-button>
      </div>
      <div v-loading="loadingList" class="session-list">
        <p v-if="!loadingList && conversations.length === 0" class="empty-hint">
          暂无会话，点击「新咨询」开始
        </p>
        <button
          v-for="c in conversations"
          :key="c.id"
          type="button"
          class="session"
          :class="{ active: c.id === activeId }"
          @click="openConversation(c.id)"
        >
          {{ c.title }}
        </button>
      </div>
      <div class="rail-foot rail-chrome">
        <div class="identity">
          <div class="avatar" aria-hidden="true">
            <img v-if="avatarSrc" :src="avatarSrc" alt="" />
            <span v-else>{{ avatarInitial }}</span>
          </div>
          <div class="identity-text">
            <div class="name">{{ displayLabel }}</div>
            <router-link class="profile-link" to="/profile">个人中心</router-link>
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
        <h1 class="stage-title">法律咨询</h1>
        <router-link class="stage-user" to="/profile">
          <span class="avatar sm" aria-hidden="true">
            <img v-if="avatarSrc" :src="avatarSrc" alt="" />
            <span v-else>{{ avatarInitial }}</span>
          </span>
          {{ displayLabel }}
        </router-link>
      </header>

      <div ref="messagesEl" v-loading="loadingMessages" class="thread">
        <p v-if="!loadingMessages && !messages.length && !isStreaming" class="thread-empty">
          发送一条消息开始咨询
        </p>
        <article v-for="(m, i) in messages" :key="m.id || i" class="turn" :class="m.role">
          <div
            v-if="m.role === 'assistant'"
            class="speech assistant md-body"
            v-html="renderMarkdown(m.content)"
          />
          <div v-else class="speech user">{{ m.content }}</div>
          <div v-if="m.citations?.length" class="cites">
            <CitationCard v-for="c in m.citations" :key="c.source_id" :citation="c" />
          </div>
        </article>
        <article v-if="isStreaming" class="turn assistant">
          <div
            v-if="streamingText"
            class="speech assistant md-body"
            v-html="renderMarkdown(streamingText)"
          />
          <div class="stream-live" aria-live="polite">
            <span class="stream-dot" />
            生成中
          </div>
          <div v-if="streamingCitations.length" class="cites">
            <CitationCard
              v-for="c in streamingCitations"
              :key="c.source_id"
              :citation="c"
            />
          </div>
        </article>
        <div ref="messagesEndEl" class="thread-end" aria-hidden="true" />
      </div>

      <div class="composer-dock">
        <div class="composer-shell">
          <el-input
            v-model="input"
            class="composer-input"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 6 }"
            :disabled="sending"
            placeholder="用大白话说说你遇到的事…"
            @keydown="onComposerKeydown"
          />
          <el-button
            class="composer-send"
            type="primary"
            circle
            :loading="sending"
            :disabled="sending || !input.trim()"
            aria-label="发送"
            @click="send"
          >
            <el-icon v-if="!sending"><Promotion /></el-icon>
          </el-button>
        </div>
        <p class="disclaimer" :title="disclaimer">{{ disclaimer }}</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.workbench {
  display: grid;
  grid-template-columns: var(--space-rail) 1fr;
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
  background: var(--bg);
}

.rail {
  background: var(--rail);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  padding: 1rem 0.85rem;
  gap: 0.65rem;
  z-index: 20;
}

.rail-chrome {
  flex-shrink: 0;
}

.rail-brand {
  font-family: var(--font-ui);
  font-weight: 700;
  font-size: 1.2rem;
  letter-spacing: -0.03em;
  color: var(--color-primary);
  margin-bottom: 0.55rem;
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
  gap: 4px;
}

.empty-hint {
  margin: 1rem 0.4rem;
  color: var(--muted);
  font-size: var(--fs-small);
  line-height: 1.45;
}

.session {
  appearance: none;
  border: 0;
  background: transparent;
  text-align: left;
  padding: 0.55rem 0.65rem;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font: inherit;
  font-size: var(--fs-small);
  color: var(--text);
  line-height: 1.35;
}

.session:hover {
  background: color-mix(in srgb, var(--color-primary) 8%, transparent);
}

.session.active {
  background: var(--primary-soft);
  color: var(--color-primary);
  font-weight: 600;
}

.rail-foot {
  margin-top: auto;
  padding-top: 0.65rem;
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.identity {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  min-width: 0;
  flex: 1;
}

.identity-text {
  min-width: 0;
}

.name {
  font-size: var(--fs-small);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.profile-link {
  font-size: var(--fs-fine);
  text-decoration: none;
}

.profile-link:hover {
  text-decoration: underline;
}

.avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  overflow: hidden;
  flex-shrink: 0;
  background: var(--primary-soft);
  color: var(--color-primary);
  font-size: 0.75rem;
  font-weight: 700;
  display: grid;
  place-items: center;
}

.avatar.sm {
  width: 24px;
  height: 24px;
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
  background: var(--bg);
}

.stage-bar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.85rem 1.25rem;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}

.rail-toggle {
  display: none;
  appearance: none;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  border-radius: var(--radius-sm);
  padding: 0.35rem 0.65rem;
  font: inherit;
  font-size: var(--fs-small);
  cursor: pointer;
}

.stage-title {
  margin: 0;
  font-family: var(--font-ui);
  font-size: var(--fs-title);
  font-weight: 600;
  letter-spacing: -0.02em;
  flex: 1;
}

.stage-user {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  color: var(--muted);
  text-decoration: none;
  font-size: var(--fs-small);
}

.stage-user:hover {
  color: var(--color-primary);
}

.thread {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
  padding: 1.1rem 1.25rem 0.75rem;
  max-width: 880px;
  width: 100%;
  margin: 0 auto;
  box-sizing: border-box;
}

.thread-empty {
  margin: 3rem auto;
  color: var(--muted);
  font-size: var(--fs-small);
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
  padding: 0.7rem 0.95rem;
  border-radius: var(--radius-md);
  font-size: var(--fs-body);
  line-height: 1.55;
}

.speech.user {
  background: var(--color-primary);
  color: #fff;
  white-space: pre-wrap;
  border-bottom-right-radius: 4px;
}

.speech.assistant {
  background: var(--surface);
  border: 1px solid var(--border);
  border-left: 3px solid var(--color-info);
  color: var(--text);
  border-bottom-left-radius: 4px;
}

.speech.md-body {
  white-space: normal;
}

.speech.md-body :deep(h2),
.speech.md-body :deep(h3) {
  margin: 0.75em 0 0.35em;
  font-size: 1.05rem;
  font-weight: 650;
  line-height: 1.35;
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
  padding: 0.35em 0.75em;
  border-left: 3px solid var(--color-info);
  color: var(--muted);
  background: var(--info-soft);
}

.speech.md-body :deep(strong) {
  font-weight: 650;
}

.speech.md-body :deep(a) {
  color: var(--color-primary);
  text-decoration: underline;
}

.speech.md-body :deep(code) {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 0.9em;
  padding: 0.1em 0.3em;
  background: var(--rail);
  border-radius: 3px;
}

.speech.md-body :deep(pre) {
  margin: 0.5em 0;
  padding: 0.6em 0.75em;
  overflow: auto;
  background: var(--rail);
  border-radius: var(--radius-sm);
}

.speech.md-body :deep(pre code) {
  padding: 0;
  background: transparent;
}

.cites {
  margin-top: 0.45rem;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  width: min(640px, 100%);
}

.stream-live {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.35rem;
  font-size: var(--fs-small);
  color: var(--muted);
}

.stream-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-success);
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
  border-top: 1px solid var(--border);
  background: var(--composer-bg);
  padding: 0.75rem 1.25rem 0.85rem;
  max-width: 880px;
  width: 100%;
  margin: 0 auto;
  box-sizing: border-box;
  box-shadow: 0 -6px 18px color-mix(in srgb, var(--text) 4%, transparent);
}

.composer-shell {
  display: flex;
  align-items: flex-end;
  gap: 0.55rem;
  padding: 0.55rem 0.55rem 0.55rem 0.85rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 18px;
  box-shadow: inset 0 1px 0 color-mix(in srgb, #fff 70%, transparent);
}

.composer-input {
  flex: 1;
  min-width: 0;
}

.composer-input :deep(.el-textarea__inner) {
  border: 0;
  box-shadow: none;
  background: transparent;
  padding: 0.35rem 0.15rem;
  resize: none;
  font-size: var(--fs-body);
  line-height: 1.5;
  color: var(--text);
}

.composer-input :deep(.el-textarea__inner:focus) {
  box-shadow: none;
}

.composer-send {
  flex-shrink: 0;
  width: 42px;
  height: 42px;
  min-width: 42px;
  min-height: 42px;
  padding: 0;
}

.disclaimer {
  margin: 0.45rem 0.15rem 0;
  font-size: 0.68rem;
  color: color-mix(in srgb, var(--muted) 78%, transparent);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  overflow: hidden;
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
    transition: transform 0.2s ease;
    box-shadow: none;
  }

  .workbench.rail-open .rail {
    transform: none;
    box-shadow: 8px 0 24px color-mix(in srgb, var(--text) 12%, transparent);
  }

  .rail-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    background: color-mix(in srgb, var(--text) 35%, transparent);
    z-index: 15;
  }

  .stage-title {
    font-size: 1.05rem;
  }
}

@media (prefers-reduced-motion: reduce) {
  .rail {
    transition: none;
  }
  .stream-dot {
    animation: none;
  }
}
</style>
