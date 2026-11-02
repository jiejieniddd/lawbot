<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api, streamChat, type ChatEvent, type Citation } from '../api/client'
import CitationCard from '../components/CitationCard.vue'
import { LEGAL_DISCLAIMER } from '../constants/disclaimer'
import { useAuthStore } from '../stores/auth'

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

const activeId = computed(() => (route.params.id as string) || '')
const isStreaming = computed(
  () => sending.value && (!!streamingText.value || streamingCitations.value.length > 0),
)

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
    router.push(`/chat/${conv.id}`)
  } catch (e) {
    ElMessage.error((e as Error).message || '创建会话失败')
  }
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

  try {
    await streamChat(cid, content, (ev: ChatEvent) => {
      if (ev.type === 'token') {
        streamingText.value += String(ev.data.text || '')
      } else if (ev.type === 'citation') {
        streamingCitations.value.push(ev.data as unknown as Citation)
      } else if (ev.type === 'done') {
        messages.value.push({
          id: String(ev.data.message_id || ''),
          role: 'assistant',
          content: streamingText.value,
          citations: [...streamingCitations.value],
        })
        streamingText.value = ''
        streamingCitations.value = []
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
  <div class="layout">
    <aside class="sidebar">
      <div class="brand">LawBot</div>
      <el-button type="primary" style="width: 100%; margin-bottom: 12px" @click="createConversation">
        新咨询
      </el-button>
      <div v-loading="loadingList" class="conv-list">
        <el-empty
          v-if="!loadingList && conversations.length === 0"
          description="暂无会话，点击「新咨询」开始"
          :image-size="64"
        />
        <div
          v-for="c in conversations"
          :key="c.id"
          class="conv"
          :class="{ active: c.id === activeId }"
          @click="router.push(`/chat/${c.id}`)"
        >
          {{ c.title }}
        </div>
      </div>
      <div class="foot">
        <div class="user-email">{{ auth.user?.email }}</div>
        <el-button text type="danger" @click="logout">退出</el-button>
      </div>
    </aside>
    <main class="main">
      <header class="topbar">
        <span class="topbar-title">法律咨询</span>
        <span class="topbar-user">{{ auth.user?.email }}</span>
      </header>
      <div v-loading="loadingMessages" class="messages">
        <el-empty
          v-if="!loadingMessages && !messages.length && !isStreaming"
          description="发送一条消息开始咨询"
          :image-size="80"
        />
        <div v-for="(m, i) in messages" :key="m.id || i" class="msg" :class="m.role">
          <div class="bubble">{{ m.content }}</div>
          <div v-if="m.citations?.length" class="cites">
            <CitationCard v-for="c in m.citations" :key="c.source_id" :citation="c" />
          </div>
        </div>
        <div v-if="isStreaming" class="msg assistant">
          <div v-if="streamingText" class="bubble">{{ streamingText }}</div>
          <div v-if="streamingCitations.length" class="cites">
            <CitationCard
              v-for="c in streamingCitations"
              :key="c.source_id"
              :citation="c"
            />
          </div>
        </div>
      </div>
      <div class="composer">
        <el-input
          v-model="input"
          type="textarea"
          :rows="3"
          :disabled="sending"
          placeholder="描述你的法律问题…"
          @keydown.ctrl.enter="send"
        />
        <el-button type="primary" :loading="sending" :disabled="sending" @click="send">
          发送
        </el-button>
      </div>
      <p class="disclaimer">{{ disclaimer }}</p>
    </main>
  </div>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 260px 1fr;
  min-height: 100vh;
  background: #f4f6f8;
}
.sidebar {
  background: #1f2a37;
  color: #e8eef5;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.brand {
  font-family: "Source Han Serif SC", "Noto Serif SC", Georgia, serif;
  font-size: 1.4rem;
  margin-bottom: 8px;
}
.conv-list {
  flex: 1;
  overflow: auto;
  min-height: 120px;
}
.conv-list :deep(.el-empty__description) {
  color: #9aa8b8;
}
.conv {
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.9rem;
  color: #c9d4e0;
}
.conv:hover,
.conv.active {
  background: #2b3a4c;
  color: #fff;
}
.foot {
  margin-top: auto;
  font-size: 0.8rem;
  opacity: 0.85;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.user-email {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.main {
  display: flex;
  flex-direction: column;
  padding: 16px 20px;
  max-width: 960px;
  width: 100%;
  margin: 0 auto;
}
.topbar {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 12px;
  gap: 12px;
}
.topbar-title {
  font-family: "Source Han Serif SC", "Noto Serif SC", Georgia, serif;
  font-size: 1.15rem;
  color: #1f2a37;
}
.topbar-user {
  font-size: 0.85rem;
  color: #667788;
}
.messages {
  flex: 1;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-bottom: 12px;
  min-height: 200px;
}
.msg.user {
  align-self: flex-end;
}
.msg.assistant {
  align-self: flex-start;
}
.bubble {
  background: #fff;
  border: 1px solid #e2e8f0;
  padding: 10px 14px;
  border-radius: 10px;
  max-width: 640px;
  white-space: pre-wrap;
}
.msg.user .bubble {
  background: #1f4e79;
  color: #fff;
  border-color: #1f4e79;
}
.cites {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.composer {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 10px;
  align-items: end;
}
.disclaimer {
  font-size: 0.75rem;
  color: #888;
  margin: 8px 0 0;
  line-height: 1.5;
}
@media (max-width: 800px) {
  .layout {
    grid-template-columns: 1fr;
  }
  .sidebar {
    max-height: 40vh;
    overflow: auto;
  }
}
</style>
