<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type UploadRawFile } from 'element-plus'
import { Document, Lock, User } from '@element-plus/icons-vue'
import { useAuthStore } from '../../stores/auth'
import { useResumeStore } from '../../stores/resume'

const emit = defineEmits<{ close: [] }>()

const AVATAR_MAX_BYTES = 2 * 1024 * 1024

const auth = useAuthStore()
const resumeStore = useResumeStore()
const router = useRouter()

const activeSection = ref<'profile' | 'security' | 'resume'>('profile')

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
  } catch (e) {
    ElMessage.error((e as Error).message || '加载资料失败')
  }
})

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
            <button
              v-if="resumeStore.active"
              type="button"
              class="resume-card resume-card-btn"
              title="查看简历"
              @click="resumeStore.openPreview(resumeStore.active)"
            >
              <div class="resume-card-top">
                <div class="resume-badge">{{ resumeStore.badgeLabel }}</div>
                <span class="resume-view-hint">查看</span>
              </div>
              <div class="muted">{{ resumeStore.active.filename }}</div>
              <div v-if="resumeStore.active.skills?.length" class="resume-skills">
                {{ resumeStore.active.skills.slice(0, 12).join(' · ') }}
              </div>
              <div v-if="resumeStore.active.error" class="resume-error">
                {{ resumeStore.active.error }}
              </div>
            </button>
            <div v-else class="muted">尚未上传简历</div>
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

.resume-card-btn {
  appearance: none;
  width: 100%;
  text-align: left;
  font: inherit;
  color: inherit;
  cursor: pointer;
  padding: 12px;
  border: 3px solid var(--color-ink);
  background: var(--color-white);
  box-shadow: 4px 4px 0 var(--color-mint);
  transition:
    transform var(--duration-spring) var(--ease-spring),
    box-shadow var(--duration-spring) var(--ease-spring),
    background-color var(--duration-spring) var(--ease-spring);
}

.resume-card-btn:hover {
  background: var(--color-sunny);
  transform: translateY(-2px) rotate(-0.5deg);
  box-shadow: 6px 6px 0 var(--color-ink);
}

.resume-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.resume-view-hint {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: var(--font-weight-bold);
  letter-spacing: 0.06em;
  padding: 2px 8px;
  border: 2px solid var(--color-ink);
  background: var(--color-mint);
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
