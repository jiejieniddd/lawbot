<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Document, Setting } from '@element-plus/icons-vue'
import ResumePreviewDialog from '../components/settings/ResumePreviewDialog.vue'
import SettingsModal from '../components/settings/SettingsModal.vue'
import PixelToggle from '../components/theme/PixelToggle.vue'
import { useAuthStore } from '../stores/auth'
import { useInterviewStore } from '../stores/interview'
import { useResumeStore } from '../stores/resume'
import { useThemeStore } from '../stores/theme'

const auth = useAuthStore()
const resumeStore = useResumeStore()
const themeStore = useThemeStore()
const interview = useInterviewStore()
const route = useRoute()
const router = useRouter()

const railOpen = ref(false)
const settingsOpen = ref(false)
const questionCount = ref<5 | 8>(5)
const targetRole = ref('')
const jdText = ref('')
const answer = ref('')

const resumeReady = computed(() => resumeStore.active?.parse_status === 'ready')
const canStart = computed(
  () => Boolean(targetRole.value.trim()) || Boolean(jdText.value.trim()),
)
const displayLabel = computed(() => auth.user?.display_name || auth.user?.email || '我')
const avatarSrc = computed(() => auth.user?.avatar_url || '')
const avatarInitial = computed(() => displayLabel.value.slice(0, 1).toUpperCase())

const progressLabel = computed(() => {
  const s = interview.session
  if (!s) return ''
  const cur = s.answered_count + (s.current_question ? 1 : 0)
  return `${Math.min(cur, s.question_count)} / ${s.question_count}`
})

async function bootstrap() {
  await Promise.all([
    resumeStore.fetchActive().catch(() => undefined),
    auth.fetchMe().catch(() => undefined),
  ])
  const id = route.params.id as string | undefined
  if (id) {
    try {
      await interview.loadSession(id)
    } catch (e) {
      ElMessage.error((e as Error).message || '加载失败')
      interview.reset()
      await router.replace('/interview')
    }
  } else {
    interview.reset()
  }
}

onMounted(() => {
  void bootstrap()
})

watch(
  () => route.params.id,
  () => {
    void bootstrap()
  },
)

async function start() {
  if (!canStart.value) {
    ElMessage.warning('请填写目标岗位，或粘贴本场 JD')
    return
  }
  try {
    const s = await interview.createSession({
      question_count: questionCount.value,
      target_role: targetRole.value.trim(),
      jd_text: jdText.value.trim(),
    })
    await router.replace(`/interview/${s.id}`)
  } catch (e) {
    const msg = ((e as Error).message || '').trim()
    ElMessage.error(msg || '无法开始面试，请稍后重试')
  }
}

async function submit() {
  const text = answer.value.trim()
  if (!text) {
    ElMessage.warning('请先填写回答')
    return
  }
  try {
    const data = await interview.submitAnswer(text)
    answer.value = ''
    if (data.done) {
      ElMessage.success('本轮面试结束，已生成报告')
    }
  } catch (e) {
    ElMessage.error((e as Error).message || '提交失败')
  }
}

function again() {
  interview.reset()
  answer.value = ''
  // Keep targetRole / jdText so user can tweak before next round; clear JD if desired:
  // leave fields for quick retry with same role.
  void router.replace('/interview')
}

async function logout() {
  await auth.logout()
  await router.push('/login')
}
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
          <router-link class="nav-link" to="/chat">求职助手</router-link>
          <router-link class="nav-link active" to="/interview">模拟面试</router-link>
        </nav>
      </div>
      <div class="rail-hint">
        <p>固定题量 · 一题一答</p>
        <p>结束后生成能力初评</p>
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
        <button type="button" class="rail-toggle" aria-label="导航" @click="railOpen = !railOpen">
          菜单
        </button>
        <h1 class="stage-title">模拟面试</h1>
        <button
          v-if="resumeStore.badgeLabel"
          type="button"
          class="resume-chip"
          title="可选：在设置中管理简历"
          @click="settingsOpen = true"
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
        </div>
      </header>

      <div class="thread-scroll">
        <!-- Prep -->
        <div v-if="interview.phase === 'prep'" class="panel prep">
          <p class="empty-title">准备模拟面试</p>
          <p class="empty-sub">本场填写目标岗位或 JD，答完给出能力初评（简历可选）</p>

          <div class="checklist">
            <div class="check-row" :class="{ ok: resumeReady }">
              <span>简历（可选）</span>
              <strong>{{ resumeReady ? '已就绪，出题/报告会结合简历' : '未上传亦可开始' }}</strong>
              <el-button size="small" @click="settingsOpen = true">
                {{ resumeReady ? '查看' : '可选上传' }}
              </el-button>
            </div>
          </div>

          <label class="field">
            <span>目标岗位（本场）</span>
            <el-input
              v-model="targetRole"
              placeholder="如：后端开发 / Python 后端 / 算法工程师"
              maxlength="80"
            />
          </label>

          <label class="field">
            <span>岗位 JD（本场可选）</span>
            <el-input
              v-model="jdText"
              type="textarea"
              :rows="5"
              maxlength="50000"
              show-word-limit
              placeholder="粘贴本场面试对应的 JD 原文；可与目标岗位二选一或同时填写"
            />
          </label>

          <label class="field">
            <span>题量</span>
            <el-radio-group v-model="questionCount">
              <el-radio :value="5">5 题</el-radio>
              <el-radio :value="8">8 题</el-radio>
            </el-radio-group>
          </label>

          <el-button
            type="primary"
            class="start-btn"
            :disabled="!canStart || interview.loading"
            :loading="interview.loading"
            @click="start"
          >
            开始模拟
          </el-button>
          <p v-if="!canStart" class="empty-sub start-hint">请填写本场目标岗位，或粘贴 JD</p>
        </div>

        <!-- Live -->
        <div v-else-if="interview.phase === 'live'" class="panel live">
          <div class="progress">进度 {{ progressLabel }} · {{ interview.session?.target_role }}</div>
          <article
            v-for="t in interview.session?.turns || []"
            :key="t.id"
            class="turn"
            :class="{ pending: !t.answered && t.seq === interview.session?.current_seq }"
          >
            <div class="speech assistant">
              <div class="q-label">第 {{ t.seq }} 题</div>
              {{ t.question }}
            </div>
            <div v-if="t.answered" class="speech user">{{ t.answer }}</div>
            <div v-if="t.answered && t.feedback" class="speech note">
              得分 {{ t.score }} · {{ t.feedback }}
            </div>
          </article>

          <div v-if="interview.session?.current_question" class="composer-shell">
            <el-input
              v-model="answer"
              type="textarea"
              :rows="4"
              placeholder="写下你的回答…"
              :disabled="interview.submitting"
            />
            <el-button
              type="primary"
              :loading="interview.submitting"
              @click="submit"
            >
              提交回答
            </el-button>
          </div>
        </div>

        <!-- Report -->
        <div v-else class="panel report">
          <p class="empty-title">面试报告</p>
          <p class="score-line">
            总分 <strong>{{ interview.report?.total_score ?? '—' }}</strong>
            · {{ interview.report?.target_role || interview.session?.target_role }}
          </p>
          <p v-if="interview.report?.resume_note" class="resume-note">
            {{ interview.report.resume_note }}
          </p>
          <div v-if="interview.report?.dimension_averages" class="dims">
            <span v-for="(v, k) in interview.report.dimension_averages" :key="k">
              {{ k }} {{ v }}
            </span>
          </div>
          <div class="gaps">
            <h3>相对岗位的能力缺口</h3>
            <ul>
              <li v-for="(g, i) in interview.report?.gaps || []" :key="i">
                <strong>{{ g.skill }}</strong> — {{ g.suggestion }}
              </li>
            </ul>
            <p v-if="!(interview.report?.gaps || []).length" class="empty-sub">暂无显著缺口条目</p>
          </div>
          <div class="advice speech assistant">{{ interview.report?.advice }}</div>
          <div class="turn-briefs">
            <h3>逐题简评</h3>
            <article v-for="t in interview.report?.turns || []" :key="t.seq" class="brief">
              <div class="speech assistant">第 {{ t.seq }} 题（{{ t.score }} 分）· {{ t.question }}</div>
              <div class="speech note">{{ t.feedback }}</div>
            </article>
          </div>
          <p class="disclaimer">{{ interview.report?.disclaimer || 'AI 初评仅供参考' }}</p>
          <div class="report-actions">
            <el-button type="primary" @click="again">再练一轮</el-button>
            <el-button @click="router.push('/chat')">回到聊天</el-button>
          </div>
        </div>
      </div>
    </section>

    <SettingsModal v-model:open="settingsOpen" />
    <ResumePreviewDialog />
  </div>
</template>

<style scoped>
.workbench {
  display: grid;
  grid-template-columns: var(--space-rail, 280px) 1fr;
  min-height: 100vh;
  background: var(--surface);
  color: var(--color-ink);
}
.rail {
  border-right: 4px solid var(--color-ink);
  display: flex;
  flex-direction: column;
  padding: var(--spacing-16);
  background: var(--surface);
}
.rail-brand {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.brand-text {
  font-size: 1.35rem;
  font-weight: var(--font-weight-black);
}
.brand-badge {
  width: 12px;
  height: 12px;
  background: var(--color-coral);
  border: 2px solid var(--color-ink);
}
.rail-nav {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
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
.rail-hint {
  font-size: var(--text-label);
  opacity: 0.8;
  flex: 1;
}
.rail-foot {
  margin-top: auto;
  padding-top: var(--spacing-16);
  border-top: 4px solid var(--color-ink);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.identity {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.avatar {
  width: 36px;
  height: 36px;
  border: 3px solid var(--color-ink);
  display: grid;
  place-items: center;
  overflow: hidden;
  background: var(--color-mint);
  font-weight: var(--font-weight-black);
}
.avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.name {
  font-weight: var(--font-weight-black);
  font-size: var(--text-label);
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
}
.stage {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.stage-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 4px solid var(--color-ink);
  flex-wrap: wrap;
}
.stage-title {
  margin: 0;
  font-size: 1.1rem;
  font-weight: var(--font-weight-black);
}
.rail-toggle {
  display: none;
}
.resume-chip {
  appearance: none;
  border: 3px solid var(--color-ink);
  background: var(--color-coral);
  padding: 4px 8px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-weight: var(--font-weight-bold);
  cursor: pointer;
}
.resume-chip.mint {
  background: var(--color-mint);
}
.stage-bar-actions {
  margin-left: auto;
}
.thread-scroll {
  flex: 1;
  overflow: auto;
  padding: 24px 16px 40px;
}
.panel {
  width: min(720px, 100%);
  margin: 0 auto;
}
.empty-title {
  font-size: 1.5rem;
  font-weight: var(--font-weight-black);
  margin: 0 0 8px;
}
.empty-sub {
  margin: 0 0 20px;
  opacity: 0.85;
}
.checklist {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 20px;
}
.check-row {
  border: 3px solid var(--color-ink);
  padding: 10px 12px;
  display: flex;
  align-items: center;
  gap: 12px;
  background: var(--surface);
}
.check-row.ok {
  background: color-mix(in srgb, var(--color-mint) 35%, var(--surface));
}
.check-row span {
  flex-shrink: 0;
  white-space: nowrap;
  font-weight: var(--font-weight-bold);
}
.check-row strong {
  flex: 1;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
  font-weight: var(--font-weight-bold);
}
.start-btn {
  width: 100%;
  border-width: 3px !important;
}
.progress {
  font-weight: var(--font-weight-black);
  margin-bottom: 16px;
}
.turn {
  margin-bottom: 16px;
}
.speech {
  border: 3px solid var(--color-ink);
  padding: 12px 14px;
  margin-bottom: 8px;
  background: var(--surface);
}
.speech.assistant {
  box-shadow: 4px 4px 0 var(--color-mint);
}
.speech.user {
  background: var(--color-coral);
  box-shadow: 4px 4px 0 var(--color-ink);
}
.speech.note {
  background: var(--color-sunny);
  font-size: 0.95rem;
}
.q-label {
  font-weight: var(--font-weight-black);
  margin-bottom: 6px;
}
.composer-shell {
  border: 4px solid var(--color-ink);
  padding: 12px;
  box-shadow: 4px 4px 0 var(--color-mint);
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 20px;
}
.score-line {
  font-size: 1.2rem;
  margin-bottom: 12px;
}
.resume-note {
  border: 3px solid var(--color-ink);
  background: var(--color-sunny);
  padding: 8px 12px;
  font-weight: var(--font-weight-bold);
  margin-bottom: 16px;
}
.start-hint {
  margin-top: 10px;
  text-align: center;
}
.dims {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}
.dims span {
  border: 2px solid var(--color-ink);
  padding: 4px 8px;
  font-weight: var(--font-weight-bold);
  background: var(--color-seafoam, var(--color-mint));
}
.gaps h3,
.turn-briefs h3 {
  margin: 16px 0 8px;
  font-weight: var(--font-weight-black);
}
.gaps ul {
  margin: 0;
  padding-left: 1.2rem;
}
.advice {
  margin: 16px 0;
}
.disclaimer {
  margin-top: 20px;
  font-size: 0.9rem;
  opacity: 0.8;
}
.report-actions {
  display: flex;
  gap: 10px;
  margin-top: 16px;
}
.rail-backdrop {
  display: none;
}

@media (max-width: 860px) {
  .workbench {
    grid-template-columns: 1fr;
  }
  .rail {
    position: fixed;
    inset: 0 auto 0 0;
    width: min(280px, 86vw);
    z-index: 40;
    transform: translateX(-105%);
    transition: transform 0.2s ease;
  }
  .workbench.rail-open .rail {
    transform: translateX(0);
  }
  .rail-toggle {
    display: inline-flex;
    appearance: none;
    border: 3px solid var(--color-ink);
    background: var(--color-sunny);
    padding: 4px 10px;
    font-weight: var(--font-weight-bold);
    cursor: pointer;
  }
  .rail-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    background: rgb(0 0 0 / 35%);
    z-index: 30;
  }
}
</style>
