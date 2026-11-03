<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type UploadRawFile } from 'element-plus'
import { useAuthStore } from '../stores/auth'

const AVATAR_MAX_BYTES = 2 * 1024 * 1024

const auth = useAuthStore()
const router = useRouter()

const displayName = ref('')
const savingProfile = ref(false)
const uploadingAvatar = ref(false)

const oldPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const savingPassword = ref(false)

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
  savingPassword.value = true
  try {
    await auth.changePassword(oldPassword.value, newPassword.value)
    ElMessage.success('密码已修改，请重新登录')
    router.push('/login')
  } catch (e) {
    ElMessage.error((e as Error).message || '修改密码失败')
  } finally {
    savingPassword.value = false
  }
}

async function logout() {
  await auth.logout()
  router.push('/login')
}
</script>

<template>
  <div class="desk">
    <header class="desk-bar">
      <div class="desk-brand">LawBot</div>
      <div class="desk-actions">
        <el-button text type="primary" @click="router.push('/chat')">返回咨询</el-button>
        <el-button text type="danger" @click="logout">退出登录</el-button>
      </div>
    </header>

    <main class="desk-main">
      <h1>个人中心</h1>
      <p class="lead">管理资料与登录安全</p>

      <section class="panel avatar-panel">
        <div class="avatar-wrap">
          <img v-if="avatarSrc" class="avatar" :src="avatarSrc" alt="头像" />
          <div v-else class="avatar placeholder">{{ avatarInitial }}</div>
        </div>
        <div class="avatar-actions">
          <el-upload
            :show-file-list="false"
            accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"
            :disabled="uploadingAvatar"
            :before-upload="beforeAvatarUpload"
          >
            <el-button type="primary" :loading="uploadingAvatar">
              {{ uploadingAvatar ? '上传中' : '更换头像' }}
            </el-button>
          </el-upload>
          <el-button
            v-if="avatarSrc"
            text
            type="danger"
            :disabled="uploadingAvatar"
            @click="onRemoveAvatar"
          >
            移除
          </el-button>
        </div>
      </section>

      <section class="panel">
        <h2>基本信息</h2>
        <el-form label-position="top">
          <el-form-item label="账号">
            <el-input :model-value="auth.user?.email || ''" disabled />
          </el-form-item>
          <el-form-item label="昵称">
            <div class="row">
              <el-input v-model="displayName" maxlength="100" placeholder="显示名称" />
              <el-button type="primary" :loading="savingProfile" @click="saveProfile">保存</el-button>
            </div>
          </el-form-item>
          <el-form-item label="角色">
            <el-input :model-value="roleLabel" disabled />
          </el-form-item>
          <el-form-item label="注册时间">
            <el-input :model-value="createdAtLabel" disabled />
          </el-form-item>
        </el-form>
      </section>

      <section class="panel">
        <h2>修改密码</h2>
        <el-form label-position="top" @submit.prevent="savePassword">
          <el-form-item label="旧密码">
            <el-input
              v-model="oldPassword"
              type="password"
              show-password
              autocomplete="current-password"
            />
          </el-form-item>
          <el-form-item label="新密码">
            <el-input
              v-model="newPassword"
              type="password"
              show-password
              autocomplete="new-password"
            />
          </el-form-item>
          <el-form-item label="确认新密码">
            <el-input
              v-model="confirmPassword"
              type="password"
              show-password
              autocomplete="new-password"
            />
          </el-form-item>
          <el-button type="primary" native-type="submit" :loading="savingPassword">
            修改密码
          </el-button>
        </el-form>
      </section>
    </main>
  </div>
</template>

<style scoped>
.desk {
  min-height: 100vh;
  min-height: 100dvh;
  background: var(--bg);
  display: flex;
  flex-direction: column;
}

.desk-bar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.85rem 1.25rem;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}

.desk-brand {
  font-family: var(--font-ui);
  font-weight: 700;
  font-size: 1.15rem;
  letter-spacing: -0.03em;
  color: var(--color-primary);
}

.desk-actions {
  display: flex;
  gap: 0.25rem;
}

.desk-main {
  width: min(560px, 94vw);
  margin: 0 auto;
  padding: 1.75rem 0.75rem 2.5rem;
}

h1 {
  margin: 0;
  font-family: var(--font-ui);
  font-size: var(--fs-title);
  font-weight: 600;
  letter-spacing: -0.02em;
}

.lead {
  margin: 0.35rem 0 1.35rem;
  color: var(--muted);
  font-size: var(--fs-small);
}

.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 1rem 1.1rem 1.15rem;
  margin-bottom: 0.9rem;
}

.panel h2 {
  margin: 0 0 0.85rem;
  font-family: var(--font-ui);
  font-size: 1rem;
  font-weight: 600;
  color: var(--text);
}

.avatar-panel {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.avatar {
  width: 88px;
  height: 88px;
  border-radius: 50%;
  object-fit: cover;
  display: block;
  background: var(--primary-soft);
}

.avatar.placeholder {
  display: grid;
  place-items: center;
  font-size: 2rem;
  font-weight: 700;
  color: var(--color-primary);
  font-family: var(--font-ui);
}

.avatar-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.25rem;
}

.row {
  display: flex;
  gap: 0.5rem;
  width: 100%;
}

.row .el-input {
  flex: 1;
}
</style>
