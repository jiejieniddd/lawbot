<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type UploadRawFile } from 'element-plus'
import { Briefcase, Document, Lock, User } from '@element-plus/icons-vue'
import { useAuthStore } from '../../stores/auth'
import { useJdStore } from '../../stores/jd'
import { useResumeStore } from '../../stores/resume'

const emit = defineEmits<{ close: [] }>()

const AVATAR_MAX_BYTES = 2 * 1024 * 1024
const JD_MAX_BYTES = 8 * 1024 * 1024

const auth = useAuthStore()
const resumeStore = useResumeStore()
const jdStore = useJdStore()
const router = useRouter()
const jdPaste = ref('')

const activeSection = ref<'profile' | 'security' | 'resume' | 'jd'>('profile')

const displayName = ref('')
const savingProfile = ref(false)
const uploadingAvatar = ref(false)

const oldPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const code = ref('')
const savingPassword = ref(false)
const sendingCode = ref(false)
const cooldown = ref(0)
let cooldownTimer: number | null = null

function startCooldown(seconds: number) {
  cooldown.value = Math.max(1, seconds)
  if (cooldownTimer != null) window.clearInterval(cooldownTimer)
  cooldownTimer = window.setInterval(() => {
    cooldown.value -= 1
    if (cooldown.value <= 0 && cooldownTimer != null) {
      window.clearInterval(cooldownTimer)
      cooldownTimer = null
    }
  }, 1000)
}

onUnmounted(() => {
  if (cooldownTimer != null) window.clearInterval(cooldownTimer)
})

const roleLabel = computed(() => {
  const role = auth.user?.role
  if (role === 'user') return '用户'
  if (role === 'admin') return '管理员'
  if (role === 'super_admin') return '超级管理员'
  return role || '—'
})

const createdAtLabel = computed(() => {
  const raw = auth.user?.created_at
  if (!raw) return '—'
  const d = new Date(raw)
  if (Number.isNaN(d.getTime())) return raw
  return d.toLocaleString('zh-CN')
})

const avatarSrc = computed(() => auth.user?.avatar_url || '')
const avatarInitial = computed(() => {
  const label = auth.user?.display_name?.trim() || auth.user?.email || '?'
  return label.slice(0, 1).toUpperCase()
})

onMounted(async () => {
  try {
    await auth.fetchMe()
    displayName.value = auth.user?.display_name || ''
    await resumeStore.fetchActive()
    await jdStore.fetchActive()
  } catch (e) {
    ElMessage.error((e as Error).message || '加载资料失败')
  }
})

function beforeJdUpload(file: UploadRawFile) {
  const name = (file.name || '').toLowerCase()
  const okExt =
    name.endsWith('.pdf') ||
    name.endsWith('.docx') ||
    name.endsWith('.png') ||
    name.endsWith('.txt')
  if (!okExt) {
    ElMessage.error('仅支持 PDF / DOCX / PNG / TXT')
    return false
  }
  if (file.size > JD_MAX_BYTES) {
    ElMessage.error('JD 不能超过 8MB')
    return false
  }
  void doJdUpload(file)
  return false
}

async function doJdUpload(file: File) {
  try {
    const row = await jdStore.upload(file)
    if (row.parse_status === 'ready') ElMessage.success('JD 已上传并解析')
    else ElMessage.warning(`上传完成，状态：${row.parse_status}`)
  } catch (e) {
    ElMessage.error((e as Error).message || 'JD 上传失败')
  }
}

async function onPasteJd() {
  const text = jdPaste.value.trim()
  if (text.length < 20) {
    ElMessage.warning('请粘贴至少 20 字的 JD 文本')
    return
  }
  try {
    await jdStore.paste(text)
    ElMessage.success('JD 文本已保存')
    jdPaste.value = ''
  } catch (e) {
    ElMessage.error((e as Error).message || '保存失败')
  }
}

async function onRemoveJd() {
  const id = jdStore.active?.id
  if (!id) return
  try {
    await jdStore.remove(id)
    ElMessage.success('已删除当前 JD')
  } catch (e) {
    ElMessage.error((e as Error).message || '删除失败')
  }
}

async function saveProfile() {
  const name = displayName.value.trim()
  if (!name) {
    ElMessage.warning('请输入昵称')
    return
  }
  savingProfile.value = true
  try {
    await auth.updateProfile(name)
    ElMessage.success('昵称已保存')
  } catch (e) {
    ElMessage.error((e as Error).message || '保存失败')
  } finally {
    savingProfile.value = false
  }
}

function beforeAvatarUpload(file: UploadRawFile) {
  const okType = ['image/jpeg', 'image/png', 'image/webp'].includes(file.type)
  if (!okType) {
    ElMessage.error('仅支持 jpeg / png / webp')
    return false
  }
  if (file.size > AVATAR_MAX_BYTES) {
    ElMessage.error('头像不能超过 2MB')
    return false
  }
  void doUpload(file)
  return false
}

async function doUpload(file: File) {
  uploadingAvatar.value = true
  try {
    await auth.uploadAvatar(file)
    ElMessage.success('头像已更新')
  } catch (e) {
    ElMessage.error((e as Error).message || '上传失败')
  } finally {
    uploadingAvatar.value = false
  }
}

async function onRemoveAvatar() {
  uploadingAvatar.value = true
  try {
    await auth.removeAvatar()
    ElMessage.success('已移除头像')
  } catch (e) {
    ElMessage.error((e as Error).message || '移除失败')
  } finally {
    uploadingAvatar.value = false
  }
}

async function sendPasswordCode() {
  if (!oldPassword.value) {
    ElMessage.warning('请先填写旧密码')
    return
  }
  sendingCode.value = true
  try {
    const data = await auth.sendChangePasswordCode(oldPassword.value)
    ElMessage.success(data.detail || '验证码已发送')
    startCooldown(data.retry_after_seconds || 60)
  } catch (e) {
    ElMessage.error((e as Error).message || '发送验证码失败')
  } finally {
    sendingCode.value = false
  }
}

async function savePassword() {
  if (!oldPassword.value || !newPassword.value) {
    ElMessage.warning('请填写旧密码与新密码')
    return
  }
  if (newPassword.value.length < 6) {
    ElMessage.warning('新密码至少 6 位')
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  if (!/^\d{6}$/.test(code.value.trim())) {
    ElMessage.warning('请输入 6 位验证码')
    return
  }
  savingPassword.value = true
  try {
    await auth.changePassword(oldPassword.value, newPassword.value, code.value.trim())
    ElMessage.success('密码已修改，请重新登录')
    emit('close')
    router.push('/login')
  } catch (e) {
    ElMessage.error((e as Error).message || '修改密码失败')
  } finally {
    savingPassword.value = false
  }
}

async function logout() {
  emit('close')
  await auth.logout()
  router.push('/login')
}
</script>

<template>
  <div class="panel-body">
    <nav class="shell-nav" aria-label="设置分类">
      <button
        type="button"
        class="nav-item"
        :class="{ active: activeSection === 'profile' }"
        @click="activeSection = 'profile'"
      >
        <el-icon class="nav-icon" :size="16"><User /></el-icon>
        账号资料
      </button>
      <button
        type="button"
        class="nav-item"
        :class="{ active: activeSection === 'security' }"
        @click="activeSection = 'security'"
      >
        <el-icon class="nav-icon" :size="16"><Lock /></el-icon>
        登录安全
      </button>
      <button
        type="button"
        class="nav-item"
        :class="{ active: activeSection === 'resume' }"
        @click="activeSection = 'resume'"
      >
        <el-icon class="nav-icon" :size="16"><Document /></el-icon>
        我的简历
      </button>
      <button
        type="button"
        class="nav-item"
        :class="{ active: activeSection === 'jd' }"
        @click="activeSection = 'jd'"
      >
        <el-icon class="nav-icon" :size="16"><Briefcase /></el-icon>
        岗位 JD
      </button>
    </nav>

    <div class="shell-pane">
      <section v-show="activeSection === 'profile'" class="pane-section">
        <div class="setting-row">
          <div class="row-label">头像</div>
          <div class="row-value avatar-row">
            <img v-if="avatarSrc" class="avatar" :src="avatarSrc" alt="头像" />
            <div v-else class="avatar placeholder">{{ avatarInitial }}</div>
            <div class="avatar-actions">
              <el-upload
                :show-file-list="false"
                accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"
                :disabled="uploadingAvatar"
                :before-upload="beforeAvatarUpload"
              >
                <el-button size="small" :loading="uploadingAvatar">
                  {{ uploadingAvatar ? '上传中' : '更换头像' }}
                </el-button>
              </el-upload>
              <el-button
                v-if="avatarSrc"
                size="small"
                text
                type="danger"
                :disabled="uploadingAvatar"
                @click="onRemoveAvatar"
              >
                移除
              </el-button>
            </div>
          </div>
        </div>

        <div class="setting-row">
          <div class="row-label">昵称</div>
          <div class="row-value row-inline">
            <el-input v-model="displayName" maxlength="100" placeholder="显示名称" />
            <el-button type="primary" :loading="savingProfile" @click="saveProfile">保存</el-button>
          </div>
        </div>

        <div class="setting-row">
          <div class="row-label">邮箱</div>
          <div class="row-value muted">{{ auth.user?.email || '—' }}</div>
        </div>

        <div class="setting-row">
          <div class="row-label">角色</div>
          <div class="row-value muted">{{ roleLabel }}</div>
        </div>

        <div class="setting-row">
          <div class="row-label">注册时间</div>
          <div class="row-value muted">{{ createdAtLabel }}</div>
        </div>

        <div class="setting-row">
          <div class="row-label">账号</div>
          <div class="row-value">
            <button type="button" class="btn-danger-outline" @click="logout">退出登录</button>
          </div>
        </div>
      </section>

      <section v-show="activeSection === 'resume'" class="pane-section">
        <div class="setting-row">
          <div class="row-label">当前简历</div>
          <div class="row-value">
            <div v-if="resumeStore.active" class="resume-card">
              <div class="resume-badge">{{ resumeStore.badgeLabel }}</div>
              <div class="muted">{{ resumeStore.active.filename }}</div>
              <div v-if="resumeStore.active.skills?.length" class="resume-skills">
                {{ resumeStore.active.skills.slice(0, 12).join(' · ') }}
              </div>
              <div v-if="resumeStore.active.error" class="resume-error">
                {{ resumeStore.active.error }}
              </div>
            </div>
            <div v-else class="muted">尚未上传简历</div>
            <p class="resume-hint">请在聊天发送区点击回形针上传或移除简历（PDF / DOCX / PNG）</p>
          </div>
        </div>
      </section>

      <section v-show="activeSection === 'jd'" class="pane-section">
        <div class="setting-row">
          <div class="row-label">当前 JD</div>
          <div class="row-value">
            <div v-if="jdStore.active" class="resume-card">
              <div class="resume-badge">{{ jdStore.badgeLabel }}</div>
              <div class="muted">{{ jdStore.active.filename }}</div>
              <div v-if="jdStore.active.skills?.length" class="resume-skills">
                {{ jdStore.active.skills.slice(0, 12).join(' · ') }}
              </div>
            </div>
            <div v-else class="muted">尚未上传/粘贴 JD</div>
            <div class="avatar-actions" style="margin-top: 10px">
              <el-upload
                :show-file-list="false"
                accept=".pdf,.docx,.png,.txt"
                :disabled="jdStore.uploading"
                :before-upload="beforeJdUpload"
              >
                <el-button size="small" type="primary" :loading="jdStore.uploading">
                  上传 JD
                </el-button>
              </el-upload>
              <el-button
                v-if="jdStore.active"
                size="small"
                text
                type="danger"
                :disabled="jdStore.uploading"
                @click="onRemoveJd"
              >
                删除
              </el-button>
            </div>
            <div style="margin-top: 12px">
              <el-input
                v-model="jdPaste"
                type="textarea"
                :rows="4"
                placeholder="或粘贴 JD 文本（岗位职责 / 任职要求）"
              />
              <el-button
                style="margin-top: 8px"
                size="small"
                :loading="jdStore.uploading"
                @click="onPasteJd"
              >
                保存粘贴 JD
              </el-button>
            </div>
          </div>
        </div>
      </section>

      <section v-show="activeSection === 'security'" class="pane-section">
        <form class="security-form" @submit.prevent="savePassword">
          <div class="setting-row">
            <div class="row-label">旧密码</div>
            <div class="row-value">
              <el-input
                v-model="oldPassword"
                type="password"
                show-password
                autocomplete="current-password"
              />
            </div>
          </div>
          <div class="setting-row">
            <div class="row-label">新密码</div>
            <div class="row-value">
              <el-input
                v-model="newPassword"
                type="password"
                show-password
                autocomplete="new-password"
              />
            </div>
          </div>
          <div class="setting-row">
            <div class="row-label">确认新密码</div>
            <div class="row-value">
              <el-input
                v-model="confirmPassword"
                type="password"
                show-password
                autocomplete="new-password"
              />
            </div>
          </div>
          <div class="setting-row">
            <div class="row-label">邮箱验证码</div>
            <div class="row-value row-inline">
              <el-input
                v-model="code"
                inputmode="numeric"
                maxlength="6"
                autocomplete="one-time-code"
                placeholder="6 位数字"
              />
              <el-button
                native-type="button"
                :loading="sendingCode"
                :disabled="cooldown > 0"
                @click="sendPasswordCode"
              >
                {{ cooldown > 0 ? `${cooldown}s` : '获取验证码' }}
              </el-button>
            </div>
          </div>
          <div class="setting-row">
            <div class="row-label" />
            <div class="row-value">
              <el-button type="primary" native-type="submit" :loading="savingPassword">
                修改密码
              </el-button>
            </div>
          </div>
        </form>
      </section>
    </div>
  </div>
</template>

<style scoped>
.panel-body {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 180px 1fr;
  overflow: hidden;
}

.shell-nav {
  flex-shrink: 0;
  padding: var(--spacing-16) var(--spacing-8);
  border-right: 4px solid var(--color-ink);
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: var(--color-white);
}

.nav-item {
  appearance: none;
  border: 2px solid transparent;
  background: transparent;
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  text-align: left;
  padding: 10px 12px;
  border-radius: 0;
  font: inherit;
  font-size: var(--text-label);
  font-weight: var(--font-weight-bold);
  color: var(--color-ink);
  cursor: pointer;
  transition:
    transform var(--duration-spring) var(--ease-spring),
    box-shadow var(--duration-spring) var(--ease-spring),
    background-color var(--duration-spring) var(--ease-spring);
}

.nav-item:hover {
  background: var(--color-sunny);
  border-color: var(--color-ink);
  box-shadow: 3px 3px 0 var(--color-mint);
  transform: rotate(1deg);
}

.nav-item.active {
  background: var(--color-coral);
  color: var(--color-white);
  border-color: var(--color-ink);
  font-weight: var(--font-weight-black);
  box-shadow: 4px 4px 0 var(--color-ink);
  transform: rotate(-1deg);
}

.nav-icon {
  flex-shrink: 0;
}

.shell-pane {
  min-height: 0;
  overflow: auto;
  padding: var(--spacing-8) var(--spacing-16) var(--spacing-24);
}

.pane-section {
  padding: 0;
}

.setting-row {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: var(--spacing-16);
  align-items: center;
  padding: var(--spacing-16) 0;
  border-bottom: 2px solid var(--color-ink);
}

.row-label {
  font-size: var(--text-label);
  font-weight: var(--font-weight-black);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--color-ink);
}

.row-value {
  min-width: 0;
}

.row-value.muted {
  color: var(--color-ink);
  font-size: var(--text-body);
  font-weight: var(--font-weight-bold);
}

.row-inline {
  display: flex;
  gap: 8px;
  align-items: center;
}

.row-inline .el-input {
  flex: 1;
}

.avatar-row {
  display: flex;
  align-items: center;
  gap: 14px;
}

.avatar {
  width: 56px;
  height: 56px;
  border-radius: 0;
  object-fit: cover;
  display: block;
  background: var(--color-sunny);
  border: 3px solid var(--color-ink);
  box-shadow: 4px 4px 0 var(--color-mint);
  flex-shrink: 0;
}

.avatar.placeholder {
  display: grid;
  place-items: center;
  font-size: 1.25rem;
  font-weight: var(--font-weight-black);
  color: var(--color-ink);
  font-family: var(--font-ui);
}

.avatar-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.btn-danger-outline {
  appearance: none;
  background: var(--color-white);
  border: 3px solid var(--color-ink);
  color: var(--color-peach);
  border-radius: 0;
  padding: 8px 14px;
  font: inherit;
  font-size: var(--text-label);
  font-weight: var(--font-weight-black);
  cursor: pointer;
  box-shadow: 3px 3px 0 var(--color-peach);
}

.btn-danger-outline:hover {
  background: var(--color-peach);
  color: var(--color-white);
}

.security-form {
  margin: 0;
}

.resume-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.resume-badge {
  display: inline-flex;
  width: fit-content;
  padding: 4px 10px;
  border-radius: 0;
  background: var(--color-seafoam);
  border: 2px solid var(--color-ink);
  font-size: 12px;
  font-weight: var(--font-weight-bold);
  box-shadow: 3px 3px 0 var(--color-mint);
}

.resume-skills {
  font-size: var(--text-label);
  color: var(--color-ink);
  line-height: 1.4;
  font-weight: var(--font-weight-bold);
}

.resume-error {
  font-size: 12px;
  font-weight: var(--font-weight-bold);
  color: var(--color-peach);
}

.resume-hint {
  margin: 10px 0 0;
  font-size: 12px;
  font-weight: var(--font-weight-bold);
  color: var(--color-ink);
  line-height: 1.4;
}

@media (max-width: 720px) {
  .panel-body {
    grid-template-columns: 1fr;
    grid-template-rows: auto 1fr;
  }
  .shell-nav {
    flex-direction: row;
    border-right: 0;
    border-bottom: 4px solid var(--color-ink);
    overflow-x: auto;
  }
  .nav-item {
    width: auto;
    white-space: nowrap;
  }
  .nav-item:hover,
  .nav-item.active {
    transform: none;
  }
  .setting-row {
    grid-template-columns: 1fr;
    gap: 8px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .nav-item:hover,
  .nav-item.active {
    transform: none;
  }
}
</style>
